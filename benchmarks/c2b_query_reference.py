"""Frozen C2b query control, captured at 73d4f8a; benchmark/test use only.

Uses the original Python business filters and original mixed reader. Never routes
through the production QueryBackend compiler under test.
"""
from __future__ import annotations

import heapq
import json
from collections.abc import Iterator
from contextlib import closing
from typing import Any

from datascope_core.query_sql import CustomQueryPlan, register_custom_query_functions
from datascope_core.query_typed import MAX_FIELDS, _decode_number, _sort_key, sample_table, selected_typed_indexes
from datascope_core.workspace_utils import row_to_dict

def iter_mixed_rows(conn, conditions, values, metadata_conditions, metadata_values,
                    plan: CustomQueryPlan | None, template_id: str | None,
                    limit: int | None, stats: dict | None = None):
    cursors = []
    iterators = []
    try:
        legacy_sql = ("SELECT qr.*, coalesce(o.sample_seq, qr.rowid) AS _sample_seq, "
                      "coalesce(o.binding_seq, 0) AS _binding_seq FROM query_rows qr "
                      "JOIN recordings r ON r.id = qr.recording_id "
                      "LEFT JOIN typed_legacy_order o ON o.query_rowid = qr.rowid WHERE "
                      + " AND ".join(conditions)
                      + " ORDER BY qr.recording_id, qr.time, qr.entity_path, qr.key, _sample_seq, _binding_seq")
        legacy = conn.execute(legacy_sql, values)
        cursors.append(legacy)

        def legacy_rows():
            for row in legacy:
                if stats is not None:
                    stats["eav_fetched"] = stats.get("eav_fetched", 0) + 1
                yield dict(row)

        iterators.append(legacy_rows())
        bindings = conn.execute(
            "SELECT qr.*, d.schema_id, s.family FROM typed_bindings qr "
            "JOIN recordings r ON r.id = qr.recording_id "
            "JOIN typed_datasets d ON d.id = qr.dataset_id "
            "JOIN typed_schemas s ON s.id = d.schema_id WHERE " + " AND ".join(metadata_conditions),
            metadata_values,
        ).fetchall()
        if stats is not None:
            stats["bindings"] = len(bindings)
        for binding in bindings:
            table = sample_table(binding["schema_id"])
            column_no = binding["column_no"]
            if type(column_no) is not int or not 0 <= column_no < MAX_FIELDS:
                raise RuntimeError("Invalid typed SQLite column")
            column = f"s.c{column_no}"
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
            is_state = binding["family"] == "state"
            if binding["family"] not in {"numeric", "state"}:
                raise RuntimeError("Invalid typed SQLite schema family")
            join = f" LEFT JOIN typed_states v ON v.id = {column} AND v.dataset_id = s.dataset_id" if is_state else ""
            projection = "v.value_json" if is_state else column
            cursor = conn.execute(f"SELECT s.time, s.sample_seq, {projection} AS value FROM {table} s"
                                  + join + " WHERE " + " AND ".join(clauses)
                                  + " ORDER BY s.time, s.sample_seq", args)
            cursors.append(cursor)

            def typed_rows(cursor=cursor, binding=binding, is_state=is_state):
                for row in cursor:
                    if stats is not None:
                        stats["typed_fetched"] = stats.get("typed_fetched", 0) + 1
                    raw = row["value"]
                    if is_state:
                        if raw is None:
                            raise RuntimeError("Missing typed state dictionary entry")
                        encoded = raw
                    else:
                        encoded = json.dumps(_decode_number(raw, binding["kind"]), ensure_ascii=False)
                    yield {"recording_id": binding["recording_id"], "source_id": binding["source_id"],
                           "time": row["time"], "entity_path": binding["entity_path"],
                           "semantic_type": binding["semantic_type"], "key": binding["key"],
                           "value_json": encoded, "_sample_seq": row["sample_seq"],
                           "_binding_seq": binding["binding_seq"]}

            iterators.append(typed_rows())
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
        for cursor in cursors:
            cursor.close()


