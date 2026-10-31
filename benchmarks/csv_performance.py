"""Opt-in Phase E: paired CSV builds, exact full-field oracle and query gates.

Each worker is a fresh process. The control imports core from a git-archived
commit, so neither new dispatch nor the new batch time helper enters that path.
"""
from __future__ import annotations

import argparse
from array import array
from collections import Counter
from contextlib import ExitStack, closing
from dataclasses import asdict
from datetime import datetime, timezone
import gc
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time
from uuid import uuid4
import zipfile
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
if __package__ in {None, ''}:
    sys.path.insert(0, str(REPO))

import pandas as pd
import psutil
from datascope_core.models import MappingSpec
from datascope_core.workspace import Workspace
import datascope_core.workspace as workspace_module
from benchmarks.benchmark_memory import MemorySampler
from benchmarks.benchmark_models import DatasetConfig, PRESETS
from benchmarks.benchmark_query import measure_query, query_calls, validate_query, result_digest
from benchmarks.benchmark_report import environment
from benchmarks.custom_query_pushdown import ReadOnlyWorkspace, sha256, write_json
from benchmarks.generate_dataset import generate_dataset
from benchmarks.typed_storage import copy_metadata, storage

CONTROL = 'ab84733'
NAMES = ('find_errors', 'low_battery', 'state_duration', 'custom_scalar_key',
         'custom_time_range', 'custom_numeric_threshold', 'compare')


def timed(timings, name, function, *args, **kwargs):
    started = time.perf_counter()
    try:
        return function(*args, **kwargs)
    finally:
        timings[name] = timings.get(name, 0) + (time.perf_counter() - started) * 1000


class TimedAdapter:
    def __init__(self, adapter, timings):
        self.adapter, self.timings = adapter, timings

    def __getattr__(self, name):
        return getattr(self.adapter, name)

    def convert(self, *args, **kwargs):
        return timed(self.timings, 'rerun_ms', self.adapter.convert, *args, **kwargs)


def source_hashes():
    paths = list((REPO / 'packages/core/src').rglob('*.py')) + [Path(__file__).resolve()]
    return {str(p.relative_to(REPO)): sha256(p) for p in paths}


