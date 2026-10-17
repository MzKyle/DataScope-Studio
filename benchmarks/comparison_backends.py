"""Phase C sample-only EAV and DuckDB builders; no production backend registration."""
from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from time import perf_counter

from benchmarks.backend_common import fields_for, identifier, literal, write_json
from benchmarks.benchmark_memory import MemorySampler
from benchmarks.sqlite_typed_poc import configure, create_dictionaries


def build_legacy(path: Path, manifest: dict, memory: MemorySampler) -> dict:
    if path.exists():
        raise FileExistsError(path)
    conn = sqlite3.connect(path)
    configure(conn, writing=True)
    started = perf_counter()
    insert_ms = 0.
    try:
        create_dictionaries(conn, manifest)
        conn.execute('CREATE TABLE query_rows (recording_id TEXT NOT NULL, source_id TEXT NOT NULL, time REAL, entity_path TEXT NOT NULL, semantic_type TEXT NOT NULL, key TEXT NOT NULL, value_json TEXT NOT NULL)')
        conn.commit()
        schema_ms = (perf_counter() - started) * 1000
        load_started = perf_counter()
        with memory.stage('insert'):
            conn.execute('BEGIN')
            for recording in manifest['recordings']:
                batch, count = [], 0
                fields = fields_for(manifest, recording['recording_key'])
                with Path(recording['csv_path']).open(encoding='utf-8', newline='') as handle:
                    for sample in csv.DictReader(handle):
                        time = float(sample['timestamp'])
                        for field in fields:
                            raw = sample[field['key']]
                            value = raw if field['kind'] == 'text' else int(raw) if field['kind'] == 'integer' else float(raw)
                            batch.append((recording['recording_id'], recording['source_id'], time,
                                          field['entity_path'], field['semantic_type'], field['key'],
                                          json.dumps(value, ensure_ascii=False)))
                            if len(batch) >= 10000:
                                tick = perf_counter()
                                conn.executemany('INSERT INTO query_rows VALUES (?, ?, ?, ?, ?, ?, ?)', batch)
                                insert_ms += (perf_counter() - tick) * 1000
                                batch = []
                        count += 1
                        if count % 100000 == 0:
                            print(f'  Legacy EAV inserted {count:,}/{recording["rows"]:,} samples', flush=True)
                if batch:
                    tick = perf_counter()
                    conn.executemany('INSERT INTO query_rows VALUES (?, ?, ?, ?, ?, ?, ?)', batch)
                    insert_ms += (perf_counter() - tick) * 1000
                if count != recording['rows']:
                    raise AssertionError('Legacy CSV row count mismatch')
            conn.commit()
        load_ms = (perf_counter() - load_started) * 1000
        indexes = [('idx_query_rows_recording', 'recording_id'), ('idx_query_rows_key', 'key'),
                   ('idx_query_rows_recording_semantic_key', 'recording_id, semantic_type, key, entity_path, time')]
        index_started = perf_counter()
        individual = {}
        with memory.stage('indexes'):
            for name, columns in indexes:
                print(f'  Legacy EAV creating {name}', flush=True)
                tick = perf_counter()
                conn.execute(f'CREATE INDEX {name} ON query_rows ({columns})')
                individual[name] = (perf_counter() - tick) * 1000
            conn.execute('ANALYZE')
            conn.commit()
        index_ms = (perf_counter() - index_started) * 1000
        checkpoint_started = perf_counter()
        with memory.stage('checkpoint'):
            if conn.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0] != 0:
                raise RuntimeError('Legacy checkpoint was busy')
        checkpoint_ms = (perf_counter() - checkpoint_started) * 1000
        total_ms = (perf_counter() - started) * 1000
        rows = conn.execute('SELECT count(*) FROM query_rows').fetchone()[0]
        if rows != manifest['logical_query_rows']:
            raise AssertionError('Legacy EAV physical row count mismatch')
    finally:
        conn.close()
    return {'schema_ms': schema_ms, 'load_ms': load_ms, 'sql_insert_ms': insert_ms,
            'index_ms': index_ms, 'individual_index_ms': individual, 'checkpoint_ms': checkpoint_ms,
            'total_preparation_ms': total_ms, 'physical_sample_rows': rows,
            'storage_bytes': path.stat().st_size, 'secondary_indexes': indexes,
            'storage_scope': 'EAV sample rows, all three existing indexes, same small dictionaries; excludes production workspace metadata',
            'layout': 'production query_rows schema; indexes built after CSV ingestion, not the production build pipeline',
            'sqlite_pragmas': {'journal_mode': 'wal', 'synchronous': 2, 'cache_size': -65536, 'temp_store': 1}}


