"""Private read boundary. Storage format and public query contracts live elsewhere."""
from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from datascope_core.query import _filter_float
from datascope_core.query_sql import CustomQueryPlan
from datascope_core.query_typed import (
    _decode_number, binding_select, iter_binding_rows, merge_ordered_rows,
    select_bindings, selected_typed_indexes,
)


@dataclass(frozen=True)
class QueryRequest:
    project_id: str
    recording_ids: list[str] | None
    semantic_types: list[str] | None
    conditions: tuple[str, ...]
    parameters: tuple[Any, ...]
    metadata_conditions: tuple[str, ...]
    metadata_parameters: tuple[Any, ...]
    custom_plan: CustomQueryPlan | None = None
    filters: Any = None
    template_id: str | None = None
    template_params: Any = None
    limit: Any = None
    candidate_limit: int | None = None
    execute_template: bool = False


@dataclass(frozen=True)
class BackendPlan:
    source: str
    sql: str
    parameters: tuple[Any, ...]
    needs_python_filter: bool
    reason: str
    binding: Mapping | None = None


class QueryBackend(Protocol):
    def plan(self, conn: sqlite3.Connection, request: QueryRequest,
             binding: Mapping | None = None, *, mixed: bool = False) -> BackendPlan: ...

    def iter_rows(self, conn: sqlite3.Connection, plan: BackendPlan,
                  stats: dict | None = None) -> Iterator[dict[str, Any]]: ...


def _positive_limit(limit):
    return limit if isinstance(limit, int) and limit > 0 else None


class LegacyQueryBackend:
    def __init__(self, convert=dict):
        self.convert = convert

    def plan(self, conn, request, binding=None, *, mixed=False):
        if binding is not None:
            sql, args = binding_select(binding, request.custom_plan, request.template_id)
            return BackendPlan("typed_compat", sql, args, True,
                               "operation or value semantics require Python", binding)
        projection = ("qr.*, coalesce(o.sample_seq, qr.rowid) AS _sample_seq, "
                      "coalesce(o.binding_seq, 0) AS _binding_seq") if mixed else "qr.*"
        join = " LEFT JOIN typed_legacy_order o ON o.query_rowid = qr.rowid" if mixed else ""
        order = "_sample_seq, _binding_seq" if mixed else "qr.rowid"
        sql = (f"select {projection} from query_rows qr "
               "join recordings r on r.id = qr.recording_id" + join
               + " where " + " and ".join(request.conditions)
               + " order by qr.recording_id, qr.time, qr.entity_path, qr.key, " + order)
        args = request.parameters
        # A mixed stream owns the global limit. No per-EAV truncation when a
        # Python value predicate remains.
        if request.candidate_limit is not None:
            sql += " limit ?"
            args += (request.candidate_limit,)
        return BackendPlan("eav", sql, args, request.candidate_limit is None,
                           "legacy EAV with C2a candidate predicates")

    def iter_rows(self, conn, plan, stats=None):
        if plan.binding is not None:
            yield from iter_binding_rows(conn, plan.binding, plan.sql, plan.parameters, stats)
            return
        cursor = conn.execute(plan.sql, plan.parameters)
        try:
            for row in cursor:
                if stats is not None:
                    stats["eav_fetched"] = stats.get("eav_fetched", 0) + 1
                yield self.convert(row)
        finally:
            cursor.close()


def register_backend_functions(conn):
    # REAL affinity stores the lossless -0.0 escape as BLOB. Only that uncommon
    # branch calls Python; invalid encodings raise instead of turning into zero.
    conn.create_function("datascope_float_blob", 1,
                         lambda value: _decode_number(value, "float"), deterministic=True)


