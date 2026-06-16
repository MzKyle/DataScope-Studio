from __future__ import annotations

from typing import Any

from datascope_core.query import run_query_template
from datascope_core.robot_diagnostics import build_diagnostic_report


class WorkspaceDiagnosticsMixin:
    def run_diagnostics(
        self,
        project_id: str,
        recording_ids: list[str] | None = None,
        thresholds: dict[str, Any] | None = None,
        limit: int = 1000,
    ) -> dict[str, Any]:
        self.get_project(project_id)
        recordings = self.list_recordings(project_id)
        if recording_ids:
            requested = set(recording_ids)
            recordings = [recording for recording in recordings if recording["id"] in requested]
            missing = requested - {recording["id"] for recording in recordings}
            if missing:
                raise ValueError(f"Recordings do not belong to project: {', '.join(sorted(missing))}")
        selected_recording_ids = [recording["id"] for recording in recordings]
        source_ids = {
            recording.get("source_id")
            for recording in recordings
            if recording.get("source_id")
        }
        sources = [self.get_source(source_id) for source_id in sorted(source_ids)]
        row_limit = max(int(limit), 1)
        topic_rows = self._query_rows(
            project_id,
            template_id="topic_summary",
            recording_ids=selected_recording_ids,
        )
        error_rows = run_query_template(
            self._query_rows(
                project_id,
                template_id="find_errors",
                recording_ids=selected_recording_ids,
            ),
            "find_errors",
            None,
            {},
            row_limit,
        )["rows"]
        battery_rows = run_query_template(
            self._query_rows(
                project_id,
                template_id="low_battery",
                recording_ids=selected_recording_ids,
            ),
            "low_battery",
            None,
            {"threshold": (thresholds or {}).get("battery_low", 0.2)},
            row_limit,
        )["rows"]
        detection_rows = run_query_template(
            self._query_rows(
                project_id,
                template_id="detection_failure",
                recording_ids=selected_recording_ids,
            ),
            "detection_failure",
            None,
            {"threshold": (thresholds or {}).get("detection_confidence", 0.5)},
            row_limit,
        )["rows"]
        return build_diagnostic_report(
            project_id=project_id,
            recordings=recordings,
            sources=sources,
            topic_rows=topic_rows,
            error_rows=error_rows,
            battery_rows=battery_rows,
            detection_rows=detection_rows,
            thresholds=thresholds,
            limit=row_limit,
        )
