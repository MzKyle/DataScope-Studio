"""Phase C: fresh, sequential process comparisons on identical sample contracts."""
from __future__ import annotations

import argparse
import csv
import gc
import json
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
if __package__ in {None, ''}:
    sys.path.insert(0, str(REPO))

from benchmarks.backend_common import (QUERY_NAMES, assert_parity, canonical_result, checksum,
                                       csv_oracle, decode_typed, fields_for, typed_queries, write_json)
from benchmarks.benchmark_memory import MemorySampler
from benchmarks.benchmark_models import DatasetConfig, add_dataset_arguments, config_from_args
from benchmarks.benchmark_query import measure_query, query_calls, result_digest, validate_query
from benchmarks.benchmark_report import environment
from benchmarks.generate_dataset import generate_dataset

BACKENDS = ('legacy_sqlite_eav', 'sqlite_typed_none', 'sqlite_typed_time', 'sqlite_typed_minimal', 'sqlite_typed_covering',
            'duckdb_table', 'duckdb_parquet')


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    add_dataset_arguments(result, presets=True)
    result.add_argument('--baseline', type=Path, help='Reuse an immutable retained Phase A dataset/mapping; also verify the CSV oracle against production')
    result.add_argument('--resume-from', type=Path, help='Read retained Phase C inputs and reuse successful SQLite preparations; rerun every selected query in fresh workers')
    result.add_argument('--reuse-legacy-control', type=Path, help='Keep a previously validated EAV control only if SQL, data, oracle, policy and dependency versions are unchanged')
    result.add_argument('--output-dir', type=Path, default=REPO / 'benchmarks/results')
    result.add_argument('--query-runs', type=int, default=5)
    result.add_argument('--warmups', type=int, default=1)
    result.add_argument('--query-limit', type=int, default=1000)
    result.add_argument('--peer-rows', type=int, help='Default min(primary rows, 1000); baseline retains its actual peer')
    result.add_argument('--threads', type=int, default=4)
    result.add_argument('--memory-limit', default='1GB')
    result.add_argument('--keep-artifacts', action='store_true')
    result.add_argument('--backends', nargs='+', choices=BACKENDS, default=list(BACKENDS))
    result.add_argument('--production-control', action='store_true', help='Measure production custom-time filtering and execution ablations in another process')
    result.add_argument('--worker', choices=(*BACKENDS, 'legacy_analysis'), help=argparse.SUPPRESS)
    result.add_argument('--manifest', type=Path, help=argparse.SUPPRESS)
    result.add_argument('--worker-output', type=Path, help=argparse.SUPPRESS)
    return result


def mapping_fields(spec, code: int) -> list[dict]:
    fields = []
    for stream in spec.streams:
        if not stream.get('enabled', True):
            continue
        for key in stream['source_fields']:
            path = stream['entity_path'] + ('/' + key if stream['semantic_type'] == 'scalar_group' else '')
            kind = 'text' if stream['semantic_type'] == 'state' else 'integer' if key == 'error_code' else 'real'
            fields.append({'recording_key': code, 'key': key, 'entity_path': path,
                           'semantic_type': stream['semantic_type'], 'kind': kind})
    return fields


