from __future__ import annotations

import json
from collections import Counter
from typing import Any


ROBOTICS_ROLES = [
    "tf_tree",
    "trajectory",
    "point_cloud",
    "camera_image",
    "imu",
    "joint_state",
    "diagnostics",
    "robot_model",
]

DEFAULT_THRESHOLDS = {
    "battery_low": 0.2,
    "detection_confidence": 0.5,
    "time_sync_warn_s": 0.1,
    "time_sync_critical_s": 1.0,
}

CHECK_DEFINITIONS = {
    "topic_coverage": {
        "name": "Topic Coverage",
        "recommendation": "Record core robot topics such as /tf plus sensor and trajectory streams.",
    },
    "convertibility": {
        "name": "ROS2 Convertibility",
        "recommendation": "Install or embed missing ROS message definitions and avoid unsupported serialization formats.",
    },
    "message_volume": {
        "name": "Message Volume",
        "recommendation": "Verify the bag was recorded for the expected duration and that key topics contain messages.",
    },
    "time_sync": {
        "name": "Time Sync",
        "recommendation": "Check sensor clocks and bag timestamps for topic range drift.",
    },
    "logs_and_states": {
        "name": "Logs and States",
        "recommendation": "Inspect error, fault, and warning states before using this run for analysis.",
    },
    "battery": {
        "name": "Battery",
        "recommendation": "Review battery telemetry and power state around low battery samples.",
    },
    "cv_detection": {
        "name": "CV Detection",
        "recommendation": "Review frames with no predictions or low confidence detections.",
    },
}


def normalize_thresholds(thresholds: dict[str, Any] | None) -> dict[str, float]:
    result = dict(DEFAULT_THRESHOLDS)
    for key, value in (thresholds or {}).items():
        if key not in result:
            continue
        try:
            result[key] = float(value)
        except (TypeError, ValueError):
            continue
    return result


def build_diagnostic_report(
    *,
    project_id: str,
    recordings: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    topic_rows: list[dict[str, Any]],
    error_rows: list[dict[str, Any]],
    battery_rows: list[dict[str, Any]],
    detection_rows: list[dict[str, Any]],
    thresholds: dict[str, Any] | None = None,
    limit: int = 1000,
) -> dict[str, Any]:
    resolved_thresholds = normalize_thresholds(thresholds)
    topic_values = [_row_value(row) for row in topic_rows]
    topic_values = [value for value in topic_values if isinstance(value, dict)]
    findings: list[dict[str, Any]] = []
    findings.extend(_recording_findings(recordings))
    findings.extend(_topic_coverage_findings(recordings, topic_values))
    findings.extend(_convertibility_findings(sources, topic_values))
    findings.extend(_message_volume_findings(recordings, sources, topic_values))
    findings.extend(_time_sync_findings(topic_values, resolved_thresholds))
    findings.extend(_log_findings(error_rows))
    findings.extend(_battery_findings(battery_rows, resolved_thresholds))
    findings.extend(_cv_detection_findings(detection_rows, resolved_thresholds))

    findings = [_with_finding_id(index, finding) for index, finding in enumerate(findings, start=1)]
    checks = _build_checks(findings, topic_values, sources)
    score = _health_score(findings)
    severity = _overall_severity(score, findings)
    summary = {
        "health_score": score,
        "severity": severity,
        "recording_count": len(recordings),
        "source_count": len(sources),
        "topic_count": len(topic_values),
        "finding_count": len(findings),
    }
    return {
        "project_id": project_id,
        "thresholds": resolved_thresholds,
        "summary": summary,
        "checks": checks,
        "findings": findings[: max(limit, 0)],
    }