class TypedSQLiteBackend:
    def __init__(self):
        self.legacy = LegacyQueryBackend()
        self.state_codes = {}
        self.dictionary_decodes = 0

    def _errors(self, conn, dataset):
        if dataset not in self.state_codes:
            rows = conn.execute("SELECT id,value_json FROM typed_states WHERE dataset_id = ? "
                                "ORDER BY id LIMIT 4097", (dataset,)).fetchall()
            codes = None
            if len(rows) <= 4096:
                matches = []
                for row in rows:
                    self.dictionary_decodes += 1
                    text = str(json.loads(row["value_json"])).lower()
                    if any(word in text for word in ("error", "warn", "fault")):
                        matches.append(row["id"])
                codes = tuple(matches)
                if len(codes) > 500:
                    codes = None
            self.state_codes[dataset] = codes
        return self.state_codes[dataset]

    def plan(self, conn, request, binding=None, *, mixed=False):
        assert binding is not None
        # Validate identifiers/codecs even for an optimized empty branch.
        fallback = self.legacy.plan(conn, request, binding)
        predicates, args = [], []
        residual = True
        reason = fallback.reason
        column = f"s.c{binding['column_no']}"
        numeric = (f"CASE WHEN typeof({column}) = 'blob' "
                   f"THEN datascope_float_blob({column}) ELSE {column} END")
        if request.custom_plan is not None:
            filters = request.filters
            if not isinstance(filters, dict):
                filters = {} if filters is None else None
            if filters is not None:
                try:
                    # Eager planning must never suppress a lazy conversion error.
                    for name in ("time_start", "time_end"):
                        _filter_float(filters.get(name))
                    op = str(filters.get("operator") or "any")
                    target = _filter_float(filters.get("value"))
                except (TypeError, ValueError, OverflowError):
                    return fallback
                if not request.custom_plan.needs_python_filter:
                    residual, reason = False, "metadata/time predicates complete"
                elif (op in {"gt", "gte", "lt", "lte"} and target is not None
                      and math.isfinite(target) and binding["family"] == "numeric"):
                    if binding["kind"] == "bool":
                        predicates.append("0")
                    else:
                        operator = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[op]
                        predicates.append(f"CAST(({numeric}) AS REAL) {operator} ?")
                        args.append(target)
                    residual = bool(str(filters.get("text") or "").strip()) or any(
                        (bound := _filter_float(filters.get(name))) is not None and not math.isfinite(bound)
                        for name in ("time_start", "time_end"))
                    reason = "custom floating comparison; bool excluded"
        elif request.execute_template and request.template_id == "low_battery":
            try:
                threshold = float((request.template_params or {}).get("threshold", 0.2))
            except (AttributeError, TypeError, ValueError, OverflowError):
                return fallback
            if binding["family"] == "numeric" and math.isfinite(threshold):
                predicates.append(f"({numeric}) < ?")
                args.append(threshold)
                residual, reason = False, "native numeric/bool battery comparison"
        elif request.execute_template and request.template_id == "find_errors":
            if binding["family"] == "state":
                codes = self._errors(conn, binding["dataset_id"])
                if codes is not None:
                    # Missing dictionary references must reach the strict reader.
                    predicate = f"{column} IN ({','.join('?' for _ in codes)})" if codes else "0"
                    predicates.append(f"(v.id IS NULL OR {predicate})")
                    args.extend(codes)
                    residual, reason = False, "bounded state dictionary error codes"
        if not predicates and residual:
            return fallback
        sql, parameters = binding_select(binding, request.custom_plan, request.template_id,
            predicates, args, None if residual else _positive_limit(request.limit))
        return BackendPlan("typed_sql", sql, parameters, residual, reason, binding)

    def iter_rows(self, conn, plan, stats=None):
        yield from iter_binding_rows(conn, plan.binding, plan.sql, plan.parameters, stats)


def iter_backend_rows(conn, request, *, convert=dict, stats=None):
    """One connection/snapshot, disjoint sources, one final ordered merge."""
    legacy, typed = LegacyQueryBackend(convert), TypedSQLiteBackend()
    indexes = selected_typed_indexes(conn, request.project_id, request.recording_ids)
    eav = legacy.plan(conn, request, mixed=bool(indexes))
    if not indexes:
        yield from legacy.iter_rows(conn, eav, stats)
        return
    register_backend_functions(conn)
    iterators = [legacy.iter_rows(conn, eav, stats)]
    try:
        bindings = select_bindings(conn, request.metadata_conditions, request.metadata_parameters)
        if stats is not None:
            stats["bindings"] = len(bindings)
        for binding in bindings:
            plan = typed.plan(conn, request, binding)
            if stats is not None:
                stats.setdefault("routes", []).append({"binding": binding["id"], "source": plan.source,
                    "residual": plan.needs_python_filter, "reason": plan.reason})
            backend = legacy if plan.source == "typed_compat" else typed
            iterators.append(backend.iter_rows(conn, plan, stats))
        if stats is not None:
            stats["state_dictionary_decodes"] = typed.dictionary_decodes
        yield from merge_ordered_rows(iterators, request.candidate_limit, stats)
    finally:
        for iterator in iterators:
            iterator.close()
