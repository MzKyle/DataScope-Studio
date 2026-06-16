from __future__ import annotations

import pickle
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from datascope_core.models import ConvertRequest
from datascope_core.time_utils import normalize_time_value, time_seconds_or_none


def write_tabular_recording(frame: pd.DataFrame, request: ConvertRequest) -> None:
    write_tabular_chunks([frame], request)


def write_tabular_chunks(frames: Iterable[pd.DataFrame], request: ConvertRequest) -> None:
    import rerun as rr

    Path(request.output_rrd).parent.mkdir(parents=True, exist_ok=True)
    with rr.RecordingStream(
        request.app_id,
        recording_id=request.recording_id,
        send_properties=False,
    ) as rec:
        rec.save(request.output_rrd)
        rec.send_recording_name(request.recording_id)
        rows = (
            _externally_sorted_rows(frames, request)
            if request.timeline_sort == "ascending"
            else _source_order_rows(frames, request)
        )
        for row_index, row in enumerate(rows):
            _check_cancel(request)
            _set_row_time(
                rec,
                row,
                row_index,
                request.mappings,
                time_key=request.primary_timeline,
                time_unit=request.timeline_unit,
            )
            for mapping in request.mappings:
                _log_mapping(rec, row, mapping)
            if row_index % 1_000 == 0:
                _report_progress(request, "converting", _fraction(row_index, request))


def _source_order_rows(
    frames: Iterable[pd.DataFrame],
    request: ConvertRequest,
) -> Iterable[pd.Series]:
    processed = 0
    for frame in frames:
        _check_cancel(request)
        for _, row in frame.iterrows():
            processed += 1
            yield row
        _report_progress(request, "converting", _fraction(processed, request))


def _externally_sorted_rows(
    frames: Iterable[pd.DataFrame],
    request: ConvertRequest,
) -> Iterable[pd.Series]:
    cache_dir = Path(request.cache_dir or Path(request.output_rrd).parent)
    cache_dir.mkdir(parents=True, exist_ok=True)
    sort_db = cache_dir / "tabular-sort.sqlite"
    sort_db.unlink(missing_ok=True)
    try:
        with sqlite3.connect(sort_db) as conn:
            conn.execute(
                "create table rows (sort_missing integer not null, sort_time real not null, ordinal integer primary key, payload blob not null)"
            )
            ordinal = 0
            for frame in frames:
                _check_cancel(request)
                values = []
                for _, row in frame.iterrows():
                    timestamp = (
                        time_seconds_or_none(row[request.primary_timeline], unit=request.timeline_unit)
                        if request.primary_timeline
                        and request.primary_timeline in row
                        and pd.notna(row[request.primary_timeline])
                        else None
                    )
                    values.append(
                        (
                            int(timestamp is None),
                            float(timestamp or 0.0),
                            ordinal,
                            sqlite3.Binary(pickle.dumps(row.to_dict(), protocol=pickle.HIGHEST_PROTOCOL)),
                        )
                    )
                    ordinal += 1
                conn.executemany(
                    "insert into rows (sort_missing, sort_time, ordinal, payload) values (?, ?, ?, ?)",
                    values,
                )
                conn.commit()
                _report_progress(request, "sorting", _fraction(ordinal, request) * 0.5)
            cursor = conn.execute(
                "select payload from rows order by sort_missing, sort_time, ordinal"
            )
            for index, (payload,) in enumerate(cursor):
                _check_cancel(request)
                if index % 1_000 == 0:
                    _report_progress(
                        request,
                        "converting",
                        0.5 + (_fraction(index, request) * 0.5),
                    )
                yield pd.Series(pickle.loads(payload))
    finally:
        sort_db.unlink(missing_ok=True)


def _fraction(processed: int, request: ConvertRequest) -> float:
    total = int(request.source.metadata.get("rows") or 0)
    if total <= 0:
        return 0.0
    return min(max(processed / total, 0.0), 1.0)


def _report_progress(request: ConvertRequest, stage: str, progress: float) -> None:
    if request.progress_callback is not None:
        request.progress_callback(stage, min(max(progress, 0.0), 1.0))