class C2bQueryReference:
    def _iter_query_rows(
        self,
        project_id: str,
        *,
        template_id: str | None = None,
        recording_ids: list[str] | None = None,
        semantic_types: list[str] | None = None,
        search_tokens: list[str] | None = None,
        custom_plan: CustomQueryPlan | None = None,
        custom_limit: int | None = None,
        **_ignored,
    ) -> Iterator[dict[str, Any]]:
        conditions, values = self._query_conditions(
            project_id,
            template_id=template_id,
            recording_ids=recording_ids,
            semantic_types=semantic_types,
            search_tokens=search_tokens,
        )
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN")
            limit_sql = ""
            indexes = selected_typed_indexes(conn, project_id, recording_ids)
            if custom_plan is not None:
                register_custom_query_functions(conn, custom_plan)
                conditions.extend(custom_plan.conditions)
                values.extend(custom_plan.parameters)
                if custom_limit is not None:
                    limit_sql = "limit ?"
                    values.append(custom_limit)
            if indexes:
                metadata_conditions, metadata_values = self._query_conditions(
                    project_id, template_id=template_id, recording_ids=recording_ids,
                    semantic_types=semantic_types, search_tokens=search_tokens, include_time=False,
                )
                if custom_plan is not None:
                    metadata_conditions.extend(custom_plan.metadata_conditions)
                    metadata_values.extend(custom_plan.metadata_parameters)
                # The merged logical stream owns LIMIT; EAV and individual fields
                # must not truncate candidates ahead of the other sources.
                mixed_values = values[:-1] if limit_sql else values
                yield from iter_mixed_rows(conn, conditions, mixed_values,
                    metadata_conditions, metadata_values, custom_plan, template_id,
                    custom_limit, getattr(self, "_query_read_stats", None))
                return
            cursor = conn.execute(
                f"""
                select qr.*
                from query_rows qr
                join recordings r on r.id = qr.recording_id
                where {' and '.join(conditions)}
                order by qr.recording_id, qr.time, qr.entity_path, qr.key, qr.rowid
                {limit_sql}
                """,
                values,
            )
            try:
                for row in cursor:
                    stats = getattr(self, "_query_read_stats", None)
                    if stats is not None:
                        stats["eav_fetched"] = stats.get("eav_fetched", 0) + 1
                    yield row_to_dict(row)
            finally:
                cursor.close()

    def _query_conditions(
        self,
        project_id: str,
        *,
        template_id: str | None = None,
        recording_ids: list[str] | None = None,
        semantic_types: list[str] | None = None,
        search_tokens: list[str] | None = None,
        include_time: bool = True,
    ) -> tuple[list[str], list[Any]]:
        conditions = ["r.project_id = ?"]
        values: list[Any] = [project_id]
        if recording_ids:
            conditions.append(
                f"qr.recording_id in ({','.join('?' for _ in recording_ids)})"
            )
            values.extend(recording_ids)
        if semantic_types:
            conditions.append(
                f"qr.semantic_type in ({','.join('?' for _ in semantic_types)})"
            )
            values.extend(semantic_types)
        _add_template_conditions(conditions, template_id, include_time=include_time)
        if search_tokens:
            token_conditions = []
            for token in search_tokens:
                if not token:
                    continue
                token_conditions.append(
                    "(lower(qr.key) like ? or lower(qr.entity_path) like ?)"
                )
                pattern = f"%{token.lower()}%"
                values.extend([pattern, pattern])
            if token_conditions:
                conditions.append(f"({' or '.join(token_conditions)})")
        return conditions, values


def _add_template_conditions(conditions: list[str], template_id: str | None, *, include_time=True) -> None:
    if template_id == "find_errors":
        conditions.append("qr.semantic_type in ('text_log', 'state')")
    elif template_id == "low_battery":
        conditions.append("qr.semantic_type in ('scalar', 'scalar_group')")
        conditions.append(
            "(lower(qr.key) like '%battery%' or lower(qr.entity_path) like '%battery%')"
        )
    elif template_id == "detection_failure":
        conditions.append("qr.entity_path like '/camera/pred%'")
        conditions.append("qr.key in ('pred_box_count', 'score_min', 'score_mean')")
    elif template_id == "topic_summary":
        conditions.append("qr.key = 'topic_summary'")
    elif template_id == "state_duration":
        conditions.append("qr.semantic_type = 'state'")
        if include_time:
            conditions.append("qr.time is not null")
    elif template_id == "time_sync":
        conditions.append("qr.key = 'topic_summary'")
