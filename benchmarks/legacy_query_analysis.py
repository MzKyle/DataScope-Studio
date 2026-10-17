"""Separate-process execution ablations; do not add their times as causal fractions."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from time import perf_counter

from datascope_core.query import _custom_row_matches, run_custom_query

from benchmarks.backend_common import assert_parity, literal, query_filters
from benchmarks.benchmark_memory import MemorySampler
from benchmarks.benchmark_query import latency_stats, measure_query
from benchmarks.sqlite_typed_poc import configure


def analyze(args, manifest: dict) -> dict:
    retained = manifest.get('reused_preparations', {}).get('legacy_sqlite_eav')
    path = args.manifest.parent / 'legacy_sqlite_eav/samples.sqlite' if retained is None else Path(retained['path'])
    golden = json.loads((args.manifest.parent / 'golden.json').read_text(encoding='utf-8'))
    filters = query_filters(manifest, 'custom_time_range')
    # Equivalent sample-only selection/order to Workspace._iter_query_rows; no time predicate.
    sql = ('SELECT qr.* FROM query_rows qr JOIN recording_dictionary r ON r.recording_id = qr.recording_id '
           f'WHERE qr.recording_id = {literal(manifest["recordings"][0]["recording_id"])} '
           'ORDER BY qr.recording_id, qr.time, qr.entity_path, qr.key')
    conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    configure(conn)
    conn.row_factory = sqlite3.Row
    memory = MemorySampler()
    report = {'scope': 'primary custom time window; actual production run_custom_query on the new sample-only EAV catalog',
              'sql': sql, 'logical_candidate_rows': manifest['dataset']['expected_query_rows'],
              'returned_rows': len(golden['custom_time_range']['rows']),
              'interpretation': 'separate repeated ablations, cache/allocator/order dependent; differences are observational and not additive causal percentages'}
    try:
        with memory:
            report['production_custom_time_range'] = measure_query(
                lambda: run_custom_query((dict(row) for row in conn.execute(sql)), filters, manifest['query_limit']),
                lambda actual: assert_parity(actual, golden['custom_time_range']),
                runs=args.query_runs, warmups=args.warmups, memory=memory, name='legacy_production/custom_time_range')
            report['ablations'] = {}
            for mode in ('sqlite_rows', 'row_dicts', 'row_dicts_json', 'row_dicts_json_python_filter'):
                samples, executes, iterations = [], [], []
                with memory.stage(mode):
                    for index in range(args.warmups + args.query_runs):
                        started = perf_counter()
                        cursor = conn.execute(sql)
                        executed = perf_counter()
                        count, hits = 0, 0
                        for raw in cursor:
                            count += 1
                            if mode != 'sqlite_rows':
                                row = dict(raw)
                                if mode in {'row_dicts_json', 'row_dicts_json_python_filter'}:
                                    value = json.loads(row['value_json'])
                                    if mode == 'row_dicts_json_python_filter' and _custom_row_matches(row, value, filters):
                                        hits += 1
                        ended = perf_counter()
                        if count != manifest['dataset']['expected_query_rows']:
                            raise AssertionError('Ablation did not consume all candidate rows')
                        if mode.endswith('python_filter') and min(hits, manifest['query_limit']) != report['returned_rows']:
                            raise AssertionError('Ablation time-window hit count mismatch')
                        if index >= args.warmups:
                            samples.append((ended - started) * 1000)
                            executes.append((executed - started) * 1000)
                            iterations.append((ended - executed) * 1000)
                        print(f'  ablation {mode}: {ended - started:.3f} s, {count:,} rows', flush=True)
                report['ablations'][mode] = {'total': latency_stats(samples), 'execute_to_first_row': latency_stats(executes),
                                             'iterate_consume': latency_stats(iterations), 'candidate_rows': count,
                                             'json_decodes': count if 'json' in mode else 0}
        report['memory'] = memory.report()
        report['status'] = 'succeeded'
        return report
    finally:
        conn.close()
