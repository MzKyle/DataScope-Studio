from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from datascope_core.inference import safe_slug
from datascope_core.models import MappingSpec, SourceInfo


ENTITY_PATH_RE = re.compile(r"^/(?:[A-Za-z0-9_.-]+/?)*$")
SUGGESTION_ACTIONS = {
    "set_timeline_field",
    "set_timeline_unit",
    "set_timeline_sort",
    "replace_source_field",
    "set_source_fields",
    "set_entity_path",
    "set_semantic_type",
    "set_stream_enabled",
}
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

RECOMMENDATIONS = {
    "missing_time_column": "Choose a usable time field or explicitly use row sequence.",
    "non_monotonic_time": "Sort rows by normalized time before conversion.",
    "time_nulls": "Choose another time field, use row sequence, or clean empty source values.",
    "time_parse_failure": "Choose another time field, set the correct unit, or clean invalid values.",
    "mixed_time_units": "Select the unit that applies to the entire time column.",
    "time_unit_mismatch": "Use the inferred unit unless the source metadata is known to be wrong.",
    "invalid_timeline_sort": "Use source order or stable ascending time order.",
    "unsupported_semantic_type": "Choose one of the semantic types supported by this source family.",
    "required_field_missing": "Replace each missing field with a matching source field.",
    "field_missing": "Replace the missing field or disable the optional stream.",
    "ambiguous_field_match": "Choose the intended source field from the template matches.",
    "ambiguous_time_match": "Choose the intended timeline field from the template matches.",
    "required_fields_empty": "Map a populated field or populate the required source data.",
    "fields_empty": "Map a populated field or disable the optional stream.",
    "field_nulls": "Review null handling in the source or disable the optional stream.",
    "invalid_entity_path": "Use a valid absolute Rerun entity path.",
    "duplicate_entity_path": "Assign a unique entity path to this stream.",
    "missing_coordinate_axes": "Map all coordinate axes required by the semantic type.",
    "incomplete_rotation": "Provide a full quaternion or a complete roll/pitch/yaw set.",
    "field_unit_mismatch": "Review the mapped field or update the template unit expectation.",
    "mcap_summary_unavailable": "Check MCAP readability and optional MCAP dependencies.",
    "mcap_topics_unavailable": "Inspect the MCAP source and verify that it contains readable topics.",
    "ros2_distro_fallback": "Confirm that Humble message definitions match the recorded ROS2 bag.",
    "ros2_topics_skipped": "Provide message definitions for skipped custom topics if they are required.",
    "ros2_no_convertible_topics": "Use a bag with standard types or embedded message definitions.",
    "point_cloud_sample_warning": "Inspect the reported point-cloud file and repair or replace it.",
    "point_cloud_coordinates_missing": "Provide point-cloud data with readable x/y/z coordinates.",
    "image_stream_required": "Enable an image stream before converting this image folder.",
    "no_enabled_streams": "Enable and correctly map at least one stream before conversion.",
}


class MappingValidationError(RuntimeError):
    code = "mapping_validation_failed"

    def __init__(self, report: dict[str, Any]) -> None:
        super().__init__("Mapping validation failed")
        self.report = report


