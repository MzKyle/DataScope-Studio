"""Exact, ordered native aggregates and disposable build-time summaries.

The stored samples remain authoritative. A summary is usable only for a whole
logical group, on the same Python summation runtime, without an EAV overlap.
"""
from __future__ import annotations

import heapq
import itertools
import json
import platform
import sys
import tempfile
from array import array
from collections import defaultdict, OrderedDict
from contextlib import ExitStack, closing
from pathlib import Path

import numpy as np

from datascope_core.query import QUERY_COLUMNS
from datascope_core.query_typed import (
    WORK_BYTES, _decode_number, binding_select, sample_table, select_bindings,
    selected_typed_indexes,
)

ALGORITHM = f'ordered-python-sum-v1:{platform.python_implementation()}:{sys.version_info[:2]}'


def _key(binding):
    return binding['recording_id'], binding['entity_path'], binding['key']


def _order(recording, time, path, key, seq, binding):
    return recording, time is not None, time or 0, path, key, seq, binding


def _typed_values(conn, binding, state_only=False):
    sql, args = binding_select(binding, None, 'state_duration' if state_only else None)
    with closing(conn.execute(sql, args)) as cursor:
        for row in cursor:
            if binding['family'] == 'state':
                if row['value'] is None:
                    raise RuntimeError('Missing typed state dictionary entry')
                value = json.loads(row['value'])
            else:
                value = _decode_number(row['value'], binding['kind'])
            yield (_order(binding['recording_id'], row['time'], binding['entity_path'],
                          binding['key'], row['sample_seq'], binding['binding_seq']),
                   row['time'], value, binding['semantic_type'])


def _legacy_values(conn, key, state_only=False):
    modern = conn.execute('PRAGMA user_version').fetchone()[0] >= 4
    projection = ('coalesce(o.sample_seq,qr.rowid),coalesce(o.binding_seq,0)' if modern
                  else 'qr.rowid,0')
    join = ' LEFT JOIN typed_legacy_order o ON o.query_rowid=qr.rowid' if modern else ''
    condition = "qr.semantic_type='state' AND qr.time IS NOT NULL" if state_only else (
        "qr.semantic_type IN ('scalar','scalar_group','state')")
    sql = (f'SELECT qr.time,qr.value_json,qr.semantic_type,{projection} FROM query_rows qr'
           + join + ' WHERE qr.recording_id=? AND qr.entity_path=? AND qr.key=? AND '
           + condition + ' ORDER BY qr.time,4,5')
    with closing(conn.execute(sql, key)) as cursor:
        for time, encoded, semantic, seq, binding in cursor:
            yield _order(key[0], time, key[1], key[2], seq, binding), time, json.loads(encoded), semantic


def iter_group(conn, key, bindings, legacy, state_only=False):
    streams = [_typed_values(conn, binding, state_only) for binding in bindings]
    if legacy:
        streams.append(_legacy_values(conn, key, state_only))
    try:
        yield from heapq.merge(*streams, key=lambda item: item[0])
    finally:
        for stream in streams:
            stream.close()


def summarize(values):
    count, low, high, latest, states = 0, None, None, None, {}

    def numbers():
        nonlocal count, low, high, latest
        for _, _, value, semantic in values:
            if semantic != 'state' and not isinstance(value, (int, float)):
                continue
            latest = value
            if isinstance(value, (int, float)):
                number = float(value)
                low = number if count == 0 or number < low else low
                high = number if count == 0 or number > high else high
                count += 1
                yield number
            else:
                text = str(value)
                states[text] = states.get(text, 0) + 1

    total = sum(numbers())  # One complete ordered stream, including on Python 3.12+.
    if count:
        return {'count': count, 'min': low, 'max': high, 'mean': total / count, 'latest': latest}
    return {'count': sum(states.values()), 'states': states, 'latest': latest}


def _spooled_numbers(path, multiplicity, cancel):
    with path.open('rb') as stream:
        while raw := stream.read(64 * 1024):
            cancel()
            values = array('d')
            values.frombytes(raw)
            if multiplicity == 1:
                yield from values
            else:
                for value in values:
                    yield from itertools.repeat(value, multiplicity)