def _check_cancel(request: ConvertRequest) -> None:
    if request.cancel_check is not None:
        request.cancel_check()


def _set_row_time(
    rec: Any,
    row: pd.Series,
    row_index: int,
    mappings: list[dict[str, Any]],
    *,
    time_key: str | None = None,
    time_unit: str = "auto",
) -> None:
    rec.set_time("row", sequence=int(row_index))
    time_key = time_key or _primary_time_key(mappings)
    if time_key and time_key in row and pd.notna(row[time_key]):
        normalized = normalize_time_value(row[time_key], unit=time_unit)
        if (
            normalized is not None
            and normalized.kind == "timestamp"
            and normalized.timestamp is not None
        ):
            rec.set_time("time", timestamp=normalized.timestamp)
            return
        if normalized is not None:
            rec.set_time("time", duration=normalized.seconds)
            return
    disable_timeline = getattr(rec, "disable_timeline", None)
    if callable(disable_timeline):
        disable_timeline("time")


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
    if not mapping.get("enabled", True) or not entity_path or not fields:
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
            state_change = getattr(rr, "StateChange", None)
            archetype = (
                state_change(state=str(value))
                if state_change is not None
                else rr.TextLog(str(value))
            )
            rec.log(entity_path, archetype)
    elif semantic_type == "text_log":
        message = _message_from_fields(row, fields)
        if message:
            rec.log(entity_path, rr.TextLog(message, level=_log_level(row, fields)))
    elif semantic_type == "points2d":
        values = _coordinate_values(row, fields, ("x", "y"))
        if values is not None:
            rec.log(entity_path, rr.Points2D([values]))
    elif semantic_type == "points3d":
        values = _coordinate_values(row, fields, ("x", "y", "z"))
        if values is not None:
            rec.log(entity_path, rr.Points3D([values]))
    elif semantic_type == "trajectory3d":
        values = _coordinate_values(row, fields, ("x", "y", "z"))
        if values is not None:
            rec.log(entity_path, rr.LineStrips3D([[values]]))
    elif semantic_type == "boxes2d":
        xywh = _box_values(row, fields)
        if xywh is not None:
            rec.log(entity_path, rr.Boxes2D(array=[xywh], array_format=rr.Box2DFormat.XYWH))
    elif semantic_type == "transform3d":
        translation = _coordinate_values(row, fields, ("x", "y", "z"))
        if translation is not None:
            kwargs: dict[str, Any] = {"translation": translation}
            quaternion = _coordinate_values(row, fields, ("qx", "qy", "qz", "qw"))
            if quaternion is not None and hasattr(rr, "Quaternion"):
                kwargs["quaternion"] = rr.Quaternion(xyzw=quaternion)
            rec.log(entity_path, rr.Transform3D(**kwargs))


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


def _coordinate_values(
    row: pd.Series,
    fields: list[str],
    roles: tuple[str, ...],
) -> list[float] | None:
    role_fields = {_field_role(field): field for field in fields}
    values = []
    for role in roles:
        field = role_fields.get(role)
        if field is None or field not in row or pd.isna(row[field]):
            return None
        values.append(float(row[field]))
    return values


def _box_values(row: pd.Series, fields: list[str]) -> list[float] | None:
    xywh = _coordinate_values(row, fields, ("x", "y", "w", "h"))
    if xywh is not None:
        return xywh
    xyxy = _coordinate_values(row, fields, ("xmin", "ymin", "xmax", "ymax"))
    if xyxy is None:
        return None
    xmin, ymin, xmax, ymax = xyxy
    return [xmin, ymin, xmax - xmin, ymax - ymin]


def _field_role(field: str) -> str:
    token = (
        field.lower()
        .replace("/", ".")
        .replace("-", ".")
        .replace("_", ".")
        .split(".")[-1]
    )
    if token == "width":
        return "w"
    if token == "height":
        return "h"
    if "quat" in field.lower() and token[-1:] in {"x", "y", "z", "w"}:
        return f"q{token[-1]}"
    return token
