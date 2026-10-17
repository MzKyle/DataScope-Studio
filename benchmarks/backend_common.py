"""Shared Phase C definitions and bounded, CSV-based correctness oracle."""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path

from datascope_core.query import QUERY_COLUMNS

QUERY_NAMES = ("find_errors", "low_battery", "state_duration", "custom_scalar_key",
               "custom_time_range", "custom_numeric_threshold", "compare")


def identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_result(actual: dict) -> dict:
    """Normalize transport types, preserving order and integer/string value semantics."""
    if actual.get('columns') != QUERY_COLUMNS or not isinstance(actual.get('rows'), list):
        raise AssertionError('Invalid canonical query shape')
    rows = []
    for row in actual['rows']:
        if set(row) != set(QUERY_COLUMNS):
            raise AssertionError('Invalid canonical row columns')
        rows.append({key: row[key] for key in QUERY_COLUMNS})
    return {'columns': list(QUERY_COLUMNS), 'rows': rows}


def assert_parity(actual: dict, expected: dict) -> None:
    from benchmarks.duckdb_poc import equivalent
    actual, expected = canonical_result(actual), canonical_result(expected)
    # The existing PoC tolerance is reused; strings/keys/order must still match exactly.
    equivalent(actual, expected)
    for left, right in zip(actual['rows'], expected['rows']):
        if isinstance(right['value'], str) and not isinstance(left['value'], str):
            raise AssertionError('Text value lost its type')
        if isinstance(right['value'], int) and not isinstance(left['value'], int):
            raise AssertionError('Integer value lost its type')


def fields_for(manifest: dict, recording_key: int) -> list[dict]:
    return [field for field in manifest['fields'] if field['recording_key'] == recording_key]


def query_filters(manifest: dict, name: str) -> dict:
    config = manifest['dataset']
    start = math.floor(.9 * (config['rows'] - 1))
    filters = {
        'find_errors': {'semantic_types': ['state'], 'error_contains': True},
        'low_battery': {'semantic_types': ['scalar', 'scalar_group'], 'battery_path_or_key': True,
                        'operator': 'lt', 'value': .2},
        'custom_scalar_key': {'semantic_types': ['scalar', 'scalar_group'],
                              'key': 'scalar_000' if config['scalar_fields'] > 10 else 'temperature'},
        'custom_time_range': {'time_start': start / config['frequency_hz'],
                             'time_end': min(config['rows'] - 1, start + 10) / config['frequency_hz']},
        'custom_numeric_threshold': {'semantic_types': ['scalar', 'scalar_group'], 'key': 'battery',
                                     'operator': 'lt', 'value': .1},
    }
    return filters[name]


def typed_select(manifest: dict, filters: dict, limit: int,
                 recording_keys: list[int] | None = None) -> str:
    """Compile dictionary-backed columns; every sample predicate remains in SQL.

    Compile-time schema pruning is shared by SQLite and DuckDB. It only selects
    columns, never reads or filters sample values in Python.
    """
    branches = []
    allowed_codes = [1] if recording_keys is None else recording_keys
    for recording in manifest['recordings']:
        code = recording['recording_key']
        if code not in allowed_codes:
            continue
        for field in fields_for(manifest, code):
            key, path, semantic = field['key'], field['entity_path'], field['semantic_type']
            if filters.get('semantic_types') and semantic not in filters['semantic_types']:
                continue
            if filters.get('key') and filters['key'].lower() not in key.lower():
                continue
            if filters.get('battery_path_or_key') and 'battery' not in (key + ' ' + path).lower():
                continue
            if filters.get('error_contains') and field['kind'] != 'text':
                continue
            if filters.get('operator') and field['kind'] == 'text':
                continue
            column = identifier(key)
            numeric = column if field['kind'] == 'real' else 'NULL'
            integer = column if field['kind'] == 'integer' else 'NULL'
            text = (f'(SELECT value FROM state_dictionary WHERE value_id = {column})'
                    if field['kind'] == 'text' else 'NULL')
            conditions = [f'recording_key = {code}']
            if filters.get('semantic_types'):
                conditions.append(literal(semantic) + ' IN (' + ','.join(
                    literal(value) for value in filters['semantic_types']) + ')')
            if filters.get('key'):
                conditions.append(f'instr(lower({literal(key)}), lower({literal(filters["key"])})) > 0')
            if filters.get('entity_path_exact') is not None:
                conditions.append(f'{literal(path)} = {literal(filters["entity_path_exact"])}')
            if filters.get('entity_path_prefix') is not None:
                prefix = filters['entity_path_prefix']
                conditions.append(f'substr({literal(path)}, 1, {len(prefix)}) = {literal(prefix)}')
            for bound, operator in (('time_start', '>='), ('time_end', '<=')):
                if filters.get(bound) is not None:
                    value = float(filters[bound])
                    if not math.isfinite(value):
                        raise ValueError('Time bounds must be finite')
                    conditions.append(f'time {operator} {value!r}')
            if filters.get('operator'):
                operators = {'lt': '<', 'lte': '<=', 'gt': '>', 'gte': '>='}
                operator = operators[filters['operator']]
                value = float(filters['value'])
                if not math.isfinite(value):
                    raise ValueError('Numeric threshold must be finite')
                conditions.append(f'{column} {operator} {value!r}')
            if filters.get('error_contains'):
                conditions.append(f'{column} IN (SELECT value_id FROM state_dictionary WHERE '
                                  + '(' + ' OR '.join(
                                      f'instr(lower(value), {literal(needle)}) > 0'
                                      for needle in ('error', 'warn', 'fault')) + '))')
            table = 'state_samples' if field['kind'] == 'text' else 'numeric_samples'
            branches.append(
                f'SELECT {literal(recording["recording_id"])} recording_id, time, '
                f'{literal(path)} entity_path, {literal(key)} AS "key", {numeric} number, {text} text_value, {integer} integer_value '
                f'FROM {table} WHERE ' + ' AND '.join(conditions))
    if not branches:
        return 'SELECT NULL recording_id, NULL AS "time", NULL entity_path, NULL AS "key", NULL number, NULL text_value, NULL integer_value WHERE 0'
    # A single branch has constant recording/path/key. Ordering those aliases can
    # hide the usable time index from SQLite, selecting a value index plus sort.
    # Dropping constant sort terms preserves the same order in every engine.
    order = 'time' if len(branches) == 1 else 'recording_id, time, entity_path, "key"'
    return 'SELECT * FROM (' + ' UNION ALL '.join(branches) + ') ORDER BY ' + order + ' LIMIT ' + str(limit)


