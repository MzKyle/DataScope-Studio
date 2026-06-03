from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from datascope_core.models import ConvertRequest


def write_tabular_recording(frame: pd.DataFrame, request: ConvertRequest) -> None:
    import rerun as rr

    Path(request.output_rrd).parent.mkdir(parents=True, exist_ok=True)
    with rr.RecordingStream(
        request.app_id,
        recording_id=request.recording_id,
        send_properties=False,
    ) as rec:
        rec.save(request.output_rrd)
        rec.send_recording_name(request.recording_id)
        for row_index, row in frame.iterrows():
            _set_row_time(rec, row, row_index, request.mappings)
            for mapping in request.mappings:
                _log_mapping(rec, row, mapping)


def _set_row_time(rec: Any, row: pd.Series, row_index: int, mappings: list[dict[str, Any]]) -> None:
    time_key = _primary_time_key(mappings)
    if time_key and time_key in row and pd.notna(row[time_key]):
        value = row[time_key]
        numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
        if pd.notna(numeric):
            rec.set_time("time", duration=float(numeric))
            return
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.notna(parsed):
            rec.set_time("time", timestamp=parsed.to_pydatetime())
            return
    rec.set_time("row", sequence=int(row_index))


def _primary_time_key(mappings: list[dict[str, Any]]) -> str | None:
    for mapping in mappings:
        time_key = mapping.get("time_key") or mapping.get("timeline_source_field")
        if time_key:
            return str(time_key)
    return None


def _log_mapping(rec: Any, row: pd.Series, mapping: dict[str, Any]) -> None:
    import rerun as rr

    semantic_type = mapping.get("semantic_type")
    fields = mapping.get("source_fields", [])
    entity_path = mapping.get("entity_path")
    if not entity_path or not fields:
        return
    if semantic_type == "scalar":
        value = _first_present(row, fields)
        if value is not None and pd.notna(value):
            rec.log(entity_path, rr.Scalars(float(value)))
    elif semantic_type == "scalar_group":
        for field in fields:
            if field in row and pd.notna(row[field]):
                rec.log(f"{entity_path}/{field}", rr.Scalars(float(row[field])))
    elif semantic_type == "state":
        value = _first_present(row, fields)
        if value is not None and pd.notna(value):
            rec.log(entity_path, rr.StateChange(state=str(value)))
    elif semantic_type == "text_log":
        message = _message_from_fields(row, fields)
        if message:
            rec.log(entity_path, rr.TextLog(message, level=_log_level(row, fields)))


def _first_present(row: pd.Series, fields: list[str]) -> Any:
    for field in fields:
        if field in row:
            return row[field]
    return None


def _message_from_fields(row: pd.Series, fields: list[str]) -> str:
    parts: list[str] = []
    for field in fields:
        if field in row and pd.notna(row[field]):
            parts.append(f"{field}={row[field]}")
    return " ".join(parts)


def _log_level(row: pd.Series, fields: list[str]) -> Any:
    import rerun as rr

    for field in fields:
        if field.lower() in {"level", "severity"} and field in row and pd.notna(row[field]):
            value = str(row[field]).upper()
            if value in {"ERROR", "ERR"}:
                return rr.TextLogLevel.ERROR
            if value in {"WARN", "WARNING"}:
                return rr.TextLogLevel.WARN
            if value in {"DEBUG", "TRACE"}:
                return rr.TextLogLevel.DEBUG
    return rr.TextLogLevel.INFO