def snapshot(commit, destination):
    destination.mkdir(parents=True, exist_ok=False)
    archive = destination / 'source.zip'
    subprocess.run(['git', 'archive', '--format=zip', '--output', str(archive), commit],
                   cwd=REPO, check=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(destination)
    archive.unlink()


def numbers(path):
    with path.open('rb') as stream:
        while raw := stream.read(64 * 1024):
            values = array('d')
            values.frombytes(raw)
            yield from values


def csv_oracle(path, spec, recording_id, scratch):
    """Independent aggregation, sharing only the documented pandas CSV parser.

    Standard fixtures are monotonic, aligned, complete and mapped exactly once.
    No production index reader, aggregation, summary or SQL is used.
    """
    fields = {}
    for stream in spec['streams']:
        if not stream.get('enabled', True):
            continue
        for field in stream['source_fields']:
            assert field not in fields
            fields[field] = (stream['entity_path'] + ('/' + field if stream['semantic_type'] == 'scalar_group' else ''),
                             stream['semantic_type'])
    assert len(fields) == 32
    scratch.mkdir(parents=True, exist_ok=False)
    stats = {field: {'count': 0, 'min': None, 'max': None, 'latest': None, 'states': Counter()}
             for field in fields}
    paths = {field: scratch / f'{i}.f64' for i, field in enumerate(fields)}
    with ExitStack() as stack:
        files = {field: stack.enter_context(paths[field].open('wb')) for field in fields}
        reader = stack.enter_context(pd.read_csv(path, chunksize=50_000))
        for frame in reader:
            for field, (_, semantic) in fields.items():
                values = frame[field].dropna().tolist()
                if not values:
                    continue
                info = stats[field]
                info['latest'] = values[-1]
                if semantic == 'state' and not isinstance(values[0], (int, float)):
                    info['states'].update(map(str, values))
                else:
                    floats = array('d', map(float, values))
                    low, high = min(floats), max(floats)
                    if info['count'] == 0 or low < info['min']:
                        info['min'] = low
                    if info['count'] == 0 or high > info['max']:
                        info['max'] = high
                    info['count'] += len(values)
                    floats.tofile(files[field])
    rows = []
    for field, (entity, _) in fields.items():
        info = stats[field]
        if info['count']:
            value = {k: info[k] for k in ('count', 'min', 'max', 'latest')}
            value['mean'] = sum(numbers(paths[field])) / info['count']
        else:
            value = {'count': sum(info['states'].values()), 'states': dict(info['states']), 'latest': info['latest']}
        rows.append({'recording_id': recording_id, 'time': None, 'entity_path': entity, 'key': field, 'value': value})
    assert scratch.resolve().parent == Path(path).resolve().parent
    shutil.rmtree(scratch)
    return rows


def inputs(work, config):
    workspace = Workspace(work / 'setup')
    project = workspace.create_project('CSV performance')
    records, sources, recordings, oracle = [], [], [], []
    for i in range(2):
        path = work / f'input_{i}.csv'
        generate_dataset(DatasetConfig(**{**asdict(config), 'seed': config.seed + i}), path)
        source = workspace.add_source(project['id'], str(path), storage_mode='reference')
        workspace.inspect_source(source['id'])
        spec = workspace.suggest_mapping(source['id'])
        spec.timeline_unit = spec.effective_timeline_unit = 'relative_s'
        recording = f'recording_{i}'
        with closing(workspace._connect()) as conn, conn:
            conn.execute("INSERT INTO recordings (id,project_id,source_id,app_id,path,run_name,created_at) "
                         "VALUES (?,?,?,'benchmark','','benchmark','index-only')",
                         (recording, project['id'], source['id']))
            sources.append(dict(conn.execute('SELECT * FROM sources WHERE id=?', (source['id'],)).fetchone()))
            recordings.append(dict(conn.execute('SELECT * FROM recordings WHERE id=?', (recording,)).fetchone()))
        records.append({'recording_id': recording, 'source_id': source['id'], 'spec': asdict(spec),
                        'rows': config.rows, 'path': str(path), 'sha256': sha256(path)})
        oracle.extend(csv_oracle(path, asdict(spec), recording, work / f'oracle_{i}'))
    with closing(workspace._connect()) as conn, conn:
        project_row = dict(conn.execute('SELECT * FROM projects WHERE id=?', (project['id'],)).fetchone())
        profiles = [dict(r) for r in conn.execute('SELECT * FROM schema_profiles')]
    oracle.sort(key=lambda r: (r['recording_id'], r['entity_path'], r['key']))
    return {'project_id': project['id'], 'records': records, 'oracle': oracle,
            'profiles': profiles,
            'metadata': {'projects': [project_row], 'sources': sources, 'recordings': recordings}}


def retained_inputs(path, config):
    original = json.loads(path.read_text(encoding='utf-8'))
    assert original['config'] == asdict(config), 'Retained workload configuration changed'
    assert len(original['records']) == 2 and len(original['oracle']) == 64
    for record in original['records']:
        assert record['rows'] == config.rows
        assert sha256(Path(record['path'])) == record['sha256'], 'Retained CSV changed'
    return {key: original[key] for key in ('project_id', 'records', 'oracle', 'profiles', 'metadata')}


def worker(args):
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    config = DatasetConfig(**manifest['config'])
    target = Path(manifest['work']) / args.worker
    result = {'status': 'running', 'builds': [], 'environment': environment(REPO)}
    result['imported_core'] = {name: {'path': sys.modules['datascope_core.' + name].__file__,
        'sha256': sha256(Path(sys.modules['datascope_core.' + name].__file__))}
        for name in ('workspace', 'query_typed', 'time_utils')}
    if args.worker in {'control', 'diagnostic_control'}:
        assert all(Path(item['path']).is_relative_to(Path(manifest['work']) / 'control_source')
                   for item in result['imported_core'].values()), 'Control imported non-frozen production code'
    memory = MemorySampler()
    with memory:
        if args.worker == 'diagnostic_control':
            workspace = ReadOnlyWorkspace(Path(manifest['work']) / 'index' / str(manifest['build_runs'] - 1))
            value = workspace.run_diagnostics(manifest['project_id'], [manifest['records'][0]['recording_id']])
            value.pop('created_at', None)
            result.update(status='succeeded', report_sha256=result_digest(value))
            write_json(args.worker_output, result)
            return
        if args.worker == 'pressure':
            workspace = Workspace(target)
            project = workspace.create_project('CSV pressure')
            source = workspace.add_source(project['id'], manifest['source'], storage_mode='reference')
            workspace.inspect_source(source['id'])
            spec = workspace.suggest_mapping(source['id'])
            spec.timeline_unit = spec.effective_timeline_unit = 'relative_s'
            mapping = workspace.save_mapping(project['id'], source['id'], spec, confirmed=True)
            started = time.perf_counter()
            built = workspace.build_recording(project['id'], source['id'], mapping['id'], query_storage='auto')
            result['workspace_ms'] = (time.perf_counter() - started) * 1000
            result['result'] = built
            write_json(args.worker_output, result)
            verified = subprocess.run([sys.executable, '-m', 'rerun_cli', 'rrd', 'verify', built['recording_path']],
                                      capture_output=True, text=True)
            result['rrd_verify'] = {'returncode': verified.returncode, 'stderr': verified.stderr}
            assert verified.returncode == 0
            result.update(status='succeeded', memory=memory.report())
            write_json(args.worker_output, result)
            return
        for trial in range(manifest['build_runs']):
            root = target / str(trial)
            workspace = Workspace(root)
            if args.worker in {'control', 'index'}:
                copy_metadata(workspace, manifest)
                with closing(workspace._connect()) as conn, conn:
                    for profile in manifest['profiles']:
                        conn.execute('INSERT INTO schema_profiles (' + ','.join(profile) + ') VALUES ('
                            + ','.join('?' for _ in profile) + ')', list(profile.values()))
                timings = []
                for rec in manifest['records'][:1] if args.worker == 'control' else manifest['records']:
                    started = time.perf_counter()
                    last_progress = started
                    def progress():
                        nonlocal last_progress
                        now = time.perf_counter()
                        if now - last_progress >= 15:
                            last_progress = now
                            print(f'{args.worker} trial {trial} {rec["recording_id"]}: preparing {now-started:.0f}s', flush=True)
                    workspace._index_recording(rec['recording_id'], workspace.get_source(rec['source_id']),
                        MappingSpec(**rec['spec']), query_storage='typed_sqlite',
                        cancel_check=progress,
                        **({'cache_dir': root / 'cache'} if args.worker == 'index' else {}))
                    # Include transaction commit and checkpoint in prepare timing.
                    with closing(workspace._connect()) as conn:
                        assert conn.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0] == 0
                    timings.append((time.perf_counter() - started) * 1000)
                    print(f'{args.worker} trial {trial} {rec["recording_id"]}: {timings[-1]:.1f} ms', flush=True)
                result['builds'].append({'index_ms': timings})
            else:
                project = workspace.create_project('Full CSV')
                timings = []
                phases = []
                for i, rec in enumerate(manifest['records']):
                    detail = {}
                    source = timed(detail, 'import_ms', workspace.add_source, project['id'], rec['path'], storage_mode='reference')
                    timed(detail, 'inspect_ms', workspace.inspect_source, source['id'])
                    spec = MappingSpec(**{**rec['spec'], 'source_id': source['id']})
                    mapping = timed(detail, 'mapping_ms', workspace.save_mapping,
                                    project['id'], source['id'], spec, confirmed=True)
                    started = time.perf_counter()
                    adapter_factory = workspace._adapter_for_path
                    with ExitStack() as stack:
                        original_check = workspace._check_job_cancelled
                        def counted_check(*args):
                            detail['cancellation_db_checks'] = detail.get('cancellation_db_checks', 0) + 1
                            return original_check(*args)
                        stack.enter_context(patch.object(workspace, '_check_job_cancelled', counted_check))
                        stack.enter_context(patch.object(workspace, '_adapter_for_path',
                            lambda *a, **k: TimedAdapter(adapter_factory(*a, **k), detail)))
                        for function, name in (('save_blueprint', 'blueprint_ms'),
                            ('validate_artifacts', 'validation_ms'), ('cleanup_recording_streams', 'cleanup_ms')):
                            original = getattr(workspace_module, function)
                            stack.enter_context(patch.object(workspace_module, function,
                                lambda *a, _function=original, _name=name, **k: timed(detail, _name, _function, *a, **k)))
                        built = workspace.build_recording(project['id'], source['id'], mapping['id'],
                            output_name=f'run_{i}', query_storage='auto')
                    detail['query_index'] = built['query_index']
                    phases.append(detail)
                    timings.append((time.perf_counter() - started) * 1000)
                    assert Path(built['recording_path']).is_file() and Path(built['blueprint_path']).is_file()
                    print(f'full trial {trial} recording {i}: {timings[-1]:.1f} ms', flush=True)
                result['builds'].append({'workspace_ms': timings, 'phases': phases})
            write_json(args.worker_output, result)
            if args.worker == 'index' and trial == manifest['build_runs'] - 1:
                result['storage'] = storage(workspace)
                result['catalog'] = str(root)
                workspace = ReadOnlyWorkspace(root)
                project, ids = manifest['project_id'], [r['recording_id'] for r in manifest['records']]
                calls = query_calls(workspace, project, ids, config, 1000)
                result['queries'] = {}
                for name in NAMES:
                    result['queries'][name] = measure_query(calls[name],
                        lambda value, name=name: validate_query(value, name, config, 1000, ids, config.rows),
                        runs=manifest['query_runs'], warmups=1, memory=memory, name=name)
                    write_json(args.worker_output, result)
                def exact(value):
                    assert value['rows'] == manifest['oracle'], 'Independent full-field CSV oracle mismatch'
                result['queries']['compare_all'] = measure_query(lambda: workspace.compare(project, ids), exact,
                    runs=manifest['query_runs'], warmups=1, memory=memory, name='compare_all')
                def diagnostic_call():
                    value = workspace.run_diagnostics(project, ids[:1])
                    value.pop('created_at', None)
                    return value
                result['diagnostics'] = measure_query(diagnostic_call,
                    lambda value: None, runs=manifest['query_runs'], warmups=1, memory=memory,
                    name='diagnostics')
                write_json(args.worker_output, result)
                from benchmarks.query_backends import execution
                result['execution'] = {name: execution(workspace, calls[name]) for name in NAMES}
            # Retain only the final new catalog for read-only audit; never delete inputs.
            if args.worker != 'index' or trial != manifest['build_runs'] - 1:
                gc.collect()
                assert root.resolve().parent == target.resolve()
                assert root.resolve().is_relative_to(Path(manifest['work']).resolve())
                shutil.rmtree(root)
    result.update(status='succeeded', memory=memory.report())
    write_json(args.worker_output, result)