def typed_queries(manifest: dict, limit: int) -> dict[str, str]:
    queries = {name: typed_select(manifest, query_filters(manifest, name), limit)
               for name in QUERY_NAMES if name not in {'state_duration', 'compare'}}
    recording = manifest['recordings'][0]
    states = []
    for field in fields_for(manifest, 1):
        if field['kind'] != 'text':
            continue
        column = identifier(field['key'])
        # A global limit can only need the first limit rows of each ordered group.
        # One extra row supplies LEAD for the final returned row, for every engine.
        states.append(
            'SELECT * FROM (WITH candidates AS ('
            f'SELECT time, {column} state_code FROM state_samples WHERE recording_key = 1 '
            f'ORDER BY time LIMIT {limit + 1}), durations AS ('
            'SELECT time, state_code, coalesce(lead(time) OVER (ORDER BY time), time) - time duration FROM candidates) '
            f'SELECT {literal(recording["recording_id"])} recording_id, time, '
            f'{literal(field["entity_path"])} entity_path, {literal(field["key"])} AS "key", '
            f'NULL number, (SELECT value FROM state_dictionary WHERE value_id = state_code) text_value, '
            f'NULL integer_value, duration FROM durations ORDER BY time LIMIT {limit})')
    queries['state_duration'] = ('SELECT * FROM (' + ' UNION ALL '.join(states)
                                 + ') ORDER BY recording_id, entity_path, "key", time LIMIT ' + str(limit))
    aggregates = []
    for recording in manifest['recordings']:
        code = recording['recording_key']
        for field in fields_for(manifest, code):
            if field['key'] not in {'battery', 'temperature'}:
                continue
            column = identifier(field['key'])
            aggregates.append(
                'SELECT * FROM (WITH aggregated AS ('
                f'SELECT count(*) count, min({column}) minimum, max({column}) maximum, '
                f'avg({column}) mean, max(time) last_time FROM numeric_samples WHERE recording_key = {code}) '
                f'SELECT {literal(recording["recording_id"])} recording_id, NULL AS "time", '
                f'{literal(field["entity_path"])} entity_path, {literal(field["key"])} AS "key", '
                'count, minimum, maximum, mean, '
                f'(SELECT {column} FROM numeric_samples WHERE recording_key = {code} AND time = last_time LIMIT 1) latest '
                'FROM aggregated)')
    queries['compare'] = ('SELECT * FROM (' + ' UNION ALL '.join(aggregates)
                          + ') ORDER BY recording_id, entity_path, "key" LIMIT ' + str(limit))
    return queries


