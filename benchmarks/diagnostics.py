"""C3 full-report comparison; frozen C2c, bounded production and grouped oracle."""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(REPO))

import pandas as pd
import psutil
from datascope_core.models import MappingSpec
from datascope_core.diagnostic_stats import DiagnosticStats
from datascope_core.query import _stream_query_row
from datascope_core.query_backend import register_backend_functions, TypedSQLiteBackend, LegacyQueryBackend
from datascope_core.query_sql import CustomQueryPlan, register_custom_query_functions
from datascope_core.workspace import Workspace
from benchmarks import c2c_robot_diagnostics as frozen
from benchmarks.benchmark_memory import MemorySampler
from benchmarks.benchmark_models import DatasetConfig, PRESETS
from benchmarks.benchmark_query import measure_query, result_digest
from benchmarks.benchmark_report import environment
from benchmarks.c2c_diagnostics_reference import WorkspaceDiagnosticsMixin as Reference
from benchmarks.custom_query_pushdown import ReadOnlyWorkspace, describe_input, sha256, write_json
from benchmarks.typed_storage import copy_metadata, fresh_inputs, retained_inputs, storage

CODE = tuple('packages/core/src/datascope_core/' + name + '.py' for name in
             ('diagnostic_stats', 'diagnostic_reader', 'workspace_diagnostics', 'robot_diagnostics',
              'query_backend', 'query_typed')) + ('benchmarks/diagnostics.py',
              'benchmarks/c2c_diagnostics_reference.py', 'benchmarks/c2c_robot_diagnostics.py')


class FrozenWorkspace(Reference, ReadOnlyWorkspace):
    pass


def prepare(manifest):
    workspace = Workspace(Path(manifest['work']) / 'typed')
    copy_metadata(workspace, manifest)
    started, last = time.perf_counter(), time.perf_counter()
    def progress():
        nonlocal last
        if time.perf_counter() - last > 15:
            last = time.perf_counter()
            print(f'preparing typed catalog: {last-started:.0f}s', flush=True)
    for item in manifest['records']:
        source = workspace.get_source(item['source_id'])
        workspace.get_schema_profile(source['id'])
        workspace._index_recording(item['recording_id'], source, MappingSpec(**item['spec']),
                                  query_storage='typed_sqlite', cancel_check=progress)
    return {'elapsed_ms': (time.perf_counter()-started)*1000, 'storage': storage(workspace)}


def instrument(workspace, call):
    workspace._diagnostic_read_stats = {}
    workspace.traces = []
    extra = {'json_loads_calls': 0, 'backend_typed_logical_rows': 0, 'backend_eav_rows': 0}
    original_json = json.loads
    original_typed, original_legacy = TypedSQLiteBackend.iter_rows, LegacyQueryBackend.iter_rows
    original_time, original_data = DiagnosticStats.time_findings, DiagnosticStats.data_findings
    group_hash = hashlib.sha256()
    def grouped(function):
        def wrapped(*args):
            for finding in function(*args):
                group_hash.update(json.dumps(finding, sort_keys=True, ensure_ascii=False).encode('utf-8'))
                yield finding
        return wrapped
    def decode(*args, **kwargs):
        extra['json_loads_calls'] += 1
        return original_json(*args, **kwargs)
    def typed(*args, **kwargs):
        for row in original_typed(*args, **kwargs):
            extra['backend_typed_logical_rows'] += 1
            yield row
    def legacy(*args, **kwargs):
        for row in original_legacy(*args, **kwargs):
            extra['backend_eav_rows'] += 1
            yield row
    try:
        with patch.object(json, 'loads', decode), patch.object(TypedSQLiteBackend, 'iter_rows', typed), \
             patch.object(LegacyQueryBackend, 'iter_rows', legacy), \
             patch.object(DiagnosticStats, 'time_findings', grouped(original_time)), \
             patch.object(DiagnosticStats, 'data_findings', grouped(original_data)):
            call()
        counts = {**workspace._diagnostic_read_stats, **extra,
                  'exact_group_findings_sha256': group_hash.hexdigest()}
        statements = list(dict.fromkeys(s for s in workspace.traces if s.lstrip().upper().startswith('SELECT')))
    finally:
        workspace.traces = None
        del workspace._diagnostic_read_stats
    conn = workspace._connect()
    try:
        register_backend_functions(conn)
        register_custom_query_functions(conn, CustomQueryPlan(needs_unicode_lower=True))
        conn.create_function('datascope_diag_number', 2, lambda v, k: v)
        conn.create_function('datascope_diag_pack', -1, lambda *v: None)
        plans = [{'sql': sql, 'explain': [list(r) for r in conn.execute('EXPLAIN QUERY PLAN '+sql)]}
                 for sql in statements]
    finally:
        conn.close()
    return {'counts': counts, 'statements': plans, 'sqlite_rows_examined': None,
            'scope': 'separate untimed pass; cursor rows and logical values, not SQLite scan/page counts; temporary bytes are cumulative writes'}