def legacy_queries(manifest: dict, limit: int) -> dict[str, str]:
    from benchmarks.benchmark_models import DatasetConfig
    from benchmarks.duckdb_poc import sql_queries
    config = DatasetConfig(**{key: manifest['dataset'][key] for key in (
        'rows', 'frequency_hz', 'scalar_fields', 'state_fields', 'seed')})
    ids = [row['recording_id'] for row in manifest['recordings']]
    queries = sql_queries('query_rows', ids, config, limit)
    # Apply the same schema/dictionary pruning used by the typed column compiler.
    # This avoids deliberately handicapping EAV with lower(key) scans across every field.
    numeric = "semantic_type IN ('scalar', 'scalar_group')"
    key = 'scalar_000' if config.scalar_fields > 10 else 'temperature'
    matching = {
        'low_battery': "instr(lower(key || ' ' || entity_path), 'battery') > 0",
        'custom_scalar_key': f'instr(lower(key), {literal(key)}) > 0',
        'custom_numeric_threshold': "instr(lower(key), 'battery') > 0",
    }
    for name, dictionary_condition in matching.items():
        condition = (numeric + ' AND key IN (SELECT key FROM field_dictionary WHERE recording_key = 1 AND '
                     + dictionary_condition + ')')
        if name != 'custom_scalar_key':
            condition += ' AND CAST(value_json AS DOUBLE) < ' + ('.2' if name == 'low_battery' else '.1')
        queries[name] = (f'SELECT recording_id, time, entity_path, key, value_json FROM query_rows '
                         f'WHERE recording_id = {literal(ids[0])} AND {condition} '
                         f'ORDER BY recording_id, time, entity_path, key LIMIT {limit}')
    error_values = [json.dumps(row['value'], ensure_ascii=False) for row in manifest['state_dictionary']
                    if any(needle in row['value'].lower() for needle in ('error', 'warn', 'fault'))]
    queries['find_errors'] = (f'SELECT recording_id, time, entity_path, key, value_json FROM query_rows '
                             f'WHERE recording_id = {literal(ids[0])} AND semantic_type = \'state\' '
                             'AND key IN (SELECT key FROM field_dictionary WHERE recording_key = 1 AND kind = \'text\') '
                             'AND value_json IN (' + ','.join(literal(value) for value in error_values) + ') '
                             f'ORDER BY recording_id, time, entity_path, key LIMIT {limit}')
    states, aggregates = [], []
    for recording in manifest['recordings']:
        for field in fields_for(manifest, recording['recording_key']):
            condition = (f'recording_id = {literal(recording["recording_id"])} '
                         f'AND key = {literal(field["key"])} AND entity_path = {literal(field["entity_path"])} '
                         f'AND semantic_type = {literal(field["semantic_type"])}')
            if recording['recording_key'] == 1 and field['kind'] == 'text':
                states.append('SELECT * FROM (WITH candidates AS ('
                              f'SELECT time, value_json FROM query_rows WHERE {condition} '
                              f'ORDER BY time LIMIT {limit + 1}), durations AS ('
                              'SELECT time, value_json, coalesce(lead(time) OVER (ORDER BY time), time) - time duration FROM candidates) '
                              f'SELECT {literal(recording["recording_id"])} recording_id, time, '
                              f'{literal(field["entity_path"])} entity_path, {literal(field["key"])} key, '
                              f'value_json, duration FROM durations ORDER BY time LIMIT {limit})')
            if field['key'] in {'battery', 'temperature'}:
                aggregates.append('SELECT * FROM (WITH aggregated AS ('
                                  'SELECT count(*) count, min(CAST(value_json AS DOUBLE)) minimum, '
                                  'max(CAST(value_json AS DOUBLE)) maximum, avg(CAST(value_json AS DOUBLE)) mean, '
                                  f'max(time) last_time FROM query_rows WHERE {condition}) '
                                  f'SELECT {literal(recording["recording_id"])} recording_id, NULL time, '
                                  f'{literal(field["entity_path"])} entity_path, {literal(field["key"])} key, '
                                  'count, minimum, maximum, mean, '
                                  f'(SELECT CAST(value_json AS DOUBLE) FROM query_rows WHERE {condition} '
                                  'AND time = last_time LIMIT 1) latest FROM aggregated)')
    queries['state_duration'] = ('SELECT * FROM (' + ' UNION ALL '.join(states)
                                 + ') ORDER BY recording_id, entity_path, key, time LIMIT ' + str(limit))
    queries['compare'] = ('SELECT * FROM (' + ' UNION ALL '.join(aggregates)
                          + ') ORDER BY recording_id, entity_path, key LIMIT ' + str(limit))
    return queries


