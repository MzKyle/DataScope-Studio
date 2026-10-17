"""Benchmark-only typed wide SQLite samples plus small metadata/state dictionaries."""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path
from time import perf_counter

REPO = Path(__file__).resolve().parents[1]
if __package__ in {None, ''}:
    sys.path.insert(0, str(REPO))

from benchmarks.backend_common import fields_for, identifier
from benchmarks.benchmark_memory import MemorySampler

VARIANTS = ('none', 'time', 'minimal', 'covering')


def configure(conn: sqlite3.Connection, *, writing: bool = False) -> None:
    conn.execute('PRAGMA cache_size = -65536')
    conn.execute('PRAGMA temp_store = FILE')
    if writing:
        conn.execute('PRAGMA journal_mode = WAL')
        conn.execute('PRAGMA synchronous = FULL')


def create_dictionaries(conn, manifest: dict) -> None:
    conn.execute('CREATE TABLE recording_dictionary (recording_key INTEGER PRIMARY KEY, recording_id TEXT NOT NULL, source_id TEXT NOT NULL)')
    conn.execute('CREATE TABLE field_dictionary (recording_key INTEGER NOT NULL, key TEXT NOT NULL, entity_path TEXT NOT NULL, semantic_type TEXT NOT NULL, kind TEXT NOT NULL, PRIMARY KEY (recording_key, key))')
    conn.execute('CREATE TABLE state_dictionary (value_id INTEGER PRIMARY KEY, value TEXT NOT NULL)')
    conn.executemany('INSERT INTO recording_dictionary VALUES (?, ?, ?)', [
        (row['recording_key'], row['recording_id'], row['source_id']) for row in manifest['recordings']])
    conn.executemany('INSERT INTO field_dictionary VALUES (?, ?, ?, ?, ?)', [
        tuple(row[key] for key in ('recording_key', 'key', 'entity_path', 'semantic_type', 'kind'))
        for row in manifest['fields']])
    conn.executemany('INSERT INTO state_dictionary VALUES (?, ?)', [
        (row['value_id'], row['value']) for row in manifest['state_dictionary']])