def run_process(argv, env, target, *, seconds=7200, rss_limit=2 * 1024**3):
    process = subprocess.Popen(argv, env=env)
    started, peak = time.monotonic(), 0
    temporary_peak = 0
    owned = target.parent / target.stem
    reason = None
    while process.poll() is None:
        try:
            tree = [psutil.Process(process.pid), *psutil.Process(process.pid).children(recursive=True)]
            peak = max(peak, sum(p.memory_info().rss for p in tree if p.is_running()))
            if peak > rss_limit or time.monotonic() - started > seconds:
                reason = 'RSS limit' if peak > rss_limit else 'time limit'
                for child in reversed(tree):
                    child.kill()
                break
        except psutil.NoSuchProcess:
            pass
        temporary = 0
        for directory, _, names in os.walk(owned):
            for name in names:
                if name.endswith(('.f64', '.sqlite-wal', '.sqlite-journal')) or name.startswith('tabular-sort.sqlite'):
                    try:
                        temporary += (Path(directory) / name).stat().st_size
                    except FileNotFoundError:
                        pass
        temporary_peak = max(temporary_peak, temporary)
        time.sleep(.1)
    process.wait()
    result = json.loads(target.read_text(encoding='utf-8')) if target.exists() else {}
    result['process_tree_peak_rss_bytes'] = peak
    result['temporary_usage'] = {'peak_bytes_sampled': temporary_peak, 'interval_ms': 100,
        'scope': 'owned float spools, SQLite WAL/journals and CSV sort cache; excludes source CSV, main catalog, RRD/RBL and unobservable SQLite native temp I/O'}
    if reason or process.returncode:
        result.update(status='incomplete' if reason else 'failed', error=reason or f'exit {process.returncode}')
    return result


