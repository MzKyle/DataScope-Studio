from __future__ import annotations

import re
from typing import Any

import pandas as pd

from datascope_core.adapters.csv_adapter import read_csv_source
from datascope_core.adapters.jsonl_adapter import _read_jsonl
from datascope_core.models import SourceInfo, StreamInfo
from datascope_core.time_utils import infer_time_unit, normalize_time_value


def source_family(source_type: str) -> str:
    if source_type in {"csv", "jsonl"}:
        return "tabular"
    if source_type == "ros2_db3":
        return "mcap"
    return source_type


def build_schema_profile(source: SourceInfo, streams: list[StreamInfo]) -> dict[str, Any]:
    if source.source_type == "csv":
        frame = read_csv_source(source, nrows=1000)
        return _tabular_profile(source, streams, frame)
    if source.source_type == "jsonl":
        frame = pd.DataFrame(_read_jsonl(source.path, limit=1000))
        return _tabular_profile(source, streams, frame)

    fields = []
    seen: set[str] = set()
    for stream in streams:
        for field in stream.fields:
            if field in seen:
                continue
            seen.add(field)
            fields.append(
                {
                    "name": field,
                    "dtype": "adapter",
                    "null_count": 0,
                    "null_ratio": 0.0,
                    "non_null_count": None,
                    "axis": _axis(field),
                }
            )
    time_key = next((stream.time_key for stream in streams if stream.time_key), None)
    return {
        "schema_version": 1,
        "source_id": source.source_id,
        "source_type": source.source_type,
        "source_family": source_family(source.source_type),
        "sample_rows": source.metadata.get("sample_rows"),
        "fields": fields,
        "field_names": [field["name"] for field in fields],
        "timeline": {
            "field": time_key,
            "present": bool(time_key),
            "monotonic": True,
            "parse_ratio": 1.0,
            "inferred_unit": _adapter_time_unit(source.source_type),
            "mixed_units": False,
        },
        "adapter_metadata": source.metadata,
    }


def _tabular_profile(
    source: SourceInfo,
    streams: list[StreamInfo],
    frame: pd.DataFrame,
) -> dict[str, Any]:
    fields = []
    row_count = len(frame)
    for column in frame.columns:
        series = frame[column]
        null_count = int(series.isna().sum())
        non_null = series.dropna()
        normalized = [normalize_time_value(value) for value in non_null.head(1000)]
        parsed = [value for value in normalized if value is not None]
        seconds = [value.seconds for value in parsed]
        fields.append(
            {
                "name": str(column),
                "dtype": str(series.dtype),
                "null_count": null_count,
                "null_ratio": round(null_count / row_count, 6) if row_count else 0.0,
                "non_null_count": int(series.notna().sum()),
                "axis": _axis(str(column)),
                "time_parse_ratio": (
                    round(len(parsed) / len(non_null), 6) if len(non_null) else 0.0
                ),
                "time_monotonic": (
                    bool(pd.Series(seconds).is_monotonic_increasing) if seconds else None
                ),
                "inferred_time_unit": infer_time_unit(non_null),
                "first_time_unit": parsed[0].unit if parsed else None,
            }
        )
    time_key = next((stream.time_key for stream in streams if stream.time_key), None)
    timeline = _timeline_profile(frame, time_key)
    return {
        "schema_version": 1,
        "source_id": source.source_id,
        "source_type": source.source_type,
        "source_family": "tabular",
        "sample_rows": row_count,
        "fields": fields,
        "field_names": [field["name"] for field in fields],
        "timeline": timeline,
        "adapter_metadata": source.metadata,
    }


def _timeline_profile(frame: pd.DataFrame, time_key: str | None) -> dict[str, Any]:
    if not time_key or time_key not in frame:
        return {
            "field": time_key,
            "present": False,
            "monotonic": None,
            "parse_ratio": 0.0,
            "inferred_unit": None,
            "mixed_units": False,
        }
    series = frame[time_key]
    non_null = series.dropna()
    normalized = [normalize_time_value(value) for value in non_null.head(1000)]
    parsed = [value for value in normalized if value is not None]
    seconds = [value.seconds for value in parsed]
    inferred = infer_time_unit(non_null)
    return {
        "field": time_key,
        "present": True,
        "null_count": int(series.isna().sum()),
        "null_ratio": round(float(series.isna().mean()), 6) if len(series) else 0.0,
        "monotonic": bool(pd.Series(seconds).is_monotonic_increasing) if seconds else None,
        "parse_ratio": round(len(parsed) / len(non_null), 6) if len(non_null) else 0.0,
        "inferred_unit": inferred,
        "first_unit": parsed[0].unit if parsed else None,
        "mixed_units": inferred == "mixed",
    }


def _axis(field: str) -> str | None:
    match = re.search(r"(?:^|[._-])(x|y|z|w|roll|pitch|yaw|width|height)$", field.lower())
    return match.group(1) if match else None


def _adapter_time_unit(source_type: str) -> str:
    if source_type in {"mcap", "ros2_db3"}:
        return "unix_ns"
    return "relative_s"