def normalize_time_seconds(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    absolute = abs(float(value))
    if absolute >= 1e17:
        return float(value) / 1_000_000_000.0
    if absolute >= 1e14:
        return float(value) / 1_000_000.0
    if absolute >= 1e11:
        return float(value) / 1_000.0
    return float(value)


def _recording_findings(recordings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if recordings:
        return []
    return [
        _finding(
            "message_volume",
            "critical",
            "No recordings are available for diagnostics.",
            evidence={},
            recommendation="Build at least one recording before running robot diagnostics.",
        )
    ]


def _topic_coverage_findings(
    recordings: list[dict[str, Any]],
    topic_values: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not recordings or not topic_values:
        return []
    role_counts = Counter(str(value.get("role") or "raw_topic") for value in topic_values)
    findings = []
    if not any(role in role_counts for role in ROBOTICS_ROLES):
        findings.append(
            _finding(
                "topic_coverage",
                "warning",
                "No recognized robotics topic roles were found.",
                evidence={"role_counts": dict(role_counts)},
                recommendation="Check topic names and schemas or import a robotics bag with standard ROS topic names.",
            )
        )
    if role_counts.get("tf_tree", 0) == 0:
        findings.append(
            _finding(
                "topic_coverage",
                "warning",
                "TF transform topic is missing.",
                evidence={"missing_role": "tf_tree", "role_counts": dict(role_counts)},
                recommendation="Record /tf or /tf_static to enable spatial robot diagnostics.",
            )
        )
    return findings


def _convertibility_findings(
    sources: list[dict[str, Any]],
    topic_values: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    findings = []
    for source in sources:
        if source.get("type") != "ros2_db3":
            continue
        metadata = source.get("metadata") or {}
        convertible = int(metadata.get("convertible_topic_count") or 0)
        topic_count = int(metadata.get("topic_count") or 0)
        if topic_count and convertible == 0:
            findings.append(
                _finding(
                    "convertibility",
                    "critical",
                    "ROS2 bag has no convertible topics.",
                    source_id=source.get("id"),
                    evidence={
                        "topic_count": topic_count,
                        "convertible_topic_count": convertible,
                    },
                    recommendation="Embed message definitions or use a supported ROS distribution/type store.",
                )
            )
        for skipped in metadata.get("skipped_topics") or []:
            findings.append(
                _finding(
                    "convertibility",
                    "warning",
                    f"Topic {skipped.get('topic')} cannot be converted.",
                    source_id=source.get("id"),
                    entity_path=_topic_entity_path(str(skipped.get("topic") or "")),
                    key="convertible",
                    evidence=skipped,
                    recommendation="Provide the missing message definition or exclude this topic from analysis.",
                )
            )
    for value in topic_values:
        if value.get("convertible", True):
            continue
        findings.append(
            _finding(
                "convertibility",
                "warning",
                f"Topic {value.get('topic')} is marked unconvertible in the query index.",
                recording_id=value.get("recording_id"),
                source_id=value.get("source_id"),
                entity_path=_topic_entity_path(str(value.get("topic") or "")),
                key="convertible",
                evidence=value,
                recommendation="Check the source bag metadata and message definition availability.",
            )
        )
    return _dedupe_findings(findings)


def _message_volume_findings(
    recordings: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    topic_values: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    findings = []
    selected_source_ids = {recording.get("source_id") for recording in recordings}
    for source in sources:
        metadata = source.get("metadata") or {}
        if source.get("type") not in {"mcap", "ros2_db3"}:
            continue
        if source.get("id") not in selected_source_ids:
            continue
        topic_count = int(metadata.get("topic_count") or 0)
        message_count = int(metadata.get("message_count") or 0)
        if topic_count == 0 or message_count == 0:
            findings.append(
                _finding(
                    "message_volume",
                    "critical",
                    "Recording source has no topic or message volume.",
                    source_id=source.get("id"),
                    evidence={"topic_count": topic_count, "message_count": message_count},
                    recommendation="Verify the source file is a valid non-empty robotics recording.",
                )
            )
    for value in topic_values:
        count = value.get("message_count")
        if not isinstance(count, int) or count <= 0:
            findings.append(
                _finding(
                    "message_volume",
                    "warning",
                    f"Topic {value.get('topic')} has no indexed messages.",
                    recording_id=value.get("recording_id"),
                    source_id=value.get("source_id"),
                    entity_path=_topic_entity_path(str(value.get("topic") or "")),
                    key="message_count",
                    evidence=value,
                    recommendation="Check whether this topic was recorded and included in the source bag.",
                )
            )
    return findings


def _time_sync_findings(
    topic_values: list[dict[str, Any]],
    thresholds: dict[str, float],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for value in topic_values:
        recording_id = str(value.get("recording_id") or "")
        if recording_id:
            grouped.setdefault(recording_id, []).append(value)
    findings = []
    for recording_id, values in grouped.items():
        timed = []
        for value in values:
            start = normalize_time_seconds(value.get("start_time"))
            end = normalize_time_seconds(value.get("end_time"))
            if start is None or end is None:
                continue
            timed.append((value, start, end))
        if len(timed) < 2:
            continue
        base_value, base_start, base_end = timed[0]
        for value, start, end in timed[1:]:
            start_delta = abs(start - base_start)
            end_delta = abs(end - base_end)
            delta = max(start_delta, end_delta)
            if delta >= thresholds["time_sync_critical_s"]:
                severity = "critical"
            elif delta >= thresholds["time_sync_warn_s"]:
                severity = "warning"
            else:
                continue
            findings.append(
                _finding(
                    "time_sync",
                    severity,
                    f"Topic {value.get('topic')} time range differs from {base_value.get('topic')}.",
                    recording_id=recording_id,
                    source_id=value.get("source_id"),
                    entity_path="/time_sync",
                    key="time_delta",
                    evidence={
                        "base_topic": base_value.get("topic"),
                        "topic": value.get("topic"),
                        "start_delta_s": start_delta,
                        "end_delta_s": end_delta,
                        "threshold_warn_s": thresholds["time_sync_warn_s"],
                        "threshold_critical_s": thresholds["time_sync_critical_s"],
                    },
                    recommendation="Check clock sync and message timestamps for these topics.",
                )
            )
    return findings


def _log_findings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings = []
    for row in rows:
        value = row.get("value")
        text = str(value).lower()
        severity = "critical" if "error" in text or "fault" in text else "warning"
        findings.append(
            _finding(
                "logs_and_states",
                severity,
                f"Log/state diagnostic match on {row.get('key')}.",
                recording_id=row.get("recording_id"),
                entity_path=row.get("entity_path"),
                key=row.get("key"),
                evidence={"value": value, "time": row.get("time")},
                recommendation="Inspect the related log or state transition in the recording.",
            )
        )
    return findings


def _battery_findings(
    rows: list[dict[str, Any]],
    thresholds: dict[str, float],
) -> list[dict[str, Any]]:
    return [
        _finding(
            "battery",
            "warning",
            f"Battery value is below {thresholds['battery_low']}.",
            recording_id=row.get("recording_id"),
            entity_path=row.get("entity_path"),
            key=row.get("key"),
            evidence={"value": row.get("value"), "threshold": thresholds["battery_low"], "time": row.get("time")},
            recommendation="Check battery state, charger status, and run duration near this timestamp.",
        )
        for row in rows
    ]


def _cv_detection_findings(
    rows: list[dict[str, Any]],
    thresholds: dict[str, float],
) -> list[dict[str, Any]]:
    findings = []
    for row in rows:
        value = row.get("value")
        reason = value.get("reason") if isinstance(value, dict) else "detection_failure"
        findings.append(
            _finding(
                "cv_detection",
                "warning",
                f"CV detection issue: {reason}.",
                recording_id=row.get("recording_id"),
                entity_path=row.get("entity_path"),
                key=row.get("key"),
                evidence={"value": value, "threshold": thresholds["detection_confidence"], "time": row.get("time")},
                recommendation="Review model confidence and prediction availability for this frame.",
            )
        )
    return findings


def _build_checks(
    findings: list[dict[str, Any]],
    topic_values: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    role_counts = Counter(str(value.get("role") or "raw_topic") for value in topic_values)
    source_types = Counter(str(source.get("type") or "unknown") for source in sources)
    checks = []
    for check_id, definition in CHECK_DEFINITIONS.items():
        category_findings = [finding for finding in findings if finding["category"] == check_id]
        severity = _category_severity(category_findings)
        checks.append(
            {
                "id": check_id,
                "name": definition["name"],
                "status": "pass" if severity == "ok" else ("fail" if severity == "critical" else "warn"),
                "severity": severity,
                "score": _health_score(category_findings),
                "evidence": {
                    "finding_count": len(category_findings),
                    "topic_count": len(topic_values),
                    "role_counts": {role: role_counts.get(role, 0) for role in ROBOTICS_ROLES},
                    "source_types": dict(source_types),
                },
                "recommendation": definition["recommendation"],
            }
        )
    return checks


def _category_severity(findings: list[dict[str, Any]]) -> str:
    if any(finding["severity"] == "critical" for finding in findings):
        return "critical"
    if any(finding["severity"] == "warning" for finding in findings):
        return "warning"
    return "ok"


def _overall_severity(score: int, findings: list[dict[str, Any]]) -> str:
    if any(finding["severity"] == "critical" for finding in findings) or score < 60:
        return "critical"
    if any(finding["severity"] == "warning" for finding in findings) or score < 85:
        return "warning"
    return "ok"


def _health_score(findings: list[dict[str, Any]]) -> int:
    penalty = 0
    for finding in findings:
        if finding["severity"] == "critical":
            penalty += 30
        elif finding["severity"] == "warning":
            penalty += 10
        elif finding["severity"] == "info":
            penalty += 2
    return max(100 - penalty, 0)


def _with_finding_id(index: int, finding: dict[str, Any]) -> dict[str, Any]:
    return {"id": f"diag_{index:04d}", **finding}


def _finding(
    category: str,
    severity: str,
    message: str,
    *,
    recording_id: Any = None,
    source_id: Any = None,
    topic: Any = None,
    entity_path: Any = None,
    key: Any = None,
    evidence: dict[str, Any] | None = None,
    recommendation: str,
) -> dict[str, Any]:
    evidence = evidence or {}
    if topic is None and isinstance(evidence, dict):
        topic = evidence.get("topic")
    return {
        "category": category,
        "severity": severity,
        "recording_id": recording_id,
        "source_id": source_id,
        "topic": topic,
        "entity_path": entity_path,
        "key": key,
        "message": message,
        "evidence": evidence,
        "recommendation": recommendation,
    }


def _row_value(row: dict[str, Any]) -> Any:
    if "value" in row:
        value = row["value"]
    else:
        value = row.get("value_json")
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                pass
    if isinstance(value, dict):
        enriched = dict(value)
        for key in ("recording_id", "source_id"):
            if key in row and key not in enriched:
                enriched[key] = row[key]
        return enriched
    return value


def _topic_entity_path(topic: str) -> str:
    name = topic.strip("/").replace("/", "_") or "topic"
    return f"/topics/{name}"


def _dedupe_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for finding in findings:
        key = (
            finding["category"],
            finding.get("source_id"),
            finding.get("recording_id"),
            finding.get("entity_path"),
            finding["message"],
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(finding)
    return result