def run(args):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S') + '_' + uuid4().hex[:8]
    work = args.output_dir.resolve() / '.work' / ('csv_performance_' + stamp)
    work.mkdir(parents=True, exist_ok=False)
    output = args.output_dir / ('csv_performance_' + stamp + '.json')
    report = {'status': 'running', 'preset': args.preset, 'work': str(work),
              'environment': environment(REPO), 'source_files_sha256': source_hashes(), 'workers': {},
              'development': bool(args.rows), 'standard_protocol': args.build_runs == 3 and args.query_runs == 5 and not args.rows}
    write_json(output, report)
    try:
        config = DatasetConfig(rows=args.rows or PRESETS[args.preset])
        source_inputs = retained_inputs(args.input_manifest, config) if args.input_manifest else inputs(work, config)
        if args.input_manifest:
            report['input_provenance'] = {'manifest': str(args.input_manifest.resolve()),
                'sha256': sha256(args.input_manifest),
                'scope': 'complete retained standard inputs and independent oracle; CSVs rehashed; all timing workers run afresh'}
        manifest = {**source_inputs, 'config': asdict(config), 'work': str(work),
                    'build_runs': args.build_runs, 'query_runs': args.query_runs}
        write_json(work / 'manifest.json', manifest)
        report['input'] = manifest
        frozen = work / 'control_source'
        snapshot(CONTROL, frozen)
        report['control_commit'] = subprocess.check_output(['git', 'rev-parse', CONTROL], cwd=REPO, text=True).strip()
        for name in ('control', 'index', 'diagnostic_control', 'full'):
            target = work / (name + '.json')
            env = dict(os.environ)
            if name in {'control', 'diagnostic_control'}:
                env['PYTHONPATH'] = os.pathsep.join(str(frozen / p) for p in
                    ('packages/core/src', 'packages/cli/src', 'services/api/src'))
            argv = [sys.executable, str(Path(__file__).resolve()), '--worker', name,
                    '--manifest', str(work / 'manifest.json'), '--worker-output', str(target)]
            report['workers'][name] = run_process(argv, env, target)
            write_json(output, report)
            if report['workers'][name]['status'] != 'succeeded':
                report['status'] = report['workers'][name]['status']
                return 2
        old, new, full = (report['workers'][n] for n in ('control', 'index', 'full'))
        old_ms = statistics.median(b['index_ms'][0] for b in old['builds'])
        new_ms = statistics.median(b['index_ms'][0] for b in new['builds'])
        full_ms = statistics.median(t for b in full['builds'] for t in b['workspace_ms'])
        source_bytes = sum(Path(r['path']).stat().st_size for r in manifest['records'])
        gates = {'queries_p95_le_1s': all(q['p95_ms'] <= 1000 for q in new['queries'].values()),
            'diagnostics_exact_parity': new['diagnostics']['result_sha256'] == report['workers']['diagnostic_control']['report_sha256'],
            'diagnostics_p95': new['diagnostics']['p95_ms'] <= (60_000 if args.preset in {'medium','large'} else 5000),
            'index_le_180s': new_ms <= 180_000,
            'medium_index_speedup_ge_3': old_ms / new_ms >= 3 if args.preset == 'medium' else None,
            'workspace_le_300s': full_ms <= 300_000,
            'storage_le_2x': new['storage']['database_bytes'] <= source_bytes * 2,
            'build_rss_le_1gib': all(report['workers'][n]['process_tree_peak_rss_bytes'] <= 1024**3
                                      for n in ('index', 'full')),
            'query_rss_le_512mib': max(s['peak_rss_mb'] for s in new['memory']['stages'].values()) * 1_000_000 <= 512 * 1024**2,
            'all_32_fields': new['storage']['typed_logical_rows'] == config.rows * 64,
            'no_eav_fallback': new['storage']['eav_rows'] == 0}
        report.update(status='succeeded' if all(v is not False for v in gates.values()) else 'gates_failed', acceptance=gates,
                      index_speedup=old_ms / new_ms, index_median_ms=new_ms, workspace_median_ms=full_ms)
        report['comparison_scope'] = 'Three paired primary index builds; both equal-sized sources built by new writer/full Workspace in every trial'
        assert report['source_files_sha256'] == source_hashes(), 'Production code changed during measurement'
        assert all(sha256(Path(r['path'])) == r['sha256'] for r in manifest['records'])
        if args.input_manifest:
            assert sha256(args.input_manifest) == report['input_provenance']['sha256']
        return 0 if report['status'] == 'succeeded' else 2
    except BaseException as error:
        report.update(status='failed', error=str(error))
        raise
    finally:
        write_json(output, report)
        print('Report: ' + str(output), flush=True)


