"""Private typed SQLite index format; business filtering stays in query.py.

Only aligned CSV samples are grouped. A schema describes physical column codecs;
bindings describe logical streams, including repeated fields and their original order.
"""
from __future__ import annotations

import hashlib
import heapq
import json
import math
import re
import sqlite3
from collections import OrderedDict
from collections.abc import Callable, Iterator
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd

from datascope_core.models import MappingSpec, SourceInfo
from datascope_core.query import _frame_records, _json_value, _row_time, _tabular_sample_values
from datascope_core.query_sql import CustomQueryPlan
from datascope_core.time_utils import prepare_tabular_frame


FORMAT_VERSION = 1
CSV_CHUNK_SIZE = 50_000
BATCH_SIZE = 10_000
MAX_FIELDS = 128
NEGATIVE_ZERO = b"\x80\x00\x00\x00\x00\x00\x00\x00"
SUPPORTED = {"scalar", "scalar_group", "state"}


def normalize_query_storage(value: str) -> str:
    if value not in {"legacy", "typed_sqlite"}:
        raise ValueError(f"Unsupported query storage: {value}")
    return value


def create_typed_registry(conn: sqlite3.Connection) -> None:
    # execute(), rather than executescript(), preserves the caller's transaction.
    statements = (
        """CREATE TABLE IF NOT EXISTS typed_indexes (
            recording_id TEXT PRIMARY KEY REFERENCES recordings(id),
            format_version INTEGER NOT NULL, source_checksum TEXT NOT NULL,
            mapping_json TEXT NOT NULL, stats_json TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS typed_schemas (
            id TEXT PRIMARY KEY, family TEXT NOT NULL, kinds_json TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS typed_datasets (
            id INTEGER PRIMARY KEY, recording_id TEXT NOT NULL REFERENCES recordings(id),
            schema_id TEXT NOT NULL REFERENCES typed_schemas(id))""",
        """CREATE TABLE IF NOT EXISTS typed_bindings (
            id INTEGER PRIMARY KEY, dataset_id INTEGER NOT NULL REFERENCES typed_datasets(id),
            recording_id TEXT NOT NULL REFERENCES recordings(id),
            source_id TEXT NOT NULL REFERENCES sources(id), column_no INTEGER NOT NULL,
            kind TEXT NOT NULL, entity_path TEXT NOT NULL, semantic_type TEXT NOT NULL,
            key TEXT NOT NULL, binding_seq INTEGER NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS typed_states (
            id INTEGER PRIMARY KEY, dataset_id INTEGER NOT NULL REFERENCES typed_datasets(id),
            value_json TEXT NOT NULL, UNIQUE(dataset_id, value_json))""",
        """CREATE TABLE IF NOT EXISTS typed_legacy_order (
            query_rowid INTEGER PRIMARY KEY, recording_id TEXT NOT NULL REFERENCES recordings(id),
            sample_seq INTEGER NOT NULL, binding_seq INTEGER NOT NULL)""",
    )
    for statement in statements:
        conn.execute(statement)


