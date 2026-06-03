from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from typing import Any

import pandas as pd

from datascope_core.models import TIME_COLUMN_CANDIDATES


SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9_]+")


def safe_slug(value: str) -> str:
    cleaned = SAFE_NAME_RE.sub("_", value.strip().replace("/", "_")).strip("_").lower()
    return cleaned or "stream"


def flatten_record(record: dict[str, Any]) -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, value in record.items():
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                flattened[f"{key}.{nested_key}"] = _json_safe_value(nested_value)
        else:
            flattened[key] = _json_safe_value(value)
    return flattened


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def detect_time_column(columns: list[str], frame: pd.DataFrame | None = None) -> str | None:
    lower_to_original = {column.lower(): column for column in columns}
    for candidate in TIME_COLUMN_CANDIDATES:
        if candidate in lower_to_original:
            return lower_to_original[candidate]

    if frame is None:
        return None

    best_column: str | None = None
    best_score = 0.0
    for column in columns:
        series = frame[column].dropna()
        if series.empty:
            continue
        score = 0.0
        lower = column.lower()
        if "time" in lower or "date" in lower:
            score += 0.35
        if pd.api.types.is_numeric_dtype(series):
            numeric = pd.to_numeric(series, errors="coerce").dropna()
            if not numeric.empty and numeric.is_monotonic_increasing:
                score += 0.45
            if numeric.nunique() == len(numeric):
                score += 0.15
        else:
            parsed = pd.to_datetime(series.head(100), errors="coerce")
            if parsed.notna().mean() > 0.8:
                score += 0.6
        if score > best_score:
            best_score = score
            best_column = column
    return best_column if best_score >= 0.6 else None


def infer_semantic_streams(frame: pd.DataFrame, time_key: str | None) -> list[dict[str, Any]]:
    streams: list[dict[str, Any]] = []
    numeric_columns = [
        column
        for column in frame.columns
        if column != time_key and pd.api.types.is_numeric_dtype(frame[column])
    ]
    consumed: set[str] = set()

    for group_name, fields in _find_axis_groups(numeric_columns).items():
        if len(fields) >= 2:
            consumed.update(fields)
            streams.append(
                {
                    "name": group_name,
                    "semantic_type": "scalar_group",
                    "fields": fields,
                    "confidence": 0.86,
                    "metadata": {"group": group_name},
                }
            )

    for column in numeric_columns:
        if column in consumed:
            continue
        streams.append(
            {
                "name": column,
                "semantic_type": "scalar",
                "fields": [column],
                "confidence": _numeric_confidence(column, frame[column]),
                "metadata": {"dtype": str(frame[column].dtype)},
            }
        )

    object_columns = [
        column
        for column in frame.columns
        if column != time_key and not pd.api.types.is_numeric_dtype(frame[column])
    ]
    text_log_fields = _detect_text_log_fields(object_columns, frame)
    if text_log_fields:
        streams.append(
            {
                "name": "system_log",
                "semantic_type": "text_log",
                "fields": text_log_fields,
                "confidence": 0.88,
                "metadata": {},
            }
        )
        object_columns = [column for column in object_columns if column not in text_log_fields]

    for column in object_columns:
        semantic_type, confidence = _string_semantic_type(column, frame[column])
        streams.append(
            {
                "name": column,
                "semantic_type": semantic_type,
                "fields": [column],
                "confidence": confidence,
                "metadata": {"dtype": str(frame[column].dtype)},
            }
        )

    return streams


def _find_axis_groups(columns: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, dict[str, str]] = defaultdict(dict)
    for column in columns:
        lower = column.lower()
        match = re.match(r"(.+?)[._-]?([xyz])$", lower)
        if not match:
            continue
        prefix, axis = match.groups()
        if len(prefix) < 2:
            continue
        grouped[prefix][axis] = column
    return {
        safe_slug(prefix): [axis_map[axis] for axis in ("x", "y", "z") if axis in axis_map]
        for prefix, axis_map in grouped.items()
        if len(axis_map) >= 2
    }


def _numeric_confidence(column: str, series: pd.Series) -> float:
    lower = column.lower()
    confidence = 0.72
    if any(token in lower for token in ("battery", "cpu", "memory", "temp", "loss", "accuracy")):
        confidence += 0.14
    values = pd.to_numeric(series, errors="coerce").dropna()
    if not values.empty and values.between(0, 1).mean() > 0.95:
        confidence += 0.04
    return min(confidence, 0.95)


def _detect_text_log_fields(columns: list[str], frame: pd.DataFrame) -> list[str]:
    lowered = {column.lower(): column for column in columns}
    fields: list[str] = []
    for name in ("level", "severity"):
        if name in lowered:
            fields.append(lowered[name])
            break
    for name in ("message", "msg", "log", "error", "error_code"):
        if name in lowered:
            fields.append(lowered[name])
    if fields:
        return list(dict.fromkeys(fields))

    for column in columns:
        values = frame[column].dropna().astype(str)
        if not values.empty and values.map(len).median() >= 40:
            return [column]
    return []


def _string_semantic_type(column: str, series: pd.Series) -> tuple[str, float]:
    lower = column.lower()
    values = series.dropna().astype(str)
    if values.empty:
        return "state", 0.55
    unique_count = values.nunique()
    ratio = unique_count / max(len(values), 1)
    if any(token in lower for token in ("state", "status", "mode")):
        return "state", 0.88
    if ratio <= 0.2 or unique_count <= min(20, max(5, math.ceil(len(values) * 0.1))):
        return "state", 0.76
    return "text_log", 0.62