def grouped_oracle(workspace, manifest, facts=None):
    """Original rule functions, one raw CSV group at a time; never a full EAV list.

    This oracle deliberately supports only the standard complete-field generator.
    Its finite, ordered, disjoint mappings are asserted rather than generalized.
    """
    record = manifest['records'][0]
    source = workspace.get_source(record['source_id'])
    groups = []
    for mapping in record['spec']['streams']:
        if mapping['semantic_type'] == 'scalar_group':
            groups.extend((mapping['entity_path']+'/'+field, field, 'scalar_group') for field in mapping['source_fields'])
        else:
            assert len(mapping['source_fields']) == 1
            groups.append((mapping['entity_path'], mapping['source_fields'][0], mapping['semantic_type']))
    assert len(groups) == manifest['config']['scalar_fields'] + 2
    thresholds = frozen.normalize_thresholds(None)
    temporal, numeric, states = [], [], []
    for entity, field, semantic in sorted(groups):
        def rows():
            for frame in pd.read_csv(source['uri'], usecols=['timestamp', field], chunksize=50_000):
                for timestamp, value in zip(frame['timestamp'], frame[field]):
                    yield {'recording_id': record['recording_id'], 'source_id': record['source_id'],
                           'entity_path': entity, 'key': field, 'semantic_type': semantic,
                           'time': float(timestamp), 'value': value}
        temporal.extend(frozen._time_series_quality_findings([], rows(), thresholds))
        target = states if semantic == 'state' else numeric
        target.extend(frozen._data_quality_findings([], rows(), thresholds))
        print('oracle group: '+field, flush=True)
    if facts is not None:
        digest = hashlib.sha256()
        for finding in temporal + numeric + states:
            digest.update(json.dumps(finding, sort_keys=True, ensure_ascii=False).encode('utf-8'))
        facts.update(exact_group_findings_sha256=digest.hexdigest(), group_count=len(groups),
                     time_findings=len(temporal), data_findings=len(numeric)+len(states))

    class CountOnly:
        def __len__(self):
            return record['rows'] * len(groups)
    original_time, original_data = frozen._time_series_quality_findings, frozen._data_quality_findings
    reference = FrozenWorkspace(workspace.root)
    original_rows = reference._query_rows
    def selected_rows(project_id, **kwargs):
        if kwargs.get('semantic_types'):
            return CountOnly()
        template = kwargs.get('template_id')
        if template == 'topic_summary':
            return original_rows(project_id, **kwargs)
        params = {'threshold': thresholds['battery_low' if template == 'low_battery' else 'detection_confidence']}
        found = []
        iterator = reference._iter_query_rows(project_id, **kwargs)
        try:
            for row in iterator:
                if _stream_query_row(row, template, params) is not None:
                    found.append(row)
                    if len(found) == manifest['limit']:
                        break
        finally:
            iterator.close()
        return found
    reference._query_rows = selected_rows
    with patch.object(frozen, '_time_series_quality_findings',
                      lambda profiles, rows, t: original_time(profiles, [], t) + temporal), \
         patch.object(frozen, '_data_quality_findings',
                      lambda profiles, rows, t: original_data(profiles, [], t) + numeric + states):
        return reference.run_diagnostics(manifest['project_id'], [record['recording_id']], limit=manifest['limit'])