def decode_typed(rows: list[tuple], name: str, manifest: dict) -> dict:
    kinds = {(recording['recording_id'], field['key']): field['kind']
             for recording in manifest['recordings']
             for field in fields_for(manifest, recording['recording_key'])}
    output = []
    for row in rows:
        if name == 'compare':
            value = dict(zip(('count', 'min', 'max', 'mean', 'latest'), row[4:]))
        elif name == 'state_duration':
            value = {'state': row[5], 'duration': row[7]}
        else:
            kind = kinds[(row[0], row[3])]
            value = row[5] if kind == 'text' else row[6] if kind == 'integer' else row[4]
        output.append(dict(zip(QUERY_COLUMNS, (*row[:4], value))))
    return canonical_result({'columns': QUERY_COLUMNS, 'rows': output})


def csv_oracle(manifest: dict, limit: int) -> dict:
    """Read the complete CSV once; keep bounded query results and streaming aggregates.

    This independent oracle permits Medium parity without invoking a Python
    materialization of 96m EAV rows. Smoke/Small are additionally checked against
    actual production Workspace outputs when a retained baseline is supplied.
    """
    outputs = {name: [] for name in QUERY_NAMES}
    state_prefixes = {}
    observed_states = set()
    window = query_filters(manifest, 'custom_time_range')
    scalar_key = query_filters(manifest, 'custom_scalar_key')['key']
    for recording in manifest['recordings']:
        code, fields = recording['recording_key'], fields_for(manifest, recording['recording_key'])
        fields = sorted(fields, key=lambda field: (field['entity_path'], field['key']))
        aggregates = {field['key']: {'count': 0, 'min': math.inf, 'max': -math.inf, 'sum': 0., 'latest': None}
                      for field in fields if field['key'] in {'battery', 'temperature'}}
        previous_time, count = -math.inf, 0
        with Path(recording['csv_path']).open(encoding='utf-8', newline='') as handle:
            for sample in csv.DictReader(handle):
                time = float(sample['timestamp'])
                if not time > previous_time:
                    raise AssertionError('Oracle requires strictly increasing, non-null times')
                previous_time, count = time, count + 1
                for key, aggregate in aggregates.items():
                    value = float(sample[key])
                    aggregate['count'] += 1
                    aggregate['sum'] += value
                    aggregate['min'] = min(aggregate['min'], value)
                    aggregate['max'] = max(aggregate['max'], value)
                    aggregate['latest'] = value
                for field in fields:
                    if field['kind'] == 'text':
                        observed_states.add(sample[field['key']])
                if code != 1:
                    continue
                for field in fields:
                    key, kind = field['key'], field['kind']
                    if sample[key] == '':
                        raise AssertionError('Phase C non-null fixture contains an empty value')
                    needs_value = (kind == 'text' or key == 'battery' or key == scalar_key
                                   or window['time_start'] <= time <= window['time_end'])
                    if not needs_value:
                        continue
                    value = sample[key] if kind == 'text' else int(sample[key]) if kind == 'integer' else float(sample[key])
                    row = dict(zip(QUERY_COLUMNS, (recording['recording_id'], time, field['entity_path'], key, value)))
                    hits = []
                    if kind == 'text':
                        if any(needle in value.lower() for needle in ('error', 'warn', 'fault')):
                            hits.append('find_errors')
                        prefix = state_prefixes.setdefault((field['entity_path'], key), [])
                        if len(prefix) < limit + 1:
                            prefix.append(row)
                    if key == 'battery':
                        if value < .2:
                            hits.append('low_battery')
                        if value < .1:
                            hits.append('custom_numeric_threshold')
                    if key == scalar_key:
                        hits.append('custom_scalar_key')
                    if window['time_start'] <= time <= window['time_end']:
                        hits.append('custom_time_range')
                    for name in hits:
                        if len(outputs[name]) < limit:
                            outputs[name].append(row)
        if count != recording['rows']:
            raise AssertionError('Oracle CSV row count mismatch')
        for key, aggregate in aggregates.items():
            field = next(field for field in fields if field['key'] == key)
            value = {name: aggregate[name] for name in ('count', 'min', 'max', 'latest')}
            value['mean'] = aggregate['sum'] / aggregate['count']
            outputs['compare'].append(dict(zip(QUERY_COLUMNS, (
                recording['recording_id'], None, field['entity_path'], key, value))))
    for prefix in state_prefixes.values():
        for index, row in enumerate(prefix[:limit]):
            next_time = prefix[index + 1]['time'] if index + 1 < len(prefix) else row['time']
            outputs['state_duration'].append({**row, 'value': {'state': row['value'], 'duration': next_time - row['time']}})
    for name in ('state_duration', 'compare'):
        outputs[name].sort(key=lambda row: (row['recording_id'], row['entity_path'], row['key'], row['time'] or 0.))
        outputs[name] = outputs[name][:limit]
    manifest['state_dictionary'] = [{'value_id': index + 1, 'value': value}
                                    for index, value in enumerate(sorted(observed_states))]
    return {name: canonical_result({'columns': QUERY_COLUMNS, 'rows': rows}) for name, rows in outputs.items()}


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