def prepare_inputs(args, work: Path) -> tuple[dict, dict | None]:
    from datascope_core.mapping import load_mapping_yaml
    historical = None
    manifest = {'recordings': [], 'fields': []}
    if args.resume_from:
        if args.baseline:
            raise ValueError('Choose either baseline or resume-from')
        prior = json.loads(args.resume_from.read_text(encoding='utf-8'))
        prior_work = args.resume_from.resolve().parent / '.work' / prior['run_id']
        manifest_report, manifest_report_path = prior, args.resume_from.resolve()
        manifest_work = prior_work
        while not (manifest_work / 'manifest.json').is_file():
            origin = manifest_report.get('resumed_from')
            if not origin:
                raise ValueError('Retained manifest no longer exists')
            manifest_report_path = Path(origin['json'])
            if checksum(manifest_report_path) != origin['sha256']:
                raise ValueError('Resume provenance report changed')
            manifest_report = json.loads(manifest_report_path.read_text(encoding='utf-8'))
            manifest_work = manifest_report_path.parent / '.work' / manifest_report['run_id']
        manifest = json.loads((manifest_work / 'manifest.json').read_text(encoding='utf-8'))
        if manifest['dataset'] != prior['dataset']:
            raise ValueError('Resume dataset changed along provenance chain')
        for recording in manifest['recordings']:
            if checksum(Path(recording['csv_path'])) != recording['checksum']:
                raise ValueError('Resume source checksum mismatch')
        manifest['reused_preparations'] = {}
        for backend, previous in prior['backends'].items():
            if previous['status'] != 'succeeded' or not (backend.startswith('sqlite_typed_') or backend == 'legacy_sqlite_eav'):
                continue
            artifact = prior_work / backend / 'samples.sqlite'
            provenance = previous['preparation'].get('reuse_provenance', {})
            if not artifact.is_file() and provenance:
                artifact = Path(provenance['path'])
            if artifact.is_file():
                manifest['reused_preparations'][backend] = {
                    'path': str(artifact), 'preparation': previous['preparation'],
                    'memory': previous.get('preparation_memory', previous['memory']),
                    'environment': provenance.get('environment', previous['environment']),
                    'original_run_id': provenance.get('original_run_id', prior['run_id']),
                    'original_started_at': provenance.get('original_started_at', prior['started_at'])}
        manifest['query_limit'] = args.query_limit
        manifest['resumed_from'] = {'json': str(args.resume_from.resolve()), 'sha256': checksum(args.resume_from),
                                   'note': 'preparation timings retain their original date; all query timings are measured again'}
        return manifest, None
    if args.baseline:
        from benchmarks.duckdb_poc import ReadOnlyWorkspace
        historical = json.loads(args.baseline.read_text(encoding='utf-8'))
        if historical['status'] != 'succeeded':
            raise ValueError('Baseline must have succeeded')
        config = DatasetConfig(**{key: historical['dataset'][key] for key in (
            'rows', 'frequency_hz', 'scalar_fields', 'state_fields', 'seed')})
        workspace = ReadOnlyWorkspace(historical['artifacts']['workspace'])
        conn = workspace._connect()
        try:
            for code, name in enumerate(('primary', 'peer'), 1):
                recording = dict(conn.execute('SELECT r.*, s.uri FROM recordings r JOIN sources s ON s.id = r.source_id WHERE r.run_name = ?', (name,)).fetchone())
                mapping_path = conn.execute('SELECT path FROM mappings WHERE source_id = ?', (recording['source_id'],)).fetchone()[0]
                path = Path(historical['artifacts']['dataset']) if code == 1 else Path(recording['uri'])
                source_hash = checksum(path)
                if code == 1 and source_hash != historical['source_checksum']:
                    raise ValueError('Baseline source checksum mismatch')
                rows = config.rows if code == 1 else historical['peer']['dataset']['rows']
                manifest['recordings'].append({'recording_key': code, 'recording_id': recording['id'],
                    'source_id': recording['source_id'], 'csv_path': str(path.resolve()), 'rows': rows,
                    'source_bytes': path.stat().st_size, 'checksum': source_hash})
                manifest['fields'].extend(mapping_fields(load_mapping_yaml(mapping_path), code))
            manifest['production_reference'] = {'workspace': str(workspace.root), 'project_id': recording['project_id'],
                                                 'baseline_json': str(args.baseline.resolve())}
        finally:
            conn.close()
        manifest['generation_ms'] = None
    else:
        from datascope_core.workspace import Workspace
        config = config_from_args(args)
        workspace = Workspace(work / 'schema_fixture')
        project = workspace.create_project('Phase C schema fixture')
        generation_ms = 0.
        peer_rows = min(config.rows, args.peer_rows if args.peer_rows is not None else 1000)
        if peer_rows < 2:
            raise ValueError('peer-rows must be >= 2')
        for code, rows in ((1, config.rows), (2, peer_rows)):
            path = work / f'input_{code}.csv'
            generated = generate_dataset(replace(config, rows=rows), path)
            generation_ms += generated['generation_ms']
            source = workspace.add_source(project['id'], str(path), storage_mode='reference',
                                          import_options={'csv': {'header_mode': 'header'}})
            inspection = workspace.inspect_source(source['id'])
            if inspection['source']['metadata']['rows'] != rows:
                raise AssertionError('Schema fixture row count mismatch')
            spec = workspace.suggest_mapping(source['id'], template_id='sensor_monitor')
            spec.timeline_unit = spec.effective_timeline_unit = 'relative_s'
            if not workspace.validate_mapping_spec(source['id'], spec)['valid']:
                raise AssertionError('Schema fixture mapping was invalid')
            manifest['recordings'].append({'recording_key': code, 'recording_id': spec.recording_id,
                'source_id': source['id'], 'csv_path': str(path.resolve()), 'rows': rows,
                'source_bytes': path.stat().st_size, 'checksum': checksum(path)})
            manifest['fields'].extend(mapping_fields(spec, code))
        manifest['generation_ms'] = generation_ms
    manifest['dataset'] = config.report()
    with Path(manifest['recordings'][0]['csv_path']).open(encoding='utf-8', newline='') as handle:
        manifest['csv_columns'] = next(csv.reader(handle))
    for code in (1, 2):
        fields = fields_for(manifest, code)
        if len(fields) != config.fields_per_sample or set(field['key'] for field in fields) != set(manifest['csv_columns']) - {'timestamp'}:
            raise AssertionError('Every CSV sample field must be mapped exactly once')
    manifest['logical_sample_count'] = sum(row['rows'] for row in manifest['recordings'])
    manifest['logical_query_rows'] = manifest['logical_sample_count'] * config.fields_per_sample
    manifest['source_bytes'] = sum(row['source_bytes'] for row in manifest['recordings'])
    manifest['query_limit'] = args.query_limit
    return manifest, historical