def sample_table(schema_id: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", schema_id):
        raise RuntimeError("Invalid typed SQLite schema identifier")
    return "typed_samples_" + schema_id


def clear_query_index(conn: sqlite3.Connection, recording_id: str) -> None:
    """Remove this recording's index without touching another schema user."""
    schemas = set()
    for dataset in conn.execute(
        "SELECT id, schema_id FROM typed_datasets WHERE recording_id = ?", (recording_id,)
    ).fetchall():
        schemas.add(dataset["schema_id"])
        conn.execute(f"DELETE FROM {sample_table(dataset['schema_id'])} WHERE dataset_id = ?",
                     (dataset["id"],))
        conn.execute("DELETE FROM typed_states WHERE dataset_id = ?", (dataset["id"],))
    for table in ("typed_bindings", "typed_datasets", "typed_legacy_order", "typed_indexes"):
        conn.execute(f"DELETE FROM {table} WHERE recording_id = ?", (recording_id,))
    conn.execute("DELETE FROM query_rows WHERE recording_id = ?", (recording_id,))
    for schema_id in schemas:
        if not conn.execute("SELECT 1 FROM typed_datasets WHERE schema_id = ?", (schema_id,)).fetchone():
            conn.execute(f"DROP TABLE {sample_table(schema_id)}")
            conn.execute("DELETE FROM typed_schemas WHERE id = ?", (schema_id,))


def _stamp(path: str) -> tuple[int, int]:
    stat = Path(path).stat()
    return stat.st_size, stat.st_mtime_ns


def _frames(source: SourceInfo, spec: MappingSpec) -> Iterator[pd.DataFrame]:
    # Intentionally identical to the legacy query-index CSV parser and chunk size.
    with pd.read_csv(source.path, chunksize=CSV_CHUNK_SIZE) as reader:
        for frame in reader:
            yield prepare_tabular_frame(
                frame, time_key=spec.primary_timeline,
                time_unit=spec.effective_timeline_unit or spec.timeline_unit,
                timeline_sort=spec.timeline_sort,
            )


def _kind(series: pd.Series) -> str | None:
    values = series.dropna()
    if values.empty:
        return None
    if pd.api.types.is_bool_dtype(values.dtype):
        return "bool"
    if pd.api.types.is_integer_dtype(values.dtype):
        return "int" if -(2**63) <= int(values.min()) <= int(values.max()) < 2**63 else "unsupported"
    if pd.api.types.is_float_dtype(values.dtype):
        return "float" if np.isfinite(values.to_numpy()).all() else "unsupported"
    if all(isinstance(value, str) for value in values):
        return "text"
    return "unsupported"


def preflight(source: SourceInfo, spec: MappingSpec, cancel: Callable[[], None]) -> dict:
    started = perf_counter()
    stamp = _stamp(source.path)
    fields = {field for stream in spec.streams if stream.get("enabled", True)
              and stream.get("semantic_type") in SUPPORTED for field in stream.get("source_fields", [])}
    kinds: dict[str, str] = {}
    rows = 0
    for frame in _frames(source, spec):
        cancel()
        rows += len(frame)
        for field in fields:
            if field not in frame:
                continue
            kind = _kind(frame[field])
            if kind is not None:
                previous = kinds.get(field)
                kinds[field] = kind if previous in (None, kind) else "unsupported"
    fallback = {}
    for i, stream in enumerate(spec.streams):
        if not stream.get("enabled", True):
            continue
        if stream.get("semantic_type") not in SUPPORTED:
            fallback[i] = "unsupported semantic"
        elif any(kinds.get(field) == "unsupported" or (
            kinds.get(field) == "text" and stream["semantic_type"] != "state"
        ) for field in stream.get("source_fields", [])):
            fallback[i] = "mixed, nonfinite, out-of-range or unsupported value type"
    if _stamp(source.path) != stamp:
        raise RuntimeError("CSV changed during typed schema preflight")
    return {"kinds": kinds, "fallback": fallback, "rows": rows, "stamp": stamp,
            "preflight_ms": (perf_counter() - started) * 1000}


def _create_groups(conn, recording_id, source, spec, plan):
    groups = []
    new_tables = set()
    for family in ("numeric", "state"):
        fields = list(dict.fromkeys(field for i, stream in enumerate(spec.streams)
            if stream.get("enabled", True) and i not in plan["fallback"]
            and (stream.get("semantic_type") == "state") == (family == "state")
            for field in stream.get("source_fields", [])))
        for start in range(0, len(fields), MAX_FIELDS):
            part = fields[start:start + MAX_FIELDS]
            kinds = [plan["kinds"].get(field, "float") for field in part]
            schema_json = json.dumps([FORMAT_VERSION, family, kinds], separators=(",", ":"))
            schema_id = hashlib.sha256(schema_json.encode()).hexdigest()
            table = sample_table(schema_id)
            if not conn.execute("SELECT 1 FROM typed_schemas WHERE id = ?", (schema_id,)).fetchone():
                conn.execute("INSERT INTO typed_schemas VALUES (?, ?, ?)",
                             (schema_id, family, json.dumps(kinds)))
                columns = [f"c{i} " + ("INTEGER" if family == "state" or kind in {"bool", "int"}
                                      else "REAL") for i, kind in enumerate(kinds)]
                conn.execute(f"CREATE TABLE {table} (dataset_id INTEGER NOT NULL REFERENCES "
                             "typed_datasets(id), time REAL, sample_seq INTEGER NOT NULL, "
                             + ", ".join(columns) + ")")
                new_tables.add(table)
            dataset_id = conn.execute(
                "INSERT INTO typed_datasets (recording_id, schema_id) VALUES (?, ?)",
                (recording_id, schema_id),
            ).lastrowid
            offset = 0
            for i, stream in enumerate(spec.streams):
                for j, field in enumerate(stream.get("source_fields", [])):
                    if i in plan["fallback"] or not stream.get("enabled", True) or field not in part:
                        continue
                    if (stream.get("semantic_type") == "state") != (family == "state"):
                        continue
                    path = stream.get("entity_path", "")
                    if stream["semantic_type"] == "scalar_group":
                        path += "/" + field
                    column_no = part.index(field)
                    conn.execute("""INSERT INTO typed_bindings
                        (dataset_id, recording_id, source_id, column_no, kind, entity_path,
                         semantic_type, key, binding_seq) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (dataset_id, recording_id, source.source_id, column_no, kinds[column_no],
                         path, stream["semantic_type"], field, offset + j))
                offset += len(stream.get("source_fields", [])) + (stream.get("semantic_type") == "text_log")
            groups.append({"id": dataset_id, "table": table, "family": family,
                           "fields": part, "kinds": kinds, "batch": []})
    return groups, new_tables


def build_typed_index(conn, recording_id: str, source: SourceInfo, spec: MappingSpec,
                      plan: dict, checksum: str, cancel: Callable[[], None]) -> dict:
    """The caller owns one transaction covering cleanup, DDL, samples and publication."""
    started = perf_counter()
    if _stamp(source.path) != plan["stamp"]:
        raise RuntimeError("CSV changed after typed schema preflight")
    groups, new_tables = _create_groups(conn, recording_id, source, spec, plan)
    state_cache: OrderedDict[tuple[int, str], int] = OrderedDict()
    legacy_batch, order_batch = [], []
    next_rowid = conn.execute("SELECT coalesce(max(rowid), 0) + 1 FROM query_rows").fetchone()[0]
    sample_seq = 0
    physical_rows = 0
    residual_rows = 0
    logical_rows = 0

    def state_code(dataset_id, value):
        encoded = json.dumps(value, ensure_ascii=False)
        key = (dataset_id, encoded)
        cached = state_cache.get(key)
        if cached is not None:
            state_cache.move_to_end(key)
            return cached
        conn.execute("INSERT OR IGNORE INTO typed_states (dataset_id, value_json) VALUES (?, ?)", key)
        code = conn.execute("SELECT id FROM typed_states WHERE dataset_id = ? AND value_json = ?", key).fetchone()[0]
        state_cache[key] = code
        if len(state_cache) > 4096:
            state_cache.popitem(last=False)
        return code

    def flush():
        nonlocal physical_rows
        cancel()
        for group in groups:
            batch = group["batch"]
            if batch:
                conn.executemany(f"INSERT INTO {group['table']} VALUES ("
                                 + ",".join("?" for _ in batch[0]) + ")", batch)
                physical_rows += len(batch)
                batch.clear()
        if legacy_batch:
            conn.executemany("INSERT INTO query_rows (rowid, recording_id, source_id, time, "
                             "entity_path, semantic_type, key, value_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", legacy_batch)
            conn.executemany("INSERT INTO typed_legacy_order VALUES (?, ?, ?, ?)", order_batch)
            legacy_batch.clear()
            order_batch.clear()

    fallback = set(plan["fallback"])
    binding_counts = {}
    for binding in conn.execute("SELECT dataset_id, column_no, count(*) FROM typed_bindings "
                                "WHERE recording_id = ? GROUP BY dataset_id, column_no", (recording_id,)):
        binding_counts[(binding[0], binding[1])] = binding[2]
    for frame in _frames(source, spec):
        cancel()
        for row in _frame_records(frame):
            timestamp = _row_time(row, spec.primary_timeline, spec.effective_timeline_unit or spec.timeline_unit)
            for group in groups:
                values = []
                for column_no, field in enumerate(group["fields"]):
                    raw = row.get(field)
                    value = _json_value(raw) if pd.notna(raw) else None
                    if value is not None:
                        logical_rows += binding_counts[(group["id"], column_no)]
                        if group["family"] == "state":
                            value = state_code(group["id"], value)
                        elif isinstance(value, float) and value == 0 and math.copysign(1, value) < 0:
                            # REAL affinity erases the sign of zero. This one IEEE754 escape
                            # preserves it without JSON or a second per-value sample table.
                            value = NEGATIVE_ZERO
                    values.append(value)
                if any(value is not None for value in values):
                    group["batch"].append((group["id"], timestamp, sample_seq, *values))
            if fallback:
                for binding_seq, value in _tabular_sample_values(
                    recording_id, source, spec, row, timestamp, fallback
                ):
                    legacy_batch.append((next_rowid, *value.db_tuple()))
                    order_batch.append((next_rowid, recording_id, sample_seq, binding_seq))
                    next_rowid += 1
                    residual_rows += 1
            sample_seq += 1
            if sample_seq % BATCH_SIZE == 0:
                flush()
        flush()
    if sample_seq != plan["rows"] or _stamp(source.path) != plan["stamp"]:
        raise RuntimeError("CSV changed during typed index write")
    write_ms = (perf_counter() - started) * 1000
    index_started = perf_counter()
    pages_before = conn.execute("PRAGMA page_count").fetchone()[0] - conn.execute("PRAGMA freelist_count").fetchone()[0]
    for table in new_tables:
        cancel()
        conn.execute(f"CREATE INDEX {table}_time ON {table} (dataset_id, time, sample_seq)")
    for table in {group["table"] for group in groups}:
        conn.execute(f"ANALYZE {table}")
    pages_after = conn.execute("PRAGMA page_count").fetchone()[0] - conn.execute("PRAGMA freelist_count").fetchone()[0]
    stats = {"storage": "typed_sqlite", "format_version": FORMAT_VERSION,
             "preflight_ms": plan["preflight_ms"], "write_ms": write_ms,
             "index_ms": (perf_counter() - index_started) * 1000,
             "index_build_allocated_bytes": (pages_after - pages_before) * conn.execute("PRAGMA page_size").fetchone()[0],
             "source_samples": sample_seq, "physical_sample_rows": physical_rows,
             "typed_logical_rows": logical_rows, "eav_rows": residual_rows,
             "fallback_streams": {str(i): reason for i, reason in plan["fallback"].items()},
             "sample_tables": sorted({group["table"] for group in groups})}
    cancel()
    conn.execute("INSERT INTO typed_indexes VALUES (?, ?, ?, ?, ?)",
                 (recording_id, FORMAT_VERSION, checksum,
                  json.dumps({"streams": spec.streams, "timeline": spec.primary_timeline,
                              "unit": spec.effective_timeline_unit or spec.timeline_unit,
                              "sort": spec.timeline_sort}, ensure_ascii=False), json.dumps(stats)))
    return stats


def selected_typed_indexes(conn, project_id, recording_ids):
    # Benchmark controls may intentionally open an unmodified v3 catalog read-only.
    if conn.execute("PRAGMA user_version").fetchone()[0] < 4:
        return []
    conditions = ["r.project_id = ?"]
    values = [project_id]
    if recording_ids:
        conditions.append("i.recording_id IN (" + ",".join("?" for _ in recording_ids) + ")")
        values.extend(recording_ids)
    indexes = conn.execute("SELECT i.* FROM typed_indexes i JOIN recordings r ON r.id = i.recording_id "
                           "WHERE " + " AND ".join(conditions), values).fetchall()
    if any(index["format_version"] != FORMAT_VERSION for index in indexes):
        raise RuntimeError("Unsupported typed SQLite index format")
    return indexes


def _decode_number(value, kind):
    if kind == "bool":
        if value not in (0, 1):
            raise RuntimeError("Invalid typed boolean")
        return bool(value)
    if kind == "int" and type(value) is int:
        return value
    if kind == "float":
        if isinstance(value, bytes):
            if value == NEGATIVE_ZERO:
                return -0.0
        elif isinstance(value, (int, float)) and math.isfinite(value):
            return float(value)
    raise RuntimeError(f"Invalid typed SQLite value for {kind}")


def _sort_key(row):
    timestamp = row["time"]
    return (row["recording_id"], timestamp is not None, timestamp if timestamp is not None else 0,
            row["entity_path"], row["key"], row["_sample_seq"], row["_binding_seq"])


def select_bindings(conn, conditions, values):
    return conn.execute(
        "SELECT qr.*, d.schema_id, s.family FROM typed_bindings qr "
        "JOIN recordings r ON r.id = qr.recording_id "
        "JOIN typed_datasets d ON d.id = qr.dataset_id "
        "JOIN typed_schemas s ON s.id = d.schema_id WHERE " + " AND ".join(conditions),
        values,
    ).fetchall()


def binding_select(binding, plan, template_id, predicates=(), parameters=(), limit=None):
    """Select one ordered logical field; callers prove any extra predicates."""
    table = sample_table(binding["schema_id"])
    number = binding["column_no"]
    if type(number) is not int or not 0 <= number < MAX_FIELDS:
        raise RuntimeError("Invalid typed SQLite column")
    if binding["family"] not in {"numeric", "state"}:
        raise RuntimeError("Invalid typed SQLite schema family")
    if binding["kind"] not in {"int", "float", "bool", "text"}:
        raise RuntimeError("Invalid typed SQLite kind")
    if binding["family"] == "numeric" and binding["kind"] == "text":
        raise RuntimeError("Invalid typed numeric schema kind")
    column = f"s.c{number}"
    clauses = ["s.dataset_id = ?", f"{column} IS NOT NULL"]
    args = [binding["dataset_id"]]
    if template_id == "state_duration":
        clauses.append("s.time IS NOT NULL")
    if plan is not None:
        for operator, bound in plan.time_bounds:
            if operator not in {">=", "<="}:
                raise RuntimeError("Invalid typed time bound")
            clauses.append(f"s.time {operator} ?")
            args.append(bound)
    clauses.extend(predicates)
    args.extend(parameters)
    is_state = binding["family"] == "state"
    join = f" LEFT JOIN typed_states v ON v.id = {column} AND v.dataset_id = s.dataset_id" if is_state else ""
    projection = "v.value_json" if is_state else column
    sql = (f"SELECT s.time, s.sample_seq, {projection} AS value FROM {table} s"
           + join + " WHERE " + " AND ".join(clauses) + " ORDER BY s.time, s.sample_seq")
    if limit is not None:
        sql += " LIMIT ?"
        args.append(limit)
    return sql, tuple(args)


def iter_binding_rows(conn, binding, sql, parameters, stats=None):
    cursor = conn.execute(sql, parameters)
    try:
        for row in cursor:
            if stats is not None:
                stats["typed_fetched"] = stats.get("typed_fetched", 0) + 1
            raw = row["value"]
            if binding["family"] == "state":
                if raw is None:
                    raise RuntimeError("Missing typed state dictionary entry")
                encoded = raw
            else:
                encoded = json.dumps(_decode_number(raw, binding["kind"]), ensure_ascii=False)
                if stats is not None:
                    stats["typed_numeric_decodes"] = stats.get("typed_numeric_decodes", 0) + 1
            yield {"recording_id": binding["recording_id"], "source_id": binding["source_id"],
                   "time": row["time"], "entity_path": binding["entity_path"],
                   "semantic_type": binding["semantic_type"], "key": binding["key"],
                   "value_json": encoded, "_sample_seq": row["sample_seq"],
                   "_binding_seq": binding["binding_seq"]}
    finally:
        cursor.close()


def merge_ordered_rows(iterators, limit=None, stats=None):
    try:
        for count, row in enumerate(heapq.merge(*iterators, key=_sort_key), 1):
            row.pop("_sample_seq")
            row.pop("_binding_seq")
            if stats is not None:
                stats["logical_yielded"] = stats.get("logical_yielded", 0) + 1
            yield row
            if limit is not None and count >= limit:
                break
    finally:
        for iterator in iterators:
            iterator.close()
