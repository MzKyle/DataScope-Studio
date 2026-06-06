from __future__ import annotations

import re
from typing import Any

from datascope_core.models import MappingSpec, SourceInfo


ENTITY_PATH_RE = re.compile(r"^/(?:[A-Za-z0-9_.-]+/?)*$")
SUPPORTED_BY_FAMILY = {
    "tabular": {
        "scalar",
        "scalar_group",
        "state",
        "text_log",
        "points2d",
        "points3d",
        "trajectory3d",
        "boxes2d",
        "transform3d",
    },
    "image_folder": {"image", "boxes2d", "points2d", "segmentation", "scalar"},
    "point_cloud": {"points3d"},
    "mcap": {
        "mcap",
        "image",
        "points3d",
        "transform3d",
        "trajectory3d",
        "asset3d",
        "scalar_group",
        "text_log",
    },
}


class MappingValidationError(RuntimeError):
    def __init__(self, report: dict[str, Any]) -> None:
        super().__init__("Mapping validation failed")
        self.report = report


def validate_mapping(
    source: SourceInfo,
    spec: MappingSpec,
    profile: dict[str, Any],
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    family = profile.get("source_family", source.source_type)
    available = set(profile.get("field_names", []))
    field_stats = {field["name"]: field for field in profile.get("fields", [])}
    seen_paths: dict[str, str] = {}

    timeline = profile.get("timeline", {})
    if not spec.primary_timeline or spec.primary_timeline not in available and family == "tabular":
        _issue(
            issues,
            "warning",
            "missing_time_column",
            "No usable time column is mapped; row sequence will be used.",
            field=spec.primary_timeline or None,
        )
    elif family == "tabular":
        selected_time = field_stats.get(spec.primary_timeline, {})
        monotonic = (
            timeline.get("monotonic")
            if timeline.get("field") == spec.primary_timeline
            else selected_time.get("time_monotonic")
        )
        null_ratio = selected_time.get("null_ratio", timeline.get("null_ratio"))
        parse_ratio = (
            timeline.get("parse_ratio")
            if timeline.get("field") == spec.primary_timeline
            else selected_time.get("time_parse_ratio")
        )
        inferred = (
            timeline.get("inferred_unit")
            if timeline.get("field") == spec.primary_timeline
            else selected_time.get("inferred_time_unit")
        )
        if monotonic is False:
            _issue(issues, "warning", "non_monotonic_time", "Time values are not monotonic.")
        if float(null_ratio or 0) > 0:
            _issue(issues, "warning", "time_nulls", "Time column contains empty values.")
        if float(parse_ratio or 0) < 1:
            _issue(issues, "warning", "time_parse_failure", "Some time values cannot be parsed.")
        if inferred == "mixed":
            _issue(issues, "warning", "mixed_time_units", "Time values appear to use mixed units.")
        configured = _canonical_unit(spec.timeline_unit)
        if configured not in {"auto", inferred, None} and inferred not in {None, "mixed"}:
            _issue(
                issues,
                "warning",
                "time_unit_mismatch",
                f"Configured time unit {configured} differs from inferred unit {inferred}.",
                field=spec.primary_timeline,
            )

    supported = SUPPORTED_BY_FAMILY.get(family)
    for stream in spec.streams:
        if not stream.get("enabled", True):
            continue
        stream_id = str(stream.get("stream_id") or "")
        rule_key = stream.get("rule_key")
        fields = [str(field) for field in stream.get("source_fields", [])]
        semantic_type = str(stream.get("semantic_type") or "")
        entity_path = str(stream.get("entity_path") or "")

        if supported is not None and semantic_type not in supported:
            _issue(
                issues,
                "error",
                "unsupported_semantic_type",
                f"{semantic_type} is not supported for {family} sources.",
                stream_id=stream_id,
                rule_key=rule_key,
            )
        missing = [field for field in fields if field not in available]
        if missing and family == "tabular":
            _issue(
                issues,
                "error" if stream.get("required") else "warning",
                "required_field_missing" if stream.get("required") else "field_missing",
                f"Mapped fields are missing: {', '.join(missing)}",
                stream_id=stream_id,
                rule_key=rule_key,
            )
        if stream.get("match_ambiguous"):
            _issue(
                issues,
                "error",
                "ambiguous_field_match",
                "Template field matching produced multiple candidates.",
                stream_id=stream_id,
                rule_key=rule_key,
            )
        present_stats = [field_stats[field] for field in fields if field in field_stats]
        if present_stats and all(
            int(item.get("non_null_count") or 0) == 0 for item in present_stats
        ):
            _issue(
                issues,
                "error" if stream.get("required") else "warning",
                "required_fields_empty" if stream.get("required") else "fields_empty",
                "All mapped fields are empty in the inspected sample.",
                stream_id=stream_id,
                rule_key=rule_key,
            )
        elif any(float(item.get("null_ratio") or 0) > 0 for item in present_stats):
            _issue(
                issues,
                "warning",
                "field_nulls",
                "Mapped fields contain empty values.",
                stream_id=stream_id,
                rule_key=rule_key,
            )

        if family != "mcap":
            if not ENTITY_PATH_RE.fullmatch(entity_path) or "//" in entity_path:
                _issue(
                    issues,
                    "error",
                    "invalid_entity_path",
                    f"Invalid Rerun entity path: {entity_path or '<empty>'}",
                    stream_id=stream_id,
                    rule_key=rule_key,
                )
            elif entity_path in seen_paths:
                _issue(
                    issues,
                    "error",
                    "duplicate_entity_path",
                    f"Entity path is also used by {seen_paths[entity_path]}.",
                    stream_id=stream_id,
                    rule_key=rule_key,
                )
            else:
                seen_paths[entity_path] = stream_id

        if family == "tabular":
            _validate_coordinates(issues, semantic_type, fields, stream_id, rule_key)
        expected_unit = stream.get("expected_unit")
        actual_unit = stream.get("source_unit")
        if expected_unit and actual_unit and expected_unit != actual_unit:
            _issue(
                issues,
                "warning",
                "field_unit_mismatch",
                f"Expected {expected_unit}, source declares {actual_unit}.",
                stream_id=stream_id,
                rule_key=rule_key,
            )

    errors = [issue for issue in issues if issue["severity"] == "error"]
    warnings = [issue for issue in issues if issue["severity"] == "warning"]
    selected_time = field_stats.get(spec.primary_timeline, {})
    inferred_time_unit = (
        timeline.get("inferred_unit")
        if timeline.get("field") == spec.primary_timeline
        else selected_time.get("inferred_time_unit")
    )
    first_time_unit = (
        timeline.get("first_unit")
        if timeline.get("field") == spec.primary_timeline
        else selected_time.get("first_time_unit")
    )
    effective_unit = _effective_unit(
        spec.timeline_unit,
        inferred_time_unit,
        first_time_unit,
    )
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "issues": issues,
        "summary": {"errors": len(errors), "warnings": len(warnings)},
        "effective_timeline_unit": effective_unit,
    }