def validate_mapping(
    source: SourceInfo,
    spec: MappingSpec,
    profile: dict[str, Any],
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    family = str(profile.get("source_family") or source.source_type)
    available_fields = [str(field) for field in profile.get("field_names", [])]
    available = set(available_fields)
    field_stats = {field["name"]: field for field in profile.get("fields", [])}
    seen_paths: dict[str, str] = {}
    reserved_paths = {
        str(stream.get("entity_path") or "")
        for stream in spec.streams
        if stream.get("enabled", True)
        and _valid_entity_path(str(stream.get("entity_path") or ""))
    }
    enabled_streams = [
        stream for stream in spec.streams if stream.get("enabled", True)
    ]
    if not enabled_streams:
        _issue(
            issues,
            "error",
            "no_enabled_streams",
            "The mapping does not contain any enabled streams.",
        )

    timeline = profile.get("timeline", {})
    if spec.timeline_sort not in {"source", "ascending"}:
        _issue(
            issues,
            "error",
            "invalid_timeline_sort",
            f"Unsupported timeline sort mode: {spec.timeline_sort}",
        )
    if family == "tabular" and spec.primary_timeline and spec.primary_timeline not in available:
        _issue(
            issues,
            "warning",
            "missing_time_column",
            f"Mapped time column is not available: {spec.primary_timeline}",
            field=spec.primary_timeline,
        )
    elif family == "tabular" and spec.primary_timeline:
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
        if monotonic is False and spec.timeline_sort != "ascending":
            _issue(
                issues,
                "warning",
                "non_monotonic_time",
                "Time values are not monotonic.",
                field=spec.primary_timeline,
            )
        if float(null_ratio or 0) > 0:
            _issue(
                issues,
                "warning",
                "time_nulls",
                "Time column contains empty values.",
                field=spec.primary_timeline,
            )
        if float(parse_ratio or 0) < 1:
            _issue(
                issues,
                "warning",
                "time_parse_failure",
                "Some time values cannot be parsed.",
                field=spec.primary_timeline,
            )
        if inferred == "mixed":
            _issue(
                issues,
                "warning",
                "mixed_time_units",
                "Time values appear to use mixed units.",
                field=spec.primary_timeline,
            )
        configured = _canonical_unit(spec.timeline_unit)
        if configured not in {"auto", inferred, None} and inferred not in {None, "mixed"}:
            _issue(
                issues,
                "warning",
                "time_unit_mismatch",
                f"Configured time unit {configured} differs from inferred unit {inferred}.",
                field=spec.primary_timeline,
                inferred_unit=inferred,
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
        required = bool(stream.get("required"))

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
        for missing_field in [
            *missing,
            *[str(field) for field in stream.get("template_missing_fields", [])],
        ]:
            _issue(
                issues,
                "error",
                "required_field_missing" if required else "field_missing",
                f"Mapped field is missing: {missing_field}",
                stream_id=stream_id,
                rule_key=rule_key,
                field=missing_field,
                required=required,
            )
        match_candidates = stream.get("match_candidates", [])
        if match_candidates:
            for match in match_candidates:
                _issue(
                    issues,
                    "error",
                    "ambiguous_field_match",
                    "Template field matching produced multiple candidates.",
                    stream_id=stream_id,
                    rule_key=rule_key,
                    field=str(match.get("field") or ""),
                    candidates=[str(item) for item in match.get("candidates", [])],
                )
        elif stream.get("match_ambiguous"):
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
            item.get("non_null_count") is not None
            and int(item["non_null_count"]) == 0
            for item in present_stats
        ):
            _issue(
                issues,
                "error" if required else "warning",
                "required_fields_empty" if required else "fields_empty",
                "All mapped fields are empty in the inspected sample.",
                stream_id=stream_id,
                rule_key=rule_key,
                required=required,
            )
        elif any(float(item.get("null_ratio") or 0) > 0 for item in present_stats):
            _issue(
                issues,
                "warning",
                "field_nulls",
                "Mapped fields contain empty values.",
                stream_id=stream_id,
                rule_key=rule_key,
                required=required,
            )

        if family != "mcap":
            if not _valid_entity_path(entity_path):
                suggested_path = _unique_entity_path(
                    _sanitized_entity_path(entity_path, stream),
                    reserved_paths,
                )
                reserved_paths.add(suggested_path)
                _issue(
                    issues,
                    "error",
                    "invalid_entity_path",
                    f"Invalid Rerun entity path: {entity_path or '<empty>'}",
                    stream_id=stream_id,
                    rule_key=rule_key,
                    suggested_entity_path=suggested_path,
                )
            elif entity_path in seen_paths:
                suggested_path = _unique_entity_path(entity_path, reserved_paths)
                reserved_paths.add(suggested_path)
                _issue(
                    issues,
                    "error",
                    "duplicate_entity_path",
                    f"Entity path is also used by {seen_paths[entity_path]}.",
                    stream_id=stream_id,
                    rule_key=rule_key,
                    suggested_entity_path=suggested_path,
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

    return build_validation_report(source, spec, profile, issues)


def build_validation_report(
    source: SourceInfo,
    spec: MappingSpec,
    profile: dict[str, Any],
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    family = str(profile.get("source_family") or source.source_type)
    supported = sorted(SUPPORTED_BY_FAMILY.get(family, set()))
    streams_by_id = {
        str(stream.get("stream_id") or ""): stream for stream in spec.streams
    }
    streams_by_rule = {
        str(stream.get("rule_key") or ""): stream for stream in spec.streams
    }
    enriched = []
    for raw_issue in _dedupe_issues(issues):
        issue = dict(raw_issue)
        stream = streams_by_id.get(str(issue.get("stream_id") or ""))
        if stream is None:
            stream = streams_by_rule.get(str(issue.get("rule_key") or ""))
            if stream is not None:
                issue["stream_id"] = str(stream.get("stream_id") or "") or None
        issue.setdefault("message", issue.get("field") or issue["code"])
        issue["recommendation"] = issue.get("recommendation") or RECOMMENDATIONS.get(
            issue["code"],
            "Review the source data and mapping configuration for this issue.",
        )
        issue["suggestions"] = issue.get("suggestions") or _suggestions_for_issue(
            issue,
            stream,
            spec,
            profile,
            supported,
        )
        enriched.append(issue)

    errors = [issue for issue in enriched if issue.get("severity") == "error"]
    warnings = [issue for issue in enriched if issue.get("severity") == "warning"]
    effective_unit = _effective_timeline_unit(spec, profile)
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "issues": enriched,
        "summary": {"errors": len(errors), "warnings": len(warnings)},
        "source_family": family,
        "supported_semantic_types": supported,
        "effective_timeline_unit": effective_unit,
    }


def _suggestions_for_issue(
    issue: dict[str, Any],
    stream: dict[str, Any] | None,
    spec: MappingSpec,
    profile: dict[str, Any],
    supported: list[str],
) -> list[dict[str, Any]]:
    code = str(issue["code"])
    stream_id = str(issue.get("stream_id") or "")
    available = [str(field) for field in profile.get("field_names", [])]
    suggestions: list[dict[str, Any]] = []

    if code == "missing_time_column":
        for field in _time_field_candidates(profile, exclude=spec.primary_timeline):
            suggestions.append(
                _suggestion(
                    "set_timeline_field",
                    f"Use {field} as the time field",
                    field=field,
                )
            )
        suggestions.append(
            _suggestion("set_timeline_field", "Use row sequence", field="")
        )
    elif code == "non_monotonic_time":
        suggestions.append(
            _suggestion(
                "set_timeline_sort",
                "Sort by time ascending",
                sort="ascending",
            )
        )
    elif code in {"time_nulls", "time_parse_failure"}:
        for field in _time_field_candidates(profile, exclude=spec.primary_timeline):
            suggestions.append(
                _suggestion(
                    "set_timeline_field",
                    f"Use {field} as the time field",
                    field=field,
                )
            )
        suggestions.append(
            _suggestion("set_timeline_field", "Use row sequence", field="")
        )
    elif code == "mixed_time_units":
        for unit in ("relative_s", "unix_s", "unix_ms", "unix_us", "unix_ns", "datetime"):
            suggestions.append(
                _suggestion("set_timeline_unit", f"Use {unit}", unit=unit)
            )
    elif code == "time_unit_mismatch":
        inferred = issue.get("inferred_unit")
        if inferred:
            suggestions.append(
                _suggestion(
                    "set_timeline_unit",
                    f"Use inferred unit {inferred}",
                    unit=str(inferred),
                )
            )
    elif code == "invalid_timeline_sort":
        suggestions.append(
            _suggestion("set_timeline_sort", "Keep source order", sort="source")
        )
    elif code == "unsupported_semantic_type" and stream_id:
        for semantic_type in supported:
            suggestions.append(
                _suggestion(
                    "set_semantic_type",
                    f"Use {semantic_type}",
                    stream_id=stream_id,
                    semantic_type=semantic_type,
                )
            )
    elif code in {"field_missing", "required_field_missing", "ambiguous_field_match"}:
        old_field = str(issue.get("field") or "")
        candidates = [
            str(candidate) for candidate in issue.get("candidates", [])
        ] or _similar_fields(old_field, available)
        issue["candidates"] = candidates[:3]
        for candidate in candidates[:3]:
            suggestions.append(
                _suggestion(
                    "replace_source_field",
                    f"Use {candidate}",
                    stream_id=stream_id,
                    old_field=old_field,
                    new_field=candidate,
                )
            )
        if code == "field_missing" and stream_id:
            suggestions.append(
                _suggestion(
                    "set_stream_enabled",
                    "Disable optional stream",
                    stream_id=stream_id,
                    enabled=False,
                )
            )
    elif code == "ambiguous_time_match":
        for candidate in [str(item) for item in issue.get("candidates", [])][:3]:
            suggestions.append(
                _suggestion(
                    "set_timeline_field",
                    f"Use {candidate} as the time field",
                    field=candidate,
                )
            )
    elif code in {"fields_empty", "field_nulls"} and stream_id:
        if not bool(issue.get("required")):
            suggestions.append(
                _suggestion(
                    "set_stream_enabled",
                    "Disable optional stream",
                    stream_id=stream_id,
                    enabled=False,
                )
            )
    elif code in {"invalid_entity_path", "duplicate_entity_path"} and stream_id:
        path = issue.get("suggested_entity_path")
        if path:
            suggestions.append(
                _suggestion(
                    "set_entity_path",
                    f"Use {path}",
                    stream_id=stream_id,
                    entity_path=str(path),
                )
            )
    elif code == "image_stream_required":
        image_stream = next(
            (
                item
                for item in spec.streams
                if item.get("semantic_type") == "image"
                and not item.get("enabled", True)
            ),
            None,
        )
        if image_stream is not None:
            suggestions.append(
                _suggestion(
                    "set_stream_enabled",
                    "Enable image stream",
                    stream_id=str(image_stream.get("stream_id") or ""),
                    enabled=True,
                )
            )
    elif code == "missing_coordinate_axes" and stream_id and stream is not None:
        candidate_fields = _coordinate_field_candidates(
            str(stream.get("semantic_type") or ""),
            available,
        )
        if candidate_fields:
            suggestions.append(
                _suggestion(
                    "set_source_fields",
                    f"Use {', '.join(candidate_fields)}",
                    stream_id=stream_id,
                    fields=candidate_fields,
                )
            )
    return suggestions


def _suggestion(action: str, label: str, **params: Any) -> dict[str, Any]:
    if action not in SUGGESTION_ACTIONS:
        raise ValueError(f"Unsupported mapping suggestion action: {action}")
    return {"action": action, "label": label, "params": params}


def _dedupe_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: dict[tuple[str, str, str], int] = {}
    for issue in issues:
        key = (
            str(issue.get("code") or ""),
            str(issue.get("rule_key") or issue.get("stream_id") or ""),
            str(issue.get("field") or ""),
        )
        if key not in seen:
            seen[key] = len(deduped)
            deduped.append(dict(issue))
            continue
        current = deduped[seen[key]]
        for field in ("stream_id", "rule_key", "message", "candidates"):
            if not current.get(field) and issue.get(field):
                current[field] = issue[field]
    return deduped


def _time_field_candidates(
    profile: dict[str, Any],
    *,
    exclude: str | None,
) -> list[str]:
    ranked = []
    for index, field in enumerate(profile.get("fields", [])):
        name = str(field.get("name") or "")
        if not name or name == exclude:
            continue
        parse_ratio = float(field.get("time_parse_ratio") or 0)
        inferred = field.get("inferred_time_unit")
        name_score = 1 if any(token in name.lower() for token in ("time", "date")) else 0
        if parse_ratio <= 0 and not name_score:
            continue
        ranked.append(
            (
                name_score,
                parse_ratio,
                inferred not in {None, "mixed"},
                -index,
                name,
            )
        )
    ranked.sort(reverse=True)
    return [item[-1] for item in ranked[:3]]


def _similar_fields(field: str, available: list[str]) -> list[str]:
    normalized = _normalized(field)
    ranked = []
    for index, candidate in enumerate(available):
        candidate_normalized = _normalized(candidate)
        score = SequenceMatcher(None, normalized, candidate_normalized).ratio()
        if normalized and (
            normalized in candidate_normalized or candidate_normalized in normalized
        ):
            score += 0.25
        ranked.append((score, -index, candidate))
    ranked.sort(reverse=True)
    return [candidate for score, _, candidate in ranked if score >= 0.35][:3]


def _coordinate_field_candidates(
    semantic_type: str,
    available: list[str],
) -> list[str]:
    if semantic_type == "points2d":
        required = ("x", "y")
    elif semantic_type in {"points3d", "trajectory3d", "transform3d"}:
        required = ("x", "y", "z")
    elif semantic_type == "boxes2d":
        required = ("x", "y", "w", "h")
    else:
        return []
    by_axis: dict[str, list[str]] = {}
    for field in available:
        by_axis.setdefault(_field_role(field), []).append(field)
    if not all(by_axis.get(axis) for axis in required):
        return []
    candidates = [by_axis[axis][0] for axis in required]
    prefixes = {
        re.split(r"[._/-]", field.lower())[0]
        for field in candidates
        if re.search(r"[._/-]", field)
    }
    return candidates if len(prefixes) <= 1 else []


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


def _effective_timeline_unit(
    spec: MappingSpec,
    profile: dict[str, Any],
) -> str:
    timeline = profile.get("timeline", {})
    field_stats = {field["name"]: field for field in profile.get("fields", [])}
    selected_time = field_stats.get(spec.primary_timeline, {})
    inferred = (
        timeline.get("inferred_unit")
        if timeline.get("field") == spec.primary_timeline
        else selected_time.get("inferred_time_unit")
    )
    first_unit = (
        timeline.get("first_unit")
        if timeline.get("field") == spec.primary_timeline
        else selected_time.get("first_time_unit")
    )
    configured = _canonical_unit(spec.timeline_unit) or "auto"
    if configured != "auto":
        return configured
    if inferred and inferred != "mixed":
        return str(inferred)
    if first_unit:
        return str(first_unit)
    return "auto"


def _valid_entity_path(path: str) -> bool:
    return bool(ENTITY_PATH_RE.fullmatch(path)) and "//" not in path


def _sanitized_entity_path(path: str, stream: dict[str, Any]) -> str:
    tokens = [safe_slug(token) for token in path.split("/") if token.strip()]
    if tokens:
        return "/" + "/".join(tokens)
    semantic_type = str(stream.get("semantic_type") or "")
    prefix = {
        "scalar": "metrics",
        "scalar_group": "metrics",
        "state": "states",
        "text_log": "logs",
        "points2d": "camera",
        "boxes2d": "camera",
        "points3d": "world",
        "trajectory3d": "world",
        "transform3d": "world",
        "image": "camera",
    }.get(semantic_type, "tables")
    name = safe_slug(str(stream.get("name") or stream.get("stream_id") or "stream"))
    return f"/{prefix}/{name}"


def _unique_entity_path(path: str, reserved: set[str]) -> str:
    if path not in reserved:
        return path
    suffix = 2
    while f"{path}_{suffix}" in reserved:
        suffix += 1
    return f"{path}_{suffix}"


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _issue(
    issues: list[dict[str, Any]],
    severity: str,
    code: str,
    message: str,
    *,
    stream_id: str | None = None,
    rule_key: str | None = None,
    field: str | None = None,
    **details: Any,
) -> None:
    issues.append(
        {
            "severity": severity,
            "code": code,
            "message": message,
            "stream_id": stream_id,
            "rule_key": rule_key,
            "field": field,
            **details,
        }
    )