def worker(args):
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    memory = MemorySampler()
    with memory:
        if args.worker == 'prepare':
            result = prepare(manifest)
        else:
            is_eav = args.worker.startswith('eav')
            root = manifest['control']['workspace'] if is_eav else Path(manifest['work'])/'typed'
            workspace = (FrozenWorkspace if args.worker.endswith('old') else ReadOnlyWorkspace)(root)
            workspace._diagnostic_temp_root = Path(manifest['work'])/'temporary'
            if args.worker == 'oracle':
                started = time.perf_counter()
                facts = {}
                value = grouped_oracle(workspace, manifest, facts)
                result = {'result_sha256': result_digest(value), 'report': value,
                          'elapsed_ms': (time.perf_counter()-started)*1000, **facts}
            else:
                call = lambda: workspace.run_diagnostics(manifest['project_id'],
                    [manifest['records'][0]['recording_id']], limit=manifest['limit'])
                latest = []
                def validate(value):
                    latest[:] = [value]
                result = measure_query(call, validate, runs=manifest['runs'],
                    warmups=manifest['warmups'], memory=memory, name=args.worker)
                result['report'] = latest[0]
                result['execution'] = instrument(workspace, call)
    result['memory'] = memory.report()
    write_json(args.worker_output, result)


def run(args):
    run_id = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid4().hex[:8]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    work = args.output_dir.resolve()/'.work'/('diagnostics_'+run_id)
    work.mkdir(parents=True, exist_ok=False)
    write_json(work/'owner.json', {'run_id': run_id})
    output = args.output_dir/('diagnostics_'+run_id+'.json')
    report = {'format_version': 1, 'run_id': run_id, 'preset': args.preset, 'status': 'running',
              'environment': environment(REPO), 'backends': {},
              'source_files_sha256': {p: sha256(REPO/p) for p in CODE}}
    try:
        config = DatasetConfig(rows=args.rows or PRESETS[args.preset])
        if args.rows:
            inputs = fresh_inputs(work, config)
        elif args.preset == 'medium':
            inputs = fresh_inputs(work, config, json.loads(args.phase_c_input.read_text(encoding='utf-8')))
        else:
            inputs = retained_inputs(args.preset, REPO/'benchmarks/results/baselines/2026-10-17-phase-c2a'/(args.preset+'.json'))
        manifest = {**inputs, 'work': str(work), 'config': asdict(config), 'limit': 1000,
                    'runs': args.runs, 'warmups': args.warmups}
        write_json(work/'manifest.json', manifest)
        report['input'] = {**inputs, 'config': asdict(config), 'sources': [
            {'path': s['uri'], 'sha256': sha256(Path(s['uri'])), 'bytes': Path(s['uri']).stat().st_size}
            for s in inputs['metadata']['sources']]}
        paths = ['prepare']
        if args.preset != 'medium' or args.rows:
            paths += (['eav_old', 'eav_new'] if inputs.get('control') else []) + ['typed_old']
        paths += ['typed_new']
        if args.preset == 'medium' and not args.rows:
            paths += ['oracle']
        for backend in paths:
            worker_output = work/(backend+'.json')
            command = [sys.executable, str(Path(__file__).resolve()), '--worker', backend,
                       '--manifest', str(work/'manifest.json'), '--worker-output', str(worker_output)]
            # A failed resource-limited control remains a result, never a reason
            # to reduce the standard fixture. Include launcher descendants.
            cap = max(512*1024**2, min(8*1024**3, psutil.virtual_memory().available*3//4))
            process = subprocess.Popen(command)
            peak, stopped = 0, None
            while process.poll() is None:
                try:
                    tree = [psutil.Process(process.pid), *psutil.Process(process.pid).children(recursive=True)]
                    peak = max(peak, sum(p.memory_info().rss for p in tree if p.is_running()))
                    if backend.endswith('old') and peak > cap:
                        stopped = 'RSS resource limit exceeded'
                        for child in reversed(tree):
                            child.kill()
                        break
                except psutil.NoSuchProcess:
                    pass
                time.sleep(.1)
            process.wait()
            if process.returncode:
                report['backends'][backend] = {'status': 'failed', 'returncode': process.returncode,
                    'reason': stopped or 'worker error', 'peak_rss_bytes': peak, 'resource_limit_bytes': cap}
                if backend.endswith('old') and stopped:
                    # Resource exhaustion is a result, never an excuse to reduce the fixture.
                    if 'oracle' not in paths:
                        paths.append('oracle')
                    continue
                raise RuntimeError('Worker failed: '+backend)
            report['backends'][backend] = json.loads(worker_output.read_text(encoding='utf-8'))
            if backend == 'prepare':
                catalog = work/'typed/metadata.sqlite'
                report['typed_catalog_sha256'] = sha256(catalog)
            write_json(output, report)
        measured = [r['result_sha256'] for k, r in report['backends'].items() if 'result_sha256' in r]
        assert len(set(measured)) == 1, 'Full diagnostic report parity failed'
        if 'oracle' in report['backends']:
            assert report['backends']['oracle']['exact_group_findings_sha256'] == report['backends']['typed_new']['execution']['counts']['exact_group_findings_sha256'], 'Hidden group statistics parity failed'
        assert sha256(catalog) == report['typed_catalog_sha256'], 'Typed catalog changed'
        if inputs.get('control'):
            assert describe_input(Path(inputs['control']['baseline'])) == inputs['control']
        assert all(sha256(Path(s['path'])) == s['sha256'] for s in report['input']['sources'])
        gate = report['backends']['typed_new']['p95_ms'] <= 5000
        report['acceptance'] = {'exact_report_parity': True, 'typed_p95_le_5s': gate,
            'latency_required': args.rows is None and args.preset in ('smoke','small'),
            'all_32_fields': config.fields_per_sample == 32, 'read_only_catalogs': True}
        if report['acceptance']['latency_required']:
            assert gate, 'Typed Diagnostics P95 exceeds 5s'
        assert report['source_files_sha256'] == {p: sha256(REPO/p) for p in CODE}
        report['status'] = 'succeeded'
    except BaseException as error:
        report.update(status='failed', error=str(error))
        raise
    finally:
        if not args.keep_artifacts:
            assert work.resolve().parent == args.output_dir.resolve()/'.work'
            assert json.loads((work/'owner.json').read_text())['run_id'] == run_id
            gc.collect()
            shutil.rmtree(work)
        write_json(output, report)
        lines = ['# C3 full Diagnostics', '', 'Status: '+report['status'], '',
                 '| Path | P50 ms | P95 ms |', '| --- | ---: | ---: |']
        for name, value in report['backends'].items():
            if 'median_ms' in value:
                lines.append(f"| {name} | {value['median_ms']:.2f} | {value['p95_ms']:.2f} |")
        lines += ['', 'Raw JSON preserves complete reports, raw timings, RSS, SQL/EXPLAIN and separate counters.',
                  'Medium uses exact original rules one CSV group at a time; no all-field row list.',
                  'Acceptance: '+json.dumps(report.get('acceptance', {}))]
        output.with_suffix('.md').write_bytes(('\n'.join(lines)+'\n').encode('utf-8'))
        print('Report: '+str(output), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preset', choices=('smoke','small','medium'), default='smoke')
    parser.add_argument('--rows', type=int, help='Development fixture only; not formal acceptance')
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--warmups', type=int, default=1)
    parser.add_argument('--keep-artifacts', action='store_true')
    parser.add_argument('--output-dir', type=Path, default=REPO/'benchmarks/results')
    parser.add_argument('--phase-c-input', type=Path, default=REPO/'benchmarks/results/baselines/2026-10-17-phase-c/medium.json')
    parser.add_argument('--worker', help=argparse.SUPPRESS)
    parser.add_argument('--manifest', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--worker-output', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.worker and not args.rows and (args.runs != 5 or args.warmups != 1):
        parser.error('Standard presets require 1 warm-up and 5 samples')
    worker(args) if args.worker else run(args)


if __name__ == '__main__':
    main()