def worker(args) -> None:
    from benchmarks.comparison_backends import build_duck, build_legacy, legacy_queries
    from benchmarks.sqlite_typed_poc import build_typed, configure
    from benchmarks.duckdb_poc import decode_result
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    if args.worker == 'legacy_analysis':
        from benchmarks.legacy_query_analysis import analyze
        write_json(args.worker_output, analyze(args, manifest))
        return
    backend = args.worker
    work = args.manifest.parent / backend
    work.mkdir(exist_ok=False)
    for recording in manifest['recordings']:
        if checksum(Path(recording['csv_path'])) != recording['checksum']:
            raise ValueError('Worker input checksum changed')
    golden = json.loads((args.manifest.parent / 'golden.json').read_text(encoding='utf-8'))
    memory = MemorySampler()
    conn = None
    report = {'backend': backend, 'status': 'running', 'environment': environment(REPO),
              'source_checksums': [row['checksum'] for row in manifest['recordings']],
              'query_limit': manifest['query_limit'], 'logical_sample_count': manifest['logical_sample_count'],
              'logical_query_rows': manifest['logical_query_rows'], 'query_connection': 'persistent within this isolated backend worker'}
    try:
        with memory:
            print(f'{backend}: building {manifest["logical_sample_count"]:,} samples', flush=True)
            reused = manifest.get('reused_preparations', {}).get(backend)
            if reused:
                path = Path(reused['path'])
                if path.stat().st_size != reused['preparation']['storage_bytes']:
                    raise ValueError('Retained SQLite artifact size changed')
                wal = Path(str(path) + '-wal')
                if wal.exists() and wal.stat().st_size:
                    raise ValueError('Retained SQLite artifact has an uncheckpointed WAL')
                for key in ('packages', 'sqlite_version', 'python'):
                    if reused['environment'][key] != report['environment'][key]:
                        raise ValueError('Retained preparation environment differs: ' + key)
                conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
                configure(conn)
                records = [tuple(row) for row in conn.execute('SELECT * FROM recording_dictionary ORDER BY recording_key')]
                expected = [(row['recording_key'], row['recording_id'], row['source_id']) for row in manifest['recordings']]
                if records != expected:
                    raise ValueError('Retained recording dictionary differs')
                dictionary = [tuple(row) for row in conn.execute('SELECT value_id, value FROM state_dictionary ORDER BY value_id')]
                if dictionary != [(row['value_id'], row['value']) for row in manifest['state_dictionary']]:
                    raise ValueError('Retained state dictionary differs')
                dictionary = sorted(tuple(row) for row in conn.execute('SELECT * FROM field_dictionary'))
                if dictionary != sorted(tuple(row[key] for key in ('recording_key', 'key', 'entity_path', 'semantic_type', 'kind')) for row in manifest['fields']):
                    raise ValueError('Retained field dictionary differs')
                count = (conn.execute('SELECT count(*) FROM query_rows').fetchone()[0] if backend == 'legacy_sqlite_eav'
                         else sum(conn.execute('SELECT count(*) FROM ' + table).fetchone()[0] for table in ('numeric_samples', 'state_samples')))
                if count != reused['preparation']['physical_sample_rows']:
                    raise ValueError('Retained physical sample count differs')
                report['preparation'] = {**reused['preparation'], 'reuse_provenance': {
                    key: reused[key] for key in ('path', 'original_run_id', 'original_started_at', 'environment')}}
                report['preparation_memory'] = reused['memory']
                report['memory_measurement_scope'] = 'fresh query worker; retained preparation RSS is separate'
                print(f'  Reusing checked, read-only preparation from {reused["original_started_at"]}', flush=True)
            elif backend.startswith('sqlite_typed_'):
                path = work / 'samples.sqlite'
                report['preparation'] = build_typed(path, manifest, backend.removeprefix('sqlite_typed_'), memory)
                conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
                configure(conn)
            elif backend == 'legacy_sqlite_eav':
                path = work / 'samples.sqlite'
                report['preparation'] = build_legacy(path, manifest, memory)
                conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
                configure(conn)
            else:
                conn, report['preparation'] = build_duck(work, manifest, memory,
                    parquet=backend == 'duckdb_parquet', threads=args.threads, memory_limit=args.memory_limit)
            report['preparation']['storage_mb'] = report['preparation']['storage_bytes'] / 1_000_000
            report['preparation']['storage_amplification'] = report['preparation']['storage_bytes'] / manifest['source_bytes']
            sql = legacy_queries(manifest, manifest['query_limit']) if backend == 'legacy_sqlite_eav' else typed_queries(manifest, manifest['query_limit'])
            report['sql'] = sql
            if isinstance(conn, sqlite3.Connection):
                report['query_plans'] = {name: [row[-1] for row in conn.execute('EXPLAIN QUERY PLAN ' + statement)]
                                         for name, statement in sql.items()}
            else:
                report['query_plans'] = {name: conn.execute('EXPLAIN ' + statement).fetchone()[1] for name, statement in sql.items()}
            report['queries'] = {}
            config = DatasetConfig(**{key: manifest['dataset'][key] for key in (
                'rows', 'frequency_hz', 'scalar_fields', 'state_fields', 'seed')})
            ids = [row['recording_id'] for row in manifest['recordings']]
            for name in QUERY_NAMES:
                def call(name=name):
                    raw = conn.execute(sql[name]).fetchall()
                    result = decode_result(raw, name) if backend == 'legacy_sqlite_eav' else decode_typed(raw, name, manifest)
                    return canonical_result(result)

                def validate(actual, name=name):
                    assert_parity(actual, golden[name])
                    validate_query(actual, name, config, manifest['query_limit'], ids, manifest['recordings'][1]['rows'])

                report['queries'][name] = measure_query(call, validate, runs=args.query_runs,
                    warmups=args.warmups, memory=memory, name=f'{backend}/{name}', strict_digest=name != 'compare')
            conn.close()
            conn = None
        report['memory'] = memory.report()
        if reused:
            prepare_peaks = [stage['peak_rss_mb'] for name, stage in reused['memory']['stages'].items() if not name.startswith('query/')]
            report['memory']['preparation_peak_rss_mb'] = max(prepare_peaks, default=reused['memory']['peak_rss_mb'])
            report['memory']['workflow_peak_rss_mb'] = max(report['memory']['peak_rss_mb'], report['memory']['preparation_peak_rss_mb'])
        report['status'] = 'succeeded'
    except BaseException as exc:
        report.update(status='failed', error={'type': type(exc).__name__, 'message': str(exc)})
        report['memory'] = memory.report()
        write_json(args.worker_output, report)
        raise
    finally:
        if conn is not None:
            conn.close()
    write_json(args.worker_output, report)