def build_summaries(conn, recording_id, cancel, *, directory=None):
    """One wide scan per dataset; bounded float spools preserve sum ordering."""
    bindings = select_bindings(conn, ['qr.recording_id=?'], [recording_id])
    groups = defaultdict(list)
    for binding in bindings:
        groups[_key(binding)].append(binding)
    overlaps = {(recording_id, *row) for row in conn.execute(
        "SELECT DISTINCT entity_path,key FROM query_rows WHERE recording_id=? "
        "AND semantic_type IN ('scalar','scalar_group','state')", (recording_id,))}
    columns = defaultdict(lambda: defaultdict(list))
    for key, items in groups.items():
        physical = {(b['dataset_id'], b['column_no']) for b in items}
        if key not in overlaps and len(physical) == 1:
            columns[items[0]['dataset_id']][items[0]['column_no']].append((key, items))
    if directory is not None:
        Path(directory).mkdir(parents=True, exist_ok=True)
    written = 0
    with tempfile.TemporaryDirectory(prefix='summary-', dir=directory) as temp:
        for dataset, selected in columns.items():
            cancel()
            first = next(iter(selected.values()))[0][1][0]
            table = sample_table(first['schema_id'])
            nums = list(selected)
            meta = {n: {'count': 0, 'min': None, 'max': None, 'latest': None,
                        'states': {}, 'values': 0} for n in nums}
            dictionaries = OrderedDict()
            with ExitStack() as stack:
                paths = {n: Path(temp) / f'{dataset}-{n}.f64' for n in nums}
                files = {n: stack.enter_context(paths[n].open('wb')) for n in nums}
                sql = (f'SELECT ' + ','.join(f'c{n}' for n in nums) + f' FROM {table} '
                       'WHERE dataset_id=? ORDER BY time,sample_seq')
                cursor = stack.enter_context(closing(conn.execute(sql, (dataset,))))
                size = max(1, min(50_000, WORK_BYTES // (128 * (len(nums) + 2))))
                while rows := cursor.fetchmany(size):
                    cancel()
                    for position, n in enumerate(nums):
                        info = meta[n]
                        binding = selected[n][0][1][0]
                        if binding['family'] == 'numeric':
                            raw_values = [row[position] for row in rows]
                            # Complete native columns have already passed the
                            # writer's codecs in this same transaction. Keep the
                            # uncommon NULL/BLOB/mixed path strictly scalar.
                            native = np.asarray(raw_values)
                            compatible = native.dtype.kind in 'iuf'
                            if binding['kind'] in {'bool', 'int'}:
                                compatible = native.dtype.kind in 'iu'
                            if compatible and binding['kind'] == 'bool':
                                compatible = bool(((native == 0) | (native == 1)).all())
                            if compatible:
                                values = native.astype('d', copy=False)
                                if not np.isfinite(values).all():
                                    raise RuntimeError('Invalid typed SQLite numeric summary')
                                low = float(values[int(np.argmin(values))])
                                high = float(values[int(np.argmax(values))])
                                if info['count'] == 0 or low < info['min']:
                                    info['min'] = low
                                if info['count'] == 0 or high > info['max']:
                                    info['max'] = high
                                info['count'] += len(values)
                                info['values'] += len(values)
                                info['latest'] = _decode_number(raw_values[-1], binding['kind'])
                                values.tofile(files[n])
                                continue
                        floats = array('d')
                        for row in rows:
                            raw = row[position]
                            if raw is None:
                                continue
                            if binding['family'] == 'state':
                                if raw not in dictionaries:
                                    entry = conn.execute('SELECT value_json FROM typed_states '
                                        'WHERE dataset_id=? AND id=?', (dataset, raw)).fetchone()
                                    if entry is None:
                                        raise RuntimeError('Missing typed state dictionary entry')
                                    dictionaries[raw] = json.loads(entry[0])
                                    if len(dictionaries) > 4096:
                                        dictionaries.popitem(last=False)
                                value = dictionaries[raw]
                            else:
                                value = _decode_number(raw, binding['kind'])
                            info['latest'] = value
                            info['values'] += 1
                            if isinstance(value, (int, float)):
                                floats.append(float(value))
                            elif info['states'] is not None:
                                text = str(value)
                                info['states'][text] = info['states'].get(text, 0) + 1
                                if len(info['states']) > 4096:
                                    info['states'] = None  # Unbounded result stays on the compatibility path.
                        if floats:
                            low, high = min(floats), max(floats)
                            if info['count'] == 0 or low < info['min']:
                                info['min'] = low
                            if info['count'] == 0 or high > info['max']:
                                info['max'] = high
                            info['count'] += len(floats)
                            floats.tofile(files[n])
            for n in nums:
                info = meta[n]
                if info['values'] == 0 or (not info['count'] and info['states'] is None):
                    continue
                for key, items in selected[n]:
                    cancel()
                    multiplicity = len(items)
                    if info['count']:
                        total = sum(_spooled_numbers(paths[n], multiplicity, cancel))
                        value = {'count': info['count'] * multiplicity, 'min': info['min'],
                                 'max': info['max'], 'mean': total / (info['count'] * multiplicity),
                                 'latest': info['latest']}
                    else:
                        value = {'count': info['values'] * multiplicity,
                                 'states': {k: v * multiplicity for k, v in info['states'].items()},
                                 'latest': info['latest']}
                    conn.execute('INSERT INTO typed_summaries VALUES (?,?,?,?,?)',
                                 (*key, ALGORITHM, json.dumps(value, ensure_ascii=False)))
                    written += 1
    return written


def read_groups(workspace, conn, project_id, ids, *, state_only=False, metric_keys=None):
    conditions, args = workspace._query_conditions(project_id, recording_ids=ids,
        semantic_types=['state'] if state_only else ['scalar', 'scalar_group', 'state'],
        search_tokens=metric_keys, include_time=False)
    groups = defaultdict(lambda: {'bindings': [], 'legacy': False})
    indexes = selected_typed_indexes(conn, project_id, ids)
    if indexes:
        for binding in select_bindings(conn, conditions, args):
            # A cached result must not hide a missing sample table, invalid
            # identifier/codec, or a broken dictionary table.
            sql, parameters = binding_select(binding, None, None)
            conn.execute(sql + ' LIMIT 0', parameters).close()
            groups[_key(binding)]['bindings'].append(binding)
    for row in conn.execute('SELECT DISTINCT qr.recording_id,qr.entity_path,qr.key '
        'FROM query_rows qr JOIN recordings r ON r.id=qr.recording_id WHERE '
        + ' AND '.join(conditions), args):
        groups[tuple(row)]['legacy'] = True
    return groups


def compare_summary(workspace, project_id, ids, metric_keys, limit):
    with closing(workspace._connect()) as conn, conn:
        conn.execute('BEGIN')
        groups = read_groups(workspace, conn, project_id, ids, metric_keys=metric_keys)
        modern = conn.execute('PRAGMA user_version').fetchone()[0] >= 5
        tokens = [item.lower() for item in metric_keys or [] if item]
        result = []
        for key, sources in sorted(groups.items()):
            if tokens and not any(t in f'{key[2]} {key[1]}'.lower() for t in tokens):
                continue
            cached = conn.execute('SELECT algorithm,value_json FROM typed_summaries '
                'WHERE recording_id=? AND entity_path=? AND key=?', key).fetchone() if modern and not sources['legacy'] else None
            if cached is not None and cached[0] == ALGORITHM:
                value = json.loads(cached[1])
            else:
                with closing(iter_group(conn, key, **sources)) as rows:
                    value = summarize(rows)
            if value['count']:
                result.append(dict(zip(QUERY_COLUMNS, (*key[:1], None, *key[1:], value))))
        return {'columns': QUERY_COLUMNS, 'rows': result[:limit]}


def state_duration(workspace, project_id, ids, limit):
    with closing(workspace._connect()) as conn, conn:
        conn.execute('BEGIN')
        groups = read_groups(workspace, conn, project_id, ids, state_only=True)
        ordered = []
        for key, sources in groups.items():
            with closing(iter_group(conn, key, **sources, state_only=True)) as rows:
                first = next(rows, None)
            if first is not None:
                ordered.append((first[0], key, sources))
        result = []
        for _, key, sources in sorted(ordered):
            with closing(iter_group(conn, key, **sources, state_only=True)) as rows:
                current = next(rows, None)
                while current is not None:
                    following = next(rows, None)
                    duration = max(float(following[1]) - float(current[1]), 0.0) if following else 0.0
                    result.append({'recording_id': key[0], 'time': current[1],
                        'entity_path': key[1], 'key': key[2],
                        'value': {'state': current[2], 'duration': duration}})
                    if len(result) >= limit:
                        return {'columns': QUERY_COLUMNS, 'rows': result}
                    current = following
        return {'columns': QUERY_COLUMNS, 'rows': result}