def _validate_coordinates(
    issues: list[dict[str, Any]],
    semantic_type: str,
    fields: list[str],
    stream_id: str,
    rule_key: str | None,
) -> None:
    lowered = [_field_role(field) for field in fields]
    required: set[str] | None = None
    if semantic_type == "points2d":
        required = {"x", "y"}
    elif semantic_type in {"points3d", "trajectory3d"}:
        required = {"x", "y", "z"}
    elif semantic_type == "boxes2d":
        valid_box = {"x", "y", "w", "h"} <= set(lowered) or {
            "xmin",
            "ymin",
            "xmax",
            "ymax",
        } <= set(lowered)
        if not valid_box:
            _issue(
                issues,
                "error",
                "missing_coordinate_axes",
                "Boxes2D requires x/y/w/h or xmin/ymin/xmax/ymax fields.",
                stream_id=stream_id,
                rule_key=rule_key,
            )
        return
    elif semantic_type == "transform3d":
        required = {"x", "y", "z"}
        rotation = set(lowered) & {"qx", "qy", "qz", "qw", "roll", "pitch", "yaw"}
        if rotation and not (
            {"qx", "qy", "qz", "qw"} <= set(lowered)
            or {"roll", "pitch", "yaw"} <= set(lowered)
        ):
            _issue(
                issues,
                "error",
                "incomplete_rotation",
                "Transform rotation must provide a full quaternion or roll/pitch/yaw.",
                stream_id=stream_id,
                rule_key=rule_key,
            )
    if required and not required <= set(lowered):
        _issue(
            issues,
            "error",
            "missing_coordinate_axes",
            f"{semantic_type} requires {', '.join(sorted(required))} fields.",
            stream_id=stream_id,
            rule_key=rule_key,
        )


def _field_role(field: str) -> str:
    lower = field.lower()
    token = re.split(r"[._/-]", lower)[-1]
    aliases = {
        "width": "w",
        "height": "h",
        "quat_x": "qx",
        "quat_y": "qy",
        "quat_z": "qz",
        "quat_w": "qw",
    }
    if token in {"qx", "qy", "qz", "qw"}:
        return token
    if "quat" in lower:
        suffix = token[-1:]
        return f"q{suffix}" if suffix in {"x", "y", "z", "w"} else token
    return aliases.get(token, token)


def _canonical_unit(unit: str | None) -> str | None:
    if unit == "seconds":
        return "relative_s"
    return unit


def _effective_unit(
    configured: str,
    inferred: str | None,
    first_unit: str | None,
) -> str:
    configured = _canonical_unit(configured) or "auto"
    if configured != "auto":
        return configured
    if inferred and inferred != "mixed":
        return str(inferred)
    if first_unit:
        return str(first_unit)
    return "auto"


def _issue(
    issues: list[dict[str, Any]],
    severity: str,
    code: str,
    message: str,
    *,
    stream_id: str | None = None,
    rule_key: str | None = None,
    field: str | None = None,
) -> None:
    issues.append(
        {
            "severity": severity,
            "code": code,
            "message": message,
            "stream_id": stream_id,
            "rule_key": rule_key,
            "field": field,
        }
    )
