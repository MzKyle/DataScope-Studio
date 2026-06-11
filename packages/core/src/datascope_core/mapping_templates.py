from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from datascope_core.inference import safe_slug
from datascope_core.mapping import derived_stream_fields
from datascope_core.models import MappingSpec, SourceInfo, StreamInfo
from datascope_core.schema_profile import source_family


def template_from_mapping(
    name: str,
    spec: MappingSpec,
    source: SourceInfo,
    *,
    template_id: str | None = None,
    version: str = "1.0.0",
) -> dict[str, Any]:
    rules = []
    for index, stream in enumerate(spec.streams):
        fields = [str(field) for field in stream.get("source_fields", [])]
        rules.append(
            {
                "key": stream.get("rule_key")
                or f"rule_{safe_slug(stream.get('stream_id', str(index)))}",
                "name": stream.get("name") or stream.get("stream_id") or f"Rule {index + 1}",
                "semantic_type": stream.get("semantic_type", "scalar"),
                "entity_path": stream.get("entity_path", "/tables/value"),
                "source_fields": fields,
                "aliases": {},
                "patterns": {},
                "required": bool(stream.get("required", False)),
                "enabled": bool(stream.get("enabled", True)),
                "expected_unit": stream.get("expected_unit"),
            }
        )
    return {
        "mapping_template": {
            "schema_version": 1,
            "id": template_id or f"mapping_template_{uuid4().hex[:12]}",
            "name": name,
            "version": version,
            "source_family": source_family(source.source_type),
            "visual_template_id": spec.template_id or "sensor_monitor",
            "timeline": {
                "field": spec.primary_timeline,
                "aliases": [],
                "pattern": None,
                "unit": spec.timeline_unit,
                "sort": spec.timeline_sort,
                "required": False,
            },
            "rules": rules,
        }
    }


def validate_mapping_template(payload: dict[str, Any]) -> dict[str, Any]:
    template = payload.get("mapping_template", payload)
    errors = []
    for key in ("id", "name", "version", "source_family"):
        if not isinstance(template.get(key), str) or not template[key].strip():
            errors.append(f"mapping_template.{key} is required")
    rules = template.get("rules")
    if not isinstance(rules, list):
        errors.append("mapping_template.rules must be a list")
        rules = []
    keys: set[str] = set()
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            errors.append(f"mapping_template.rules[{index}] must be an object")
            continue
        key = str(rule.get("key") or "")
        if not key:
            errors.append(f"mapping_template.rules[{index}].key is required")
        elif key in keys:
            errors.append(f"duplicate rule key: {key}")
        keys.add(key)
        if not isinstance(rule.get("source_fields"), list):
            errors.append(f"mapping_template.rules[{index}].source_fields must be a list")
    return {"valid": not errors, "errors": errors, "template": template}