def build_duck(work: Path, manifest: dict, memory: MemorySampler, *, parquet: bool,
               threads: int, memory_limit: str = '1GB'):
    import duckdb
    path = work / 'samples.duckdb'
    started = perf_counter()
    duck = duckdb.connect(':memory:' if parquet else str(path))
    try:
        duck.execute(f'SET threads = {threads}')
        duck.execute(f'SET memory_limit = {literal(memory_limit)}')
        duck.execute(f'SET temp_directory = {literal(work / "spill")}')
        create_dictionaries(duck, manifest)
        fields = fields_for(manifest, 1)
        numeric = [field for field in fields if field['kind'] != 'text']
        states = [field for field in fields if field['kind'] == 'text']
        type_by_key = {'timestamp': 'DOUBLE', **{field['key']: 'BIGINT' if field['kind'] == 'integer' else 'DOUBLE'
                                               for field in numeric}, **{field['key']: 'VARCHAR' for field in states}}
        columns = {key: type_by_key[key] for key in manifest['csv_columns']}
        definition = 'recording_key INTEGER, time DOUBLE, ' + ','.join(
            identifier(field['key']) + (' BIGINT' if field['kind'] == 'integer' else ' DOUBLE') for field in numeric)
        if not parquet:
            duck.execute('CREATE TABLE numeric_samples (' + definition + ')')
            duck.execute('CREATE TABLE state_samples (recording_key INTEGER, time DOUBLE, '
                         + ','.join(identifier(field['key']) + ' INTEGER' for field in states) + ')')
        schema_ms = (perf_counter() - started) * 1000
        load_started = perf_counter()
        numeric_paths, state_paths = [], []
        with memory.stage('insert'):
            for recording in manifest['recordings']:
                source = 'read_csv(' + literal(recording['csv_path']) + ', columns = {' + ','.join(
                    literal(key) + ':' + literal(value) for key, value in columns.items()) + '}, header = true)'
                values = []
                for field in states:
                    column = identifier(field['key'])
                    values.append('CASE ' + column + ' ' + ' '.join(
                        f'WHEN {literal(row["value"])} THEN {row["value_id"]}' for row in manifest['state_dictionary'])
                                  + ' ELSE NULL END AS ' + column)
                selections = {
                    'numeric': f'SELECT {recording["recording_key"]} recording_key, "timestamp" AS time, '
                    + ','.join(identifier(field['key']) for field in numeric) + ' FROM ' + source,
                    'state': f'SELECT {recording["recording_key"]} recording_key, "timestamp" AS time, '
                    + ','.join(values) + ' FROM ' + source,
                }
                for kind, sql in selections.items():
                    if parquet:
                        target = work / f'{kind}_{recording["recording_key"]}.parquet'
                        duck.execute(f'COPY ({sql}) TO {literal(target)} (FORMAT PARQUET, COMPRESSION ZSTD)')
                        (numeric_paths if kind == 'numeric' else state_paths).append(target)
                    else:
                        duck.execute(f'INSERT INTO {kind}_samples ' + sql)
                print(f'  DuckDB prepared {recording["rows"]:,} samples', flush=True)
        load_ms = (perf_counter() - load_started) * 1000
        checkpoint_started = perf_counter()
        with memory.stage('checkpoint'):
            if parquet:
                for table, paths in (('numeric_samples', numeric_paths), ('state_samples', state_paths)):
                    duck.execute(f'CREATE VIEW {table} AS SELECT * FROM read_parquet(['
                                 + ','.join(literal(item) for item in paths) + '])')
                write_json(work / 'dataset.json', {
                    'recordings': [{key: row[key] for key in ('recording_key', 'recording_id', 'source_id', 'rows', 'checksum')}
                                   for row in manifest['recordings']],
                    'fields': manifest['fields'], 'state_dictionary': manifest['state_dictionary']})
            else:
                duck.execute('CHECKPOINT')
        checkpoint_ms = (perf_counter() - checkpoint_started) * 1000
        total_ms = (perf_counter() - started) * 1000
        count = duck.execute('SELECT count(*) FROM numeric_samples').fetchone()[0]
        state_count = duck.execute('SELECT count(*) FROM state_samples').fetchone()[0]
        expected = sum(row['rows'] for row in manifest['recordings'])
        if count != expected or state_count != expected:
            raise AssertionError('DuckDB physical sample count mismatch')
        if duck.execute('SELECT count(*) FROM state_samples WHERE ' + ' OR '.join(
                identifier(field['key']) + ' IS NULL' for field in states)).fetchone()[0]:
            raise AssertionError('State dictionary omitted an input value')
        size = sum(item.stat().st_size for item in [*numeric_paths, *state_paths, work / 'dataset.json']) if parquet else path.stat().st_size
        return duck, {'schema_ms': schema_ms, 'load_ms': load_ms, 'index_ms': 0.,
                      'checkpoint_ms': checkpoint_ms, 'total_preparation_ms': total_ms,
                      'physical_sample_rows': count + state_count, 'numeric_sample_rows': count,
                      'state_sample_rows': state_count, 'storage_bytes': size,
                      'storage_scope': 'numeric/state Parquet plus dictionary manifest' if parquet else 'numeric/state tables and the same dictionaries',
                      'layout': 'same wide numeric and dictionary-encoded state layout as Typed SQLite',
                      'settings': {'threads': threads, 'memory_limit': memory_limit, 'compression': 'zstd' if parquet else 'DuckDB default'},
                      'csv_scan_count_per_recording': 2,
                      'durable_files': [item.name for item in [*numeric_paths, *state_paths, work / 'dataset.json']] if parquet else ['samples.duckdb']}
    except BaseException:
        duck.close()
        raise
