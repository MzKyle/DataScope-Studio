from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Any
from uuid import uuid4

from datascope_core.query_backend import QueryRequest, iter_backend_rows
from datascope_core.models import MappingSpec
from datascope_core.query import (
    QUERY_TEMPLATES,
    STREAMABLE_QUERY_TEMPLATES,
    compare_recordings,
    export_query_result,
    iter_query_rows,
    run_custom_query,
    run_query_template,
    run_query_template_stream,
)
from datascope_core.query_sql import (
    CustomQueryPlan,
    compile_custom_query,
    register_custom_query_functions,
)
from datascope_core.query_typed import (
    build_typed_index, clear_query_index, normalize_query_storage, preflight,
)
from datascope_core.workspace_utils import row_to_dict, source_info_from_row, utc_now


QUERY_INDEX_BATCH_SIZE = 10_000


class WorkspaceQueryMixin:
    def query_templates(self, project_id: str) -> list[dict[str, Any]]:
        self.get_project(project_id)
        return QUERY_TEMPLATES

    def run_query(
        self,
        project_id: str,
        template_id: str,
        recording_ids: list[str] | None = None,
        params: dict[str, Any] | None = None,
        limit: int = 1000,
    ) -> dict[str, Any]:
        self.get_project(project_id)
        if template_id in STREAMABLE_QUERY_TEMPLATES:
            with closing(self._iter_query_rows(
                    project_id,
                    template_id=template_id,
                    recording_ids=recording_ids,
                    template_params=params,
                    result_limit=limit,
                    execute_template=True,
                )) as rows:
                return run_query_template_stream(rows, template_id, params, limit)
        rows = self._query_rows(
            project_id,
            template_id=template_id,
            recording_ids=recording_ids,
        )
        return run_query_template(rows, template_id, None, params, limit)

    def export_query(
        self,
        project_id: str,
        template_id: str,
        recording_ids: list[str] | None = None,
        params: dict[str, Any] | None = None,
        limit: int = 1000,
        fmt: str = "csv",
        output_path: str | None = None,
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        result = self.run_query(project_id, template_id, recording_ids, params, limit)
        export_id = f"export_{uuid4().hex[:12]}"
        export_format = fmt.lower()
        output = Path(output_path) if output_path else (
            Path(project["workspace_path"])
            / "exports"
            / f"{template_id}_{export_id}.{export_format}"
        )
        export_query_result(result, output, export_format)
        with self._connect() as conn:
            conn.execute(
                """
                insert into query_exports (id, project_id, recording_id, path, format, created_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    export_id,
                    project_id,
                    ",".join(recording_ids or []),
                    str(output),
                    export_format,
                    utc_now(),
                ),
            )
        return {
            "export_id": export_id,
            "path": str(output),
            "format": export_format,
            "rows": len(result["rows"]),
        }

    def compare(
        self,
        project_id: str,
        recording_ids: list[str],
        metric_keys: list[str] | None = None,
        mode: str = "summary",
        limit: int = 1000,
    ) -> dict[str, Any]:
        self.get_project(project_id)
        rows = self._query_rows(
            project_id,
            recording_ids=recording_ids,
            semantic_types=["scalar", "scalar_group", "state"],
            search_tokens=metric_keys,
        )
        return compare_recordings(rows, recording_ids, metric_keys, mode, limit)

    def custom_query(
        self,
        project_id: str,
        filters: dict[str, Any] | None = None,
        recording_ids: list[str] | None = None,
        semantic_types: list[str] | None = None,
        limit: int = 1000,
    ) -> dict[str, Any]:
        self.get_project(project_id)
        plan = compile_custom_query(filters)
        with closing(self._iter_query_rows(
                project_id,
                recording_ids=recording_ids,
                semantic_types=semantic_types,
                custom_plan=plan,
                custom_limit=plan.sql_limit(limit),
                filters=filters,
                result_limit=limit,
            )) as rows:
            return run_custom_query(rows, filters, limit)

    def _index_recording(
        self,
        recording_id: str,
        source_row: dict[str, Any],
        spec: MappingSpec,
        *,
        query_storage: str = "legacy",
        cancel_check=None,
        cancel_signal=None,
    ) -> dict[str, Any] | None:
        normalize_query_storage(query_storage)
        cancel = cancel_check or (lambda: None)
        cancel()
        source = source_info_from_row(source_row)
        typed_plan = preflight(source, spec, cancel) if (
            query_storage == "typed_sqlite" and source.source_type == "csv"
        ) else None
        with closing(self._connect()) as conn, conn:
            if typed_plan is not None and cancel_signal is not None:
                conn.set_progress_handler(lambda: int(cancel_signal()), 10_000)
            clear_query_index(conn, recording_id)
            if typed_plan is not None:
                try:
                    return build_typed_index(conn, recording_id, source, spec, typed_plan,
                                             source_row.get("checksum", ""), cancel)
                except sqlite3.OperationalError:
                    if cancel_signal is not None and cancel_signal():
                        cancel()
                    raise
                finally:
                    conn.set_progress_handler(None, 0)
            batch = []
            for row in iter_query_rows(
                recording_id,
                source_info_from_row(source_row),
                spec,
            ):
                batch.append(row.db_tuple())
                if len(batch) >= QUERY_INDEX_BATCH_SIZE:
                    cancel()
                    _insert_query_rows(conn, batch)
                    batch = []
            if batch:
                cancel()
                _insert_query_rows(conn, batch)
            cancel()

    def _query_rows(
        self,
        project_id: str,
        *,
        template_id: str | None = None,
        recording_ids: list[str] | None = None,
        semantic_types: list[str] | None = None,
        search_tokens: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return list(
            self._iter_query_rows(
                project_id,
                template_id=template_id,
                recording_ids=recording_ids,
                semantic_types=semantic_types,
                search_tokens=search_tokens,
            )
        )

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
        filters: Any = None,
        template_params: Any = None,
        result_limit: Any = None,
        execute_template: bool = False,
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
            if custom_plan is not None:
                register_custom_query_functions(conn, custom_plan)
                conditions.extend(custom_plan.conditions)
                values.extend(custom_plan.parameters)
            metadata_conditions, metadata_values = self._query_conditions(
                project_id, template_id=template_id, recording_ids=recording_ids,
                semantic_types=semantic_types, search_tokens=search_tokens, include_time=False,
            )
            if custom_plan is not None:
                metadata_conditions.extend(custom_plan.metadata_conditions)
                metadata_values.extend(custom_plan.metadata_parameters)
            request = QueryRequest(
                project_id, recording_ids, semantic_types, tuple(conditions), tuple(values),
                tuple(metadata_conditions), tuple(metadata_values), custom_plan, filters,
                template_id, template_params, result_limit, custom_limit, execute_template,
            )
            yield from iter_backend_rows(conn, request, convert=row_to_dict,
                                        stats=getattr(self, "_query_read_stats", None))

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


def _insert_query_rows(conn: Any, rows: list[tuple[Any, ...]]) -> None:
    conn.executemany(
        """
        insert into query_rows
          (recording_id, source_id, time, entity_path, semantic_type, key, value_json)
        values (?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


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