def build_typed(path: Path, manifest: dict, variant: str, memory: MemorySampler,
                batch_size: int = 10000) -> dict:
    if variant not in VARIANTS:
        raise ValueError('Unknown typed SQLite index variant')
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    started = perf_counter()
    conn = sqlite3.connect(path)
    configure(conn, writing=True)
    fields = fields_for(manifest, 1)
    numeric = [field for field in fields if field['kind'] != 'text']
    states = [field for field in fields if field['kind'] == 'text']
    codes = {row['value']: row['value_id'] for row in manifest['state_dictionary']}
    insert_ms = 0.
    try:
        with memory.stage('schema'):
            create_dictionaries(conn, manifest)
            conn.execute('CREATE TABLE numeric_samples (recording_key INTEGER NOT NULL, time REAL NOT NULL, '
                         + ', '.join(identifier(field['key']) + (' INTEGER' if field['kind'] == 'integer' else ' REAL')
                                     + ' NOT NULL' for field in numeric) + ')')
            conn.execute('CREATE TABLE state_samples (recording_key INTEGER NOT NULL, time REAL NOT NULL, '
                         + ', '.join(identifier(field['key']) + ' INTEGER NOT NULL' for field in states) + ')')
            conn.commit()
        schema_ms = (perf_counter() - started) * 1000
        load_started = perf_counter()
        with memory.stage('insert'):
            conn.execute('BEGIN')
            for recording in manifest['recordings']:
                numeric_batch, state_batch = [], []
                count = 0
                with Path(recording['csv_path']).open(encoding='utf-8', newline='') as handle:
                    for sample in csv.DictReader(handle):
                        time = float(sample['timestamp'])
                        numeric_batch.append((recording['recording_key'], time, *(
                            int(sample[field['key']]) if field['kind'] == 'integer' else float(sample[field['key']])
                            for field in numeric)))
                        state_batch.append((recording['recording_key'], time, *(
                            codes[sample[field['key']]] for field in states)))
                        count += 1
                        if len(numeric_batch) >= batch_size:
                            insert_ms += insert_batches(conn, numeric_batch, state_batch)
                            numeric_batch, state_batch = [], []
                        if count % 250000 == 0:
                            print(f'  typed SQLite inserted {count:,}/{recording["rows"]:,} samples', flush=True)
                if numeric_batch:
                    insert_ms += insert_batches(conn, numeric_batch, state_batch)
                if count != recording['rows']:
                    raise AssertionError('Typed SQLite source row count mismatch')
            conn.commit()
        load_ms = (perf_counter() - load_started) * 1000
        indexes = []
        if variant != 'none':
            indexes = [('idx_numeric_time', 'numeric_samples', 'recording_key, time'),
                       ('idx_state_time', 'state_samples', 'recording_key, time')]
        if variant in {'minimal', 'covering'}:
            indexes += [('idx_numeric_battery', 'numeric_samples', 'recording_key, battery, time'),
                        ('idx_state_value', 'state_samples', 'recording_key, robot_state, time')]
        if variant == 'covering':
            indexes[0] = ('idx_numeric_time_covering', 'numeric_samples', 'recording_key, time, battery, temperature')
        index_started = perf_counter()
        with memory.stage('indexes'):
            for name, table, columns in indexes:
                conn.execute(f'CREATE INDEX {name} ON {table} ({columns})')
            conn.execute('ANALYZE')
            conn.commit()
        index_ms = (perf_counter() - index_started) * 1000
        checkpoint_started = perf_counter()
        with memory.stage('checkpoint'):
            if conn.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0] != 0:
                raise RuntimeError('Typed SQLite checkpoint was busy')
        checkpoint_ms = (perf_counter() - checkpoint_started) * 1000
        total_ms = (perf_counter() - started) * 1000
        count = conn.execute('SELECT count(*) FROM numeric_samples').fetchone()[0]
        state_count = conn.execute('SELECT count(*) FROM state_samples').fetchone()[0]
        expected = sum(row['rows'] for row in manifest['recordings'])
        if count != expected or state_count != expected:
            raise AssertionError('Typed SQLite physical sample count mismatch')
        pragmas = {key: conn.execute('PRAGMA ' + key).fetchone()[0] for key in (
            'journal_mode', 'synchronous', 'cache_size', 'temp_store', 'page_size')}
    finally:
        conn.close()
    return {'schema_ms': schema_ms, 'load_ms': load_ms, 'sql_insert_ms': insert_ms,
            'index_ms': index_ms, 'checkpoint_ms': checkpoint_ms, 'total_preparation_ms': total_ms,
            'physical_sample_rows': count + state_count, 'numeric_sample_rows': count,
            'state_sample_rows': state_count, 'secondary_indexes': indexes, 'sqlite_pragmas': pragmas,
            'storage_bytes': path.stat().st_size,
            'storage_scope': 'numeric/state sample tables plus recording/field/state dictionaries and declared indexes',
            'layout': 'wide numeric and dictionary-encoded state samples; no value_json or per-field persisted expansion'}


def insert_batches(conn, numeric: list[tuple], states: list[tuple]) -> float:
    started = perf_counter()
    conn.executemany('INSERT INTO numeric_samples VALUES (' + ','.join('?' for _ in numeric[0]) + ')', numeric)
    conn.executemany('INSERT INTO state_samples VALUES (' + ','.join('?' for _ in states[0]) + ')', states)
    return (perf_counter() - started) * 1000


def sqlite_rows(path: Path, sql: str) -> list[tuple]:
    conn = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        configure(conn)
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True,
                        help='Shared dataset manifest from backend_comparison.py --keep-artifacts')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--variant', choices=VARIANTS, default='minimal')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    memory = MemorySampler()
    with memory:
        report = build_typed(args.output, manifest, args.variant, memory)
    print(json.dumps({**report, 'memory': memory.report()}, indent=2))


if __name__ == '__main__':
    main()
