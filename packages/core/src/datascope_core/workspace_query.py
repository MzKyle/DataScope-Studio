from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

from datascope_core.models import MappingSpec
from datascope_core.query import (
    QUERY_TEMPLATES,
    STREAMABLE_QUERY_TEMPLATES,
    compare_recordings,
    export_query_result,
    iter_query_rows,
    run_query_template,
    run_query_template_stream,
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
            return run_query_template_stream(
                self._iter_query_rows(
                    project_id,
                    template_id=template_id,
                    recording_ids=recording_ids,
                ),
                template_id,
                params,
                limit,
            )
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

    def _index_recording(
        self,
        recording_id: str,
        source_row: dict[str, Any],
        spec: MappingSpec,
    ) -> None:
        with self._connect() as conn:
            conn.execute("delete from query_rows where recording_id = ?", (recording_id,))
            batch = []
            for row in iter_query_rows(
                recording_id,
                source_info_from_row(source_row),
                spec,
            ):
                batch.append(row.db_tuple())
                if len(batch) >= QUERY_INDEX_BATCH_SIZE:
                    _insert_query_rows(conn, batch)
                    batch = []
            if batch:
                _insert_query_rows(conn, batch)

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
    ) -> Iterator[dict[str, Any]]:
        conditions, values = self._query_conditions(
            project_id,
            template_id=template_id,
            recording_ids=recording_ids,
            semantic_types=semantic_types,
            search_tokens=search_tokens,
        )
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                select qr.*
                from query_rows qr
                join recordings r on r.id = qr.recording_id
                where {' and '.join(conditions)}
                order by qr.recording_id, qr.time, qr.entity_path, qr.key
                """,
                values,
            )
            for row in cursor:
                yield row_to_dict(row)

    def _query_conditions(
        self,
        project_id: str,
        *,
        template_id: str | None = None,
        recording_ids: list[str] | None = None,
        semantic_types: list[str] | None = None,
        search_tokens: list[str] | None = None,
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
        _add_template_conditions(conditions, template_id)
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


def _add_template_conditions(conditions: list[str], template_id: str | None) -> None:
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
        conditions.extend(["qr.semantic_type = 'state'", "qr.time is not null"])
    elif template_id == "time_sync":
        conditions.append("qr.key = 'topic_summary'")