def load_mapping_template(path: str | Path) -> dict[str, Any]:
    with open(Path(path).expanduser(), "r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    validation = validate_mapping_template(payload)
    if not validation["valid"]:
        raise ValueError("; ".join(validation["errors"]))
    return {"mapping_template": validation["template"]}


def save_mapping_template(payload: dict[str, Any], path: str | Path) -> None:
    validation = validate_mapping_template(payload)
    if not validation["valid"]:
        raise ValueError("; ".join(validation["errors"]))
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as handle:
        yaml.safe_dump(
            {"mapping_template": validation["template"]},
            handle,
            sort_keys=False,
            allow_unicode=True,
        )


def apply_mapping_template(
    payload: dict[str, Any],
    source: SourceInfo,
    streams: list[StreamInfo],
    profile: dict[str, Any],
) -> tuple[MappingSpec, list[dict[str, Any]]]:
    validation = validate_mapping_template(payload)
    if not validation["valid"]:
        raise ValueError("; ".join(validation["errors"]))
    template = validation["template"]
    expected_family = template["source_family"]
    actual_family = profile.get("source_family", source_family(source.source_type))
    if expected_family != actual_family:
        raise ValueError(
            f"Mapping template source family {expected_family} does not match {actual_family}"
        )

    available = [str(field) for field in profile.get("field_names", [])]
    issues: list[dict[str, Any]] = []
    mapped_streams: list[dict[str, Any]] = []
    consumed: set[str] = set()
    for rule in template.get("rules", []):
        stream_id = f"stream_{safe_slug(str(rule['key']))}"
        resolved: list[str] = []
        ambiguous = False
        match_candidates: list[dict[str, Any]] = []
        missing_fields: list[str] = []
        for canonical in rule.get("source_fields", []):
            matches = _match_field(
                str(canonical),
                available,
                rule.get("aliases", {}).get(canonical, []),
                rule.get("patterns", {}).get(canonical),
            )
            if len(matches) == 1:
                resolved.append(matches[0])
                consumed.add(matches[0])
            elif len(matches) > 1:
                ambiguous = True
                match_candidates.append(
                    {"field": str(canonical), "candidates": matches}
                )
                issues.append(
                    {
                        "severity": "error",
                        "code": "ambiguous_field_match",
                        "message": "Template field matching produced multiple candidates.",
                        "stream_id": stream_id,
                        "rule_key": rule["key"],
                        "field": canonical,
                        "candidates": matches,
                    }
                )
            else:
                missing_fields.append(str(canonical))
                issues.append(
                    {
                        "severity": "error" if rule.get("required") else "warning",
                        "code": (
                            "required_field_missing"
                            if rule.get("required")
                            else "field_missing"
                        ),
                        "message": f"Mapped field is missing: {canonical}",
                        "stream_id": stream_id,
                        "rule_key": rule["key"],
                        "field": canonical,
                        "candidates": [],
                    }
                )
        stream = {
            "stream_id": stream_id,
            "name": rule.get("name") or rule["key"],
            "source_fields": resolved,
            "semantic_type": rule.get("semantic_type", "scalar"),
            "entity_path": rule.get("entity_path", f"/tables/{safe_slug(str(rule['key']))}"),
            "confidence": 1.0 if resolved else 0.0,
            "role": rule.get("role"),
            "rule_key": rule["key"],
            "origin": "mapping_template",
            "required": bool(rule.get("required")),
            "enabled": bool(rule.get("enabled", True)),
            "expected_unit": rule.get("expected_unit"),
            "match_ambiguous": ambiguous,
            "match_candidates": match_candidates,
            "template_missing_fields": missing_fields,
        }
        stream.update(derived_stream_fields(stream["semantic_type"]))
        mapped_streams.append(stream)

    inferred_by_field = {
        field: stream
        for stream in streams
        for field in stream.fields
        if field not in consumed
    }
    for field in available:
        if field in consumed or field == profile.get("timeline", {}).get("field"):
            continue
        inferred = inferred_by_field.get(field)
        semantic_type = inferred.semantic_type if inferred else "scalar"
        stream = {
            "stream_id": f"stream_extra_{safe_slug(field)}",
            "name": inferred.name if inferred else field,
            "source_fields": [field],
            "semantic_type": semantic_type,
            "entity_path": f"/tables/extras/{safe_slug(field)}",
            "confidence": inferred.confidence if inferred else 0.5,
            "rule_key": f"inferred_extra:{safe_slug(field)}",
            "origin": "inferred_extra",
            "required": False,
            "enabled": False,
        }
        stream.update(derived_stream_fields(semantic_type))
        mapped_streams.append(stream)

    timeline_rule = template.get("timeline", {})
    timeline_matches = _match_field(
        str(timeline_rule.get("field") or ""),
        available,
        timeline_rule.get("aliases", []),
        timeline_rule.get("pattern"),
    )
    if len(timeline_matches) > 1:
        issues.append(
            {
                "severity": "error",
                "code": "ambiguous_time_match",
                "message": "Template timeline matching produced multiple candidates.",
                "rule_key": "timeline",
                "field": timeline_rule.get("field"),
                "candidates": timeline_matches,
            }
        )
    primary_timeline = (
        timeline_matches[0]
        if len(timeline_matches) == 1
        else profile.get("timeline", {}).get("field") or ""
    )
    spec = MappingSpec(
        mapping_id=f"mapping_{uuid4().hex[:12]}",
        source_id=source.source_id,
        app_id="",
        recording_id=f"recording_{uuid4().hex[:12]}",
        primary_timeline=primary_timeline,
        streams=mapped_streams,
        timeline_unit=str(timeline_rule.get("unit") or "auto"),
        timeline_sort=str(timeline_rule.get("sort") or "source"),
        template_id=template.get("visual_template_id") or "sensor_monitor",
        mapping_template_id=template["id"],
    )
    return spec, issues


def diff_template_applications(
    left: MappingSpec,
    right: MappingSpec,
    left_issues: list[dict[str, Any]],
    right_issues: list[dict[str, Any]],
) -> dict[str, Any]:
    left_map = {str(item.get("rule_key")): item for item in left.streams}
    right_map = {str(item.get("rule_key")): item for item in right.streams}
    rows = []
    for key in sorted(set(left_map) | set(right_map)):
        left_item = left_map.get(key)
        right_item = right_map.get(key)
        changes = []
        if left_item is None:
            changes.append("added")
        elif right_item is None:
            changes.append("missing")
        else:
            for field in ("source_fields", "semantic_type", "entity_path", "enabled"):
                if left_item.get(field) != right_item.get(field):
                    changes.append(field)
        rows.append(
            {
                "rule_key": key,
                "status": "same" if not changes else "changed",
                "changes": changes,
                "left": deepcopy(left_item),
                "right": deepcopy(right_item),
            }
        )
    return {
        "same_template": left.template_id == right.template_id,
        "timeline": {
            "left": {
                "field": left.primary_timeline,
                "unit": left.timeline_unit,
                "effective_unit": left.effective_timeline_unit,
            },
            "right": {
                "field": right.primary_timeline,
                "unit": right.timeline_unit,
                "effective_unit": right.effective_timeline_unit,
            },
        },
        "rows": rows,
        "left_issues": left_issues,
        "right_issues": right_issues,
    }


def _match_field(
    canonical: str,
    available: list[str],
    aliases: list[str] | None,
    pattern: str | None,
) -> list[str]:
    if not canonical:
        return []
    exact = [field for field in available if field == canonical]
    if exact:
        return exact
    normalized = [
        field for field in available if _normalized(field) == _normalized(canonical)
    ]
    if normalized:
        return normalized
    alias_values = [str(alias) for alias in aliases or []]
    alias_exact = [field for field in available if field in alias_values]
    if alias_exact:
        return alias_exact
    normalized_aliases = {_normalized(alias) for alias in alias_values}
    alias_normalized = [
        field for field in available if _normalized(field) in normalized_aliases
    ]
    if alias_normalized:
        return alias_normalized
    if pattern:
        regex = re.compile(pattern)
        return [field for field in available if regex.search(field)]
    return []


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())