def pressure(args):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S') + '_' + uuid4().hex[:8]
    work = args.output_dir.resolve() / '.work' / ('csv_pressure_' + stamp)
    work.mkdir(parents=True, exist_ok=False)
    output = args.output_dir / ('csv_performance_large_' + stamp + '.json')
    report = {'status': 'running', 'preset': 'large', 'standard_protocol': False,
              'scope': 'single new full Workspace; integrity/resource pressure only',
              'environment': environment(REPO), 'source_files_sha256': source_hashes(), 'work': str(work),
              'development': bool(args.rows)}
    write_json(output, report)
    try:
        config = DatasetConfig(rows=args.rows or PRESETS['large'])
        source = work / 'large.csv'
        generate_dataset(config, source)
        report['input'] = {'source': str(source), 'bytes': source.stat().st_size, 'sha256': sha256(source),
                           'rows': config.rows, 'fields': 32}
        manifest = {**report['input'], 'config': asdict(config), 'work': str(work)}
        write_json(work / 'manifest.json', manifest)
        target = work / 'pressure.json'
        value = run_process([sys.executable, str(Path(__file__).resolve()), '--worker', 'pressure',
            '--manifest', str(work / 'manifest.json'), '--worker-output', str(target)], dict(os.environ),
            target, seconds=1800, rss_limit=2 * 1024**3)
        report.update(status=value['status'], worker=value, resource_limits={'seconds': 1800, 'rss_bytes': 2 * 1024**3})
        assert report['source_files_sha256'] == source_hashes()
        assert report['input']['sha256'] == sha256(source)
        return 0 if report['status'] == 'succeeded' else 2
    except BaseException as error:
        report.update(status='failed', error=str(error))
        raise
    finally:
        write_json(output, report)
        print('Pressure report: ' + str(output), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preset', choices=tuple(PRESETS), default='smoke')
    parser.add_argument('--rows', type=int, help='Development only; standard preset gates require unchanged sizes')
    parser.add_argument('--build-runs', type=int, default=3)
    parser.add_argument('--query-runs', type=int, default=5)
    parser.add_argument('--output-dir', type=Path, default=REPO / 'benchmarks/results')
    parser.add_argument('--input-manifest', type=Path, help='Reuse complete, checksum-verified inputs and CSV oracle; rerun every timing worker')
    parser.add_argument('--worker', choices=('control','index','diagnostic_control','full','pressure'), help=argparse.SUPPRESS)
    parser.add_argument('--manifest', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--worker-output', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.build_runs < 1 or args.query_runs < 1 or (args.rows is not None and args.rows < 2):
        parser.error('positive runs and at least two rows are required')
    if args.worker:
        worker(args)
    elif args.preset == 'large':
        raise SystemExit(pressure(args))
    else:
        raise SystemExit(run(args))


if __name__ == '__main__':
    main()