def comparison_markdown(report: dict) -> str:
    lines = [f'# Phase C backend comparison: {report["run_id"]}', '',
             f'Status: {report["status"]}; samples: {report.get("logical_sample_count", "not prepared")}; '
             f'query runs: {report["settings"]["query_runs"]}; warm-ups: {report["settings"]["warmups"]}.', '',
             'All fresh workers use the same CSV checksums, query limit, full compare aggregates and canonical oracle.',
             'Legacy EAV uses SQL pushdown here; historical production Python filtering is a separate control.', '',
             '| Backend | Prepare s | Insert/load s | Index + analyze s | MB | Storage amp | Peak RSS MB |',
             '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for backend, data in report['backends'].items():
        if data['status'] != 'succeeded':
            continue
        prep = data['preparation']
        lines.append(f'| {backend} | {prep["total_preparation_ms"] / 1000:.3f} | '
                     f'{prep["load_ms"] / 1000:.3f} | {prep["index_ms"] / 1000:.3f} | '
                     f'{prep["storage_mb"]:.3f} | {prep["storage_amplification"]:.3f} | '
                     f'{data["memory"].get("workflow_peak_rss_mb", data["memory"]["peak_rss_mb"]):.3f} |')
    names = [name for name, data in report['backends'].items() if data['status'] == 'succeeded']
    lines += ['', '## Queries (P50 / P95 ms)', '', '| Query | ' + ' | '.join(names) + ' |',
              '| --- | ' + ' | '.join('---:' for _ in names) + ' |']
    for query in QUERY_NAMES:
        values = [report['backends'][name]['queries'][query] for name in names]
        lines.append('| ' + query + ' | ' + ' | '.join(f'{value["median_ms"]:.3f} / {value["p95_ms"]:.3f}' for value in values) + ' |')
    lines += ['', '## Method and limits', '',
              '- Sizes contain all numeric/state samples plus small dictionaries. Source CSV, RRD/RBL and production metadata are excluded for every backend.',
              '- Typed SQLite, DuckDB tables and Parquet use the same wide numeric and state-code layout; all fields are retained.',
              '- SQLite cache: 64 MiB; temp files allowed; WAL/FULL build durability. DuckDB settings and exact SQL/plans are in JSON.',
              '- Legacy schema/indexes match query_rows, but its isolated preparation builds indexes after ingestion. It is not a production Recording build timing.',
              '- SQLite index timing includes ANALYZE. DuckDB scans CSV separately for numeric and state data; Parquet is written directly without a second durable DuckDB database.',
              '- One backend per fresh process, sequential execution, persistent query connection, warm cache, fixed order. RSS includes that backend\'s preparation, validation and queries only.',
              '- Query timing includes execute/fetch/decode/canonicalization; parity checks and hashes are outside the timer. All raw samples are retained; P95 is nearest-rank.',
              '- State duration applies the same safe per-group limit + one look-ahead row before LEAD for all backends. Compare aggregates every sample in both recordings.',
              '- Floating tolerance: absolute 1e-8 / relative 1e-10; output order, keys, strings and integer values are preserved.',
              '- time_sync: known correctness gap in production MCAP file-wide ranges. Diagnostics backend parity is not implemented or used to claim a 5 s pass.',
              '- Synthetic smooth, non-null CSV scalar/state data only; no multi-writer, null/mixed/CV/ROS/lifecycle/packaging validation.',
              '- Resumed preparations retain their original build date/code/RSS; queries are all remeasured. Workflow RSS is the larger observed build/query peak, not a new joint-process measurement.',
              f'- Cleanup: {report.get("cleanup", "pending")}.', '']
    return '\n'.join(lines)


def run_comparison(args) -> Path:
    started = datetime.now(timezone.utc)
    run_id = f'benchmark_phase_c_{started:%Y%m%d_%H%M%S}_{uuid4().hex[:8]}'
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    work = output / '.work' / run_id
    work.mkdir(parents=True, exist_ok=False)
    path = output / (run_id + '.json')
    report = {'format_version': 1, 'run_id': run_id, 'started_at': started.isoformat(), 'status': 'running',
              'environment': environment(REPO), 'settings': {'query_runs': args.query_runs, 'warmups': args.warmups,
              'query_limit': args.query_limit, 'threads': args.threads, 'memory_limit': args.memory_limit}, 'backends': {}}
    try:
        setup_started = perf_counter()
        manifest, historical = prepare_inputs(args, work)
        print(f'Oracle: {manifest["logical_sample_count"]:,} samples / {manifest["logical_query_rows"]:,} logical values', flush=True)
        oracle_started = perf_counter()
        golden = csv_oracle(manifest, args.query_limit)
        report['oracle_ms'] = (perf_counter() - oracle_started) * 1000
        report['correctness_reference'] = {'type': 'bounded streaming independent CSV oracle',
                                           'production_queries_checked': []}
        if historical:
            from benchmarks.duckdb_poc import ReadOnlyWorkspace
            workspace = ReadOnlyWorkspace(manifest['production_reference']['workspace'])
            ids = [row['recording_id'] for row in manifest['recordings']]
            config = DatasetConfig(**{key: manifest['dataset'][key] for key in (
                'rows', 'frequency_hz', 'scalar_fields', 'state_fields', 'seed')})
            calls = query_calls(workspace, manifest['production_reference']['project_id'], ids, config, args.query_limit)
            for name in QUERY_NAMES:
                print(f'Production oracle parity: {name}', flush=True)
                stamp = perf_counter()
                actual = calls[name]()
                assert_parity(actual, golden[name])
                report['correctness_reference']['production_queries_checked'].append(name)
                print(f'  production parity passed in {perf_counter() - stamp:.2f} s', flush=True)
                del actual
            report['historical_production'] = {'baseline_json': str(args.baseline.resolve()),
                'build_scope': 'primary production Query Index; differs from sample-only Phase C preparation',
                'query_index_ms': historical['pipeline']['query_index_ms'],
                'storage_mb': historical['storage']['sqlite_size_mb'],
                'queries': {name: historical['queries'][name] for name in QUERY_NAMES}}
        report.update(dataset=manifest['dataset'], recordings=manifest['recordings'],
                      logical_sample_count=manifest['logical_sample_count'], logical_query_rows=manifest['logical_query_rows'],
                      source_size_mb=manifest['source_bytes'] / 1_000_000,
                      input_setup_ms=(perf_counter() - setup_started) * 1000,
                      golden_digests={name: result_digest(value) for name, value in golden.items()})
        if manifest.get('resumed_from'):
            report['resumed_from'] = manifest['resumed_from']
        write_json(work / 'manifest.json', manifest)
        write_json(work / 'golden.json', golden)
        del golden
        gc.collect()
        for backend in args.backends:
            if backend == 'legacy_sqlite_eav' and args.reuse_legacy_control:
                from benchmarks.comparison_backends import legacy_queries
                control = json.loads(args.reuse_legacy_control.read_text(encoding='utf-8'))
                previous = control['backends']['legacy_sqlite_eav']
                if previous['status'] != 'succeeded' or previous['source_checksums'] != [row['checksum'] for row in manifest['recordings']]:
                    raise ValueError('Legacy control data or status differs')
                if control['golden_digests'] != report['golden_digests'] or previous['sql'] != legacy_queries(manifest, args.query_limit):
                    raise ValueError('Legacy control oracle or SQL differs')
                for key in ('packages', 'python', 'sqlite_version'):
                    if previous['environment'][key] != report['environment'][key]:
                        raise ValueError('Legacy control runtime differs')
                if any(control['settings'][key] != report['settings'][key] for key in ('query_runs', 'warmups', 'query_limit')):
                    raise ValueError('Legacy control measurement policy differs')
                previous['query_control_reuse'] = {'json': str(args.reuse_legacy_control.resolve()),
                    'sha256': checksum(args.reuse_legacy_control), 'original_run_id': control['run_id'],
                    'original_started_at': control['started_at'],
                    'reason': 'EAV SQL, oracle, source hashes, measurement policy and runtime unchanged; only the shared typed SQL compiler was corrected'}
                report['backends'][backend] = previous
                write_json(path, report)
                print('Reusing verified unchanged Legacy SQL control measurements', flush=True)
                continue
            worker_output = work / (backend + '.json')
            command = [sys.executable, str(Path(__file__).resolve()), '--worker', backend,
                       '--manifest', str(work / 'manifest.json'), '--worker-output', str(worker_output),
                       '--query-runs', str(args.query_runs), '--warmups', str(args.warmups),
                       '--threads', str(args.threads), '--memory-limit', args.memory_limit]
            try:
                subprocess.run(command, check=True, cwd=REPO)
            except BaseException:
                if worker_output.exists():
                    report['backends'][backend] = json.loads(worker_output.read_text(encoding='utf-8'))
                raise
            report['backends'][backend] = json.loads(worker_output.read_text(encoding='utf-8'))
            write_json(path, report)
            path.with_suffix('.md').write_text(comparison_markdown(report), encoding='utf-8')
        if args.production_control:
            if 'legacy_sqlite_eav' not in report['backends']:
                raise ValueError('Production control requires the Legacy EAV backend')
            target = work / 'legacy_analysis.json'
            subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker', 'legacy_analysis',
                            '--manifest', str(work / 'manifest.json'), '--worker-output', str(target),
                            '--query-runs', str(args.query_runs), '--warmups', str(args.warmups)], check=True, cwd=REPO)
            report['legacy_analysis'] = json.loads(target.read_text(encoding='utf-8'))
        report['status'] = 'succeeded'
    except BaseException as exc:
        report.update(status='failed', error={'type': type(exc).__name__, 'message': str(exc)})
        raise
    finally:
        gc.collect()
        if work.resolve().parent != (output / '.work').resolve():
            raise RuntimeError('Phase C cleanup escaped its unique owned directory')
        if args.keep_artifacts:
            report['cleanup'] = {'status': 'retained', 'path': str(work)}
        else:
            try:
                shutil.rmtree(work)
                report['cleanup'] = {'status': 'removed_owned_run_directory'}
            except OSError as exc:
                report['cleanup'] = {'status': 'cleanup_failed', 'path': str(work), 'error': str(exc)}
        write_json(path, report)
        path.with_suffix('.md').write_text(comparison_markdown(report), encoding='utf-8')
    print(path, flush=True)
    return path


def main() -> None:
    cli = parser()
    args = cli.parse_args()
    if args.query_runs < 1 or args.warmups < 0 or args.query_limit < 4 or args.threads < 1:
        cli.error('query-runs >= 1, warmups >= 0, query-limit >= 4 and threads >= 1 required')
    if args.worker:
        if not args.manifest or not args.worker_output:
            cli.error('Worker requires manifest and output')
        worker(args)
    else:
        run_comparison(args)


if __name__ == '__main__':
    main()
