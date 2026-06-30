from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from datascope_core.query import run_query_template
from datascope_core.robot_diagnostics import DEFAULT_THRESHOLDS, build_diagnostic_report
from datascope_core.workspace_utils import row_to_dict, safe_output_name, utc_now


DIAGNOSTIC_PRESETS = {
    "balanced": {
        "id": "balanced",
        "name": "Balanced",
        "description": "Default offline robot diagnostics thresholds.",
        "thresholds": dict(DEFAULT_THRESHOLDS),
    },
    "strict": {
        "id": "strict",
        "name": "Strict",
        "description": "Flag weaker battery, detection, and time sync signals earlier.",
        "thresholds": {
            "battery_low": 0.3,
            "detection_confidence": 0.7,
            "time_sync_warn_s": 0.05,
            "time_sync_critical_s": 0.5,
        },
    },
    "lenient": {
        "id": "lenient",
        "name": "Lenient",
        "description": "Reduce noise for exploratory review of imperfect datasets.",
        "thresholds": {
            "battery_low": 0.1,
            "detection_confidence": 0.3,
            "time_sync_warn_s": 0.25,
            "time_sync_critical_s": 2.0,
        },
    },
}


class WorkspaceDiagnosticsMixin:
    def run_diagnostics(
        self,
        project_id: str,
        recording_ids: list[str] | None = None,
        thresholds: dict[str, Any] | None = None,
        preset: str | None = None,
        limit: int = 1000,
    ) -> dict[str, Any]:
        self.get_project(project_id)
        resolved_thresholds = _resolve_thresholds(preset, thresholds)
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
            thresholds=resolved_thresholds,
            limit=row_limit,
        )

    def diagnostic_presets(self, project_id: str) -> list[dict[str, Any]]:
        self.get_project(project_id)
        return [dict(value) for value in DIAGNOSTIC_PRESETS.values()]

    def export_diagnostics(
        self,
        project_id: str,
        recording_ids: list[str] | None = None,
        thresholds: dict[str, Any] | None = None,
        *,
        preset: str | None = None,
        fmt: str = "json",
        output_path: str | None = None,
        limit: int = 1000,
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        export_format = fmt.lower()
        if export_format not in {"json", "csv", "html"}:
            raise ValueError(f"Unsupported diagnostics export format: {fmt}")
        resolved_thresholds = _resolve_thresholds(preset, thresholds)
        report = self.run_diagnostics(
            project_id,
            recording_ids=recording_ids,
            thresholds=resolved_thresholds,
            limit=limit,
        )
        export_id = f"diagnostic_export_{uuid4().hex[:12]}"
        output = _diagnostics_export_path(
            Path(project["workspace_path"]),
            export_id,
            export_format,
            output_path,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        _write_diagnostics_export(report, output, export_format)
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                insert into diagnostic_exports
                  (id, project_id, recording_ids_json, thresholds_json, summary_json,
                   path, format, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    export_id,
                    project_id,
                    json.dumps(recording_ids or [], ensure_ascii=False),
                    json.dumps(resolved_thresholds, ensure_ascii=False, sort_keys=True),
                    json.dumps(report["summary"], ensure_ascii=False, sort_keys=True),
                    str(output),
                    export_format,
                    now,
                ),
            )
        return {
            "export_id": export_id,
            "project_id": project_id,
            "path": str(output),
            "format": export_format,
            "recording_ids": recording_ids or [],
            "thresholds": resolved_thresholds,
            "summary": report["summary"],
        }

    def list_diagnostic_exports(self, project_id: str) -> list[dict[str, Any]]:
        self.get_project(project_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from diagnostic_exports
                where project_id = ?
                order by created_at desc
                """,
                (project_id,),
            ).fetchall()
        return [_diagnostic_export_from_row(row) for row in rows]


def _resolve_thresholds(
    preset: str | None,
    thresholds: dict[str, Any] | None,
) -> dict[str, float]:
    preset_id = preset or "balanced"
    if preset_id not in DIAGNOSTIC_PRESETS:
        raise ValueError(f"Unsupported diagnostics preset: {preset_id}")
    resolved = dict(DIAGNOSTIC_PRESETS[preset_id]["thresholds"])
    for key, value in (thresholds or {}).items():
        if key not in resolved:
            continue
        try:
            resolved[key] = float(value)
        except (TypeError, ValueError):
            continue
    return resolved


def _diagnostics_export_path(
    project_path: Path,
    export_id: str,
    fmt: str,
    output_path: str | None,
) -> Path:
    filename = f"diagnostics_{safe_output_name(export_id)}.{fmt}"
    if output_path:
        requested = Path(output_path).expanduser()
        if requested.suffix:
            return requested
        return requested / filename
    return project_path / "exports" / filename


def _write_diagnostics_export(report: dict[str, Any], path: Path, fmt: str) -> None:
    if fmt == "json":
        path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return
    if fmt == "csv":
        columns = [
            "id",
            "severity",
            "category",
            "recording_id",
            "source_id",
            "topic",
            "entity_path",
            "key",
            "message",
            "recommendation",
            "evidence",
        ]
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for finding in report.get("findings", []):
                writer.writerow(
                    {
                        key: (
                            json.dumps(finding.get(key), ensure_ascii=False, sort_keys=True)
                            if key == "evidence"
                            else finding.get(key)
                        )
                        for key in columns
                    }
                )
        return
    if fmt == "html":
        path.write_text(_diagnostics_html(report), encoding="utf-8")
        return
    raise ValueError(f"Unsupported diagnostics export format: {fmt}")


def _diagnostics_html(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    findings = report.get("findings", [])
    rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(str(item.get('severity', '')))}</td>"
        f"<td>{html.escape(str(item.get('category', '')))}</td>"
        f"<td>{html.escape(str(item.get('recording_id') or ''))}</td>"
        f"<td>{html.escape(str(item.get('topic') or ''))}</td>"
        f"<td>{html.escape(str(item.get('message', '')))}</td>"
        f"<td>{html.escape(str(item.get('recommendation', '')))}</td>"
        "</tr>"
        for item in findings
    )
    report_json = html.escape(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>DataScope Diagnostics Report</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 32px; color: #172026; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
    th, td {{ border: 1px solid #d8dee4; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f6f8fa; }}
    pre {{ background: #f6f8fa; padding: 16px; overflow: auto; }}
  </style>
</head>
<body>
  <h1>DataScope Diagnostics Report</h1>
  <p>Severity: <strong>{html.escape(str(summary.get('severity', 'unknown')).upper())}</strong></p>
  <p>Health score: {html.escape(str(summary.get('health_score', '')))}
     | Recordings: {html.escape(str(summary.get('recording_count', '')))}
     | Sources: {html.escape(str(summary.get('source_count', '')))}
     | Topics: {html.escape(str(summary.get('topic_count', '')))}
     | Findings: {html.escape(str(summary.get('finding_count', '')))}</p>
  <h2>Findings</h2>
  <table>
    <thead><tr><th>Severity</th><th>Category</th><th>Recording</th><th>Topic</th><th>Message</th><th>Recommendation</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <h2>Full JSON</h2>
  <pre>{report_json}</pre>
</body>
</html>
"""


def _diagnostic_export_from_row(row: Any) -> dict[str, Any]:
    result = row_to_dict(row)
    result["recording_ids"] = json.loads(result.pop("recording_ids_json") or "[]")
    result["thresholds"] = json.loads(result.pop("thresholds_json") or "{}")
    result["summary"] = json.loads(result.pop("summary_json") or "{}")
    return result
