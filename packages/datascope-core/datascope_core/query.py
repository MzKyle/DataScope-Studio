from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from datascope_core.adapters.jsonl_adapter import _read_jsonl
from datascope_core.adapters.point_cloud_adapter import (
    _cloud_time,
    _read_point_cloud_stats,
    supported_point_cloud_paths,
)
from datascope_core.cv_schema import load_annotations, load_predictions, sidecar_frame_map, supported_image_paths
from datascope_core.models import MappingSpec, SourceInfo


QUERY_TEMPLATES = [
    {
        "template_id": "find_errors",
        "name": "Find Errors",
        "description": "Find ERROR/WARN/fault/error values in logs and states.",
        "params": {},
    },
    {
        "template_id": "low_battery",
        "name": "Low Battery",
        "description": "Find battery scalar samples below a threshold.",
        "params": {"threshold": 0.2},
    },
    {
        "template_id": "detection_failure",
        "name": "Detection Failure",
        "description": "Find low-confidence or missing CV predictions.",
        "params": {"threshold": 0.5},
    },
    {
        "template_id": "topic_summary",
        "name": "Topic Summary",
        "description": "Summarize MCAP topics by semantic role and message count.",
        "params": {},
    },
    {
        "template_id": "state_duration",
        "name": "State Duration",
        "description": "Estimate state duration from adjacent timestamped state samples.",
        "params": {},
    },
    {
        "template_id": "time_sync",
        "name": "Time Sync",
        "description": "Compare timestamp ranges across MCAP topics and sensor streams.",
        "params": {},
    },
]


QUERY_COLUMNS = ["recording_id", "time", "entity_path", "key", "value"]


@dataclass(slots=True)
class QueryRow:
    recording_id: str
    source_id: str
    time: float | None
    entity_path: str
    semantic_type: str
    key: str
    value: Any

    def db_tuple(self) -> tuple[Any, ...]:
        return (
            self.recording_id,
            self.source_id,
            self.time,
            self.entity_path,
            self.semantic_type,
            self.key,
            json.dumps(self.value, ensure_ascii=False),
        )


def build_query_rows(recording_id: str, source: SourceInfo, spec: MappingSpec) -> list[QueryRow]:
    if source.source_type == "csv":
        frame = pd.read_csv(source.path)
        return _tabular_rows(recording_id, source, spec, frame)
    if source.source_type == "jsonl":
        frame = pd.DataFrame(_read_jsonl(source.path, limit=None))
        return _tabular_rows(recording_id, source, spec, frame)
    if source.source_type == "image_folder":
        return _cv_rows(recording_id, source)
    if source.source_type == "mcap":
        return _mcap_rows(recording_id, source)
    if source.source_type == "point_cloud":
        return _point_cloud_rows(recording_id, source)
    return []


def run_query_template(
    rows: list[dict[str, Any]],
    template_id: str,
    recording_ids: list[str] | None,
    params: dict[str, Any] | None,
    limit: int,
) -> dict[str, Any]:
    selected = [
        row
        for row in rows
        if not recording_ids or row["recording_id"] in set(recording_ids)
    ]
    params = params or {}

    if template_id == "find_errors":
        result = _find_errors(selected)
    elif template_id == "low_battery":
        result = _low_battery(selected, float(params.get("threshold", 0.2)))
    elif template_id == "detection_failure":
        result = _detection_failure(selected, float(params.get("threshold", 0.5)))
    elif template_id == "topic_summary":
        result = _topic_summary(selected)
    elif template_id == "state_duration":
        result = _state_duration(selected)
    elif template_id == "time_sync":
        result = _time_sync(selected)
    else:
        raise ValueError(f"Unsupported query template: {template_id}")

    return {"columns": QUERY_COLUMNS, "rows": result[:limit]}


def compare_recordings(
    rows: list[dict[str, Any]],
    recording_ids: list[str],
    metric_keys: list[str] | None = None,
    mode: str = "summary",
    limit: int = 1000,
) -> dict[str, Any]:
    selected_ids = set(recording_ids)
    metric_filters = [item.lower() for item in metric_keys or [] if item]
    candidates = []
    for row in rows:
        if selected_ids and row["recording_id"] not in selected_ids:
            continue
        if row["semantic_type"] not in {"scalar", "scalar_group", "state"}:
            continue
        value = _db_value(row)
        if row["semantic_type"] != "state" and not isinstance(value, (int, float)):
            continue
        searchable = f"{row['key']} {row['entity_path']}".lower()
        if metric_filters and not any(token in searchable for token in metric_filters):
            continue
        candidates.append(row)

    if mode == "series":
        return {"columns": QUERY_COLUMNS, "rows": [_result_row(row) for row in candidates[:limit]]}
    if mode != "summary":
        raise ValueError(f"Unsupported compare mode: {mode}")

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in candidates:
        grouped.setdefault((row["recording_id"], row["entity_path"], row["key"]), []).append(row)

    result = []
    for (recording_id, entity_path, key), group_rows in sorted(grouped.items()):
        values = [_db_value(row) for row in group_rows]
        numeric_values = [float(value) for value in values if isinstance(value, (int, float))]
        latest = values[-1] if values else None
        if numeric_values:
            summary_value: Any = {
                "count": len(numeric_values),
                "min": min(numeric_values),
                "max": max(numeric_values),
                "mean": sum(numeric_values) / len(numeric_values),
                "latest": latest,
            }
        else:
            state_counts: dict[str, int] = {}
            for value in values:
                state_counts[str(value)] = state_counts.get(str(value), 0) + 1
            summary_value = {"count": len(values), "states": state_counts, "latest": latest}
        result.append(
            {
                "recording_id": recording_id,
                "time": None,
                "entity_path": entity_path,
                "key": key,
                "value": summary_value,
            }
        )
    return {"columns": QUERY_COLUMNS, "rows": result[:limit]}


def export_query_result(result: dict[str, Any], path: str | Path, fmt: str) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = fmt.lower()
    if fmt == "csv":
        with open(output_path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=result["columns"])
            writer.writeheader()
            writer.writerows(result["rows"])
        return
    if fmt == "parquet":
        try:
            import pyarrow  # noqa: F401
        except Exception as exc:
            raise RuntimeError("Parquet export requires pyarrow to be installed") from exc
        pd.DataFrame(result["rows"], columns=result["columns"]).to_parquet(output_path, index=False)
        return
    raise ValueError(f"Unsupported export format: {fmt}")


def _tabular_rows(
    recording_id: str,
    source: SourceInfo,
    spec: MappingSpec,
    frame: pd.DataFrame,
) -> list[QueryRow]:
    rows: list[QueryRow] = []
    for row_index, row in frame.iterrows():
        timestamp = _row_time(row, spec.primary_timeline, row_index)
        for mapping in spec.streams:
            fields = mapping.get("source_fields", [])
            entity_path = mapping.get("entity_path", "")
            semantic_type = mapping.get("semantic_type", "")
            if semantic_type == "scalar":
                _append_field_values(rows, recording_id, source.source_id, timestamp, entity_path, semantic_type, row, fields)
            elif semantic_type == "scalar_group":
                for field in fields:
                    if field in row and pd.notna(row[field]):
                        rows.append(QueryRow(recording_id, source.source_id, timestamp, f"{entity_path}/{field}", semantic_type, field, _json_value(row[field])))
            elif semantic_type in {"state", "text_log"}:
                _append_field_values(rows, recording_id, source.source_id, timestamp, entity_path, semantic_type, row, fields)
                if semantic_type == "text_log":
                    message = " ".join(
                        f"{field}={row[field]}" for field in fields if field in row and pd.notna(row[field])
                    )
                    if message:
                        rows.append(QueryRow(recording_id, source.source_id, timestamp, entity_path, semantic_type, "message", message))
    return rows


def _cv_rows(recording_id: str, source: SourceInfo) -> list[QueryRow]:
    root = Path(source.path)
    images = supported_image_paths(root)
    annotations = load_annotations(root)
    predictions = load_predictions(root)
    annotation_map = sidecar_frame_map(root, annotations)
    prediction_map = sidecar_frame_map(root, predictions)
    rows: list[QueryRow] = []

    for index, image in enumerate(images):
        key = str(image.resolve())
        annotation_frame = annotation_map.get(key)
        prediction_frame = prediction_map.get(key)
        timestamp = _first_time(index, annotation_frame, prediction_frame)
        rows.append(QueryRow(recording_id, source.source_id, timestamp, "/camera/image", "image", "image", str(image.relative_to(root))))
        rows.append(QueryRow(recording_id, source.source_id, timestamp, "/camera/gt/boxes", "boxes2d", "gt_box_count", len(annotation_frame.boxes) if annotation_frame else 0))
        pred_count = len(prediction_frame.boxes) if prediction_frame else 0
        rows.append(QueryRow(recording_id, source.source_id, timestamp, "/camera/pred/boxes", "boxes2d", "pred_box_count", pred_count))
        rows.append(QueryRow(recording_id, source.source_id, timestamp, "/camera/gt/keypoints", "points2d", "gt_keypoint_count", _keypoint_count(annotation_frame)))
        rows.append(QueryRow(recording_id, source.source_id, timestamp, "/camera/pred/keypoints", "points2d", "pred_keypoint_count", _keypoint_count(prediction_frame)))
        rows.append(QueryRow(recording_id, source.source_id, timestamp, "/camera/gt/masks", "segmentation", "gt_mask_count", len(annotation_frame.masks) if annotation_frame else 0))
        rows.append(QueryRow(recording_id, source.source_id, timestamp, "/camera/pred/masks", "segmentation", "pred_mask_count", len(prediction_frame.masks) if prediction_frame else 0))
        scores = [box.score for box in prediction_frame.boxes if box.score is not None] if prediction_frame else []
        if prediction_frame:
            scores.extend(item.score for item in prediction_frame.keypoints if item.score is not None)
            scores.extend(item.score for item in prediction_frame.masks if item.score is not None)
        if scores:
            rows.append(QueryRow(recording_id, source.source_id, timestamp, "/camera/pred/scores", "scalar", "score_min", min(scores)))
            rows.append(QueryRow(recording_id, source.source_id, timestamp, "/camera/pred/scores", "scalar", "score_mean", sum(scores) / len(scores)))
        labels = [box.label for box in prediction_frame.boxes if box.label] if prediction_frame else []
        if labels:
            rows.append(QueryRow(recording_id, source.source_id, timestamp, "/camera/pred/boxes", "boxes2d", "labels", labels))
    return rows


def _mcap_rows(recording_id: str, source: SourceInfo) -> list[QueryRow]:
    rows: list[QueryRow] = []
    for topic in source.metadata.get("topics", []):
        topic_name = topic.get("topic", "")
        entity_path = f"/topics/{topic_name.strip('/').replace('/', '_') or 'topic'}"
        value = {
            "topic": topic_name,
            "role": topic.get("role") or _role_from_topic(topic_name, topic.get("schema_name", "")),
            "schema_name": topic.get("schema_name", ""),
            "message_encoding": topic.get("message_encoding", ""),
            "message_count": topic.get("message_count", 0),
            "start_time": topic.get("message_start_time", source.metadata.get("message_start_time")),
            "end_time": topic.get("message_end_time", source.metadata.get("message_end_time")),
        }
        rows.append(QueryRow(recording_id, source.source_id, None, entity_path, "mcap", "topic_summary", value))
        rows.append(QueryRow(recording_id, source.source_id, None, entity_path, "mcap", "message_count", value["message_count"]))
    return rows


def _point_cloud_rows(recording_id: str, source: SourceInfo) -> list[QueryRow]:
    root = Path(source.path)
    clouds = supported_point_cloud_paths(root)
    rows: list[QueryRow] = []
    for index, cloud in enumerate(clouds):
        timestamp = _cloud_time(index, cloud)
        stats = _read_point_cloud_stats(cloud, include_bounds=False)
        file_value = str(cloud.relative_to(root)) if root.is_dir() else cloud.name
        rows.append(QueryRow(recording_id, source.source_id, timestamp, "/sensors/lidar/points", "points3d", "file", file_value))
        rows.append(QueryRow(recording_id, source.source_id, timestamp, "/sensors/lidar/points", "points3d", "point_count", stats.point_count))
        rows.append(QueryRow(recording_id, source.source_id, timestamp, "/sensors/lidar/points", "points3d", "format", stats.file_format))
    return rows


def _append_field_values(
    rows: list[QueryRow],
    recording_id: str,
    source_id: str,
    timestamp: float | None,
    entity_path: str,
    semantic_type: str,
    row: pd.Series,
    fields: list[str],
) -> None:
    for field in fields:
        if field in row and pd.notna(row[field]):
            rows.append(QueryRow(recording_id, source_id, timestamp, entity_path, semantic_type, field, _json_value(row[field])))


def _row_time(row: pd.Series, time_key: str, row_index: int) -> float:
    if time_key in row and pd.notna(row[time_key]):
        numeric = pd.to_numeric(pd.Series([row[time_key]]), errors="coerce").iloc[0]
        if pd.notna(numeric):
            return float(numeric)
    return float(row_index)


def _first_time(index: int, *frames: Any) -> float:
    for frame in frames:
        if frame is not None and frame.time is not None:
            return float(frame.time)
    return float(index)


def _json_value(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    return value


def _db_value(row: dict[str, Any]) -> Any:
    return json.loads(row["value_json"])


def _result_row(row: dict[str, Any], value: Any | None = None) -> dict[str, Any]:
    return {
        "recording_id": row["recording_id"],
        "time": row["time"],
        "entity_path": row["entity_path"],
        "key": row["key"],
        "value": _db_value(row) if value is None else value,
    }


def _find_errors(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    needles = ("error", "warn", "fault")
    result = []
    for row in rows:
        if row["semantic_type"] not in {"text_log", "state"}:
            continue
        text = str(_db_value(row)).lower()
        if any(needle in text for needle in needles):
            result.append(_result_row(row))
    return result


def _low_battery(rows: list[dict[str, Any]], threshold: float) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        key_text = f"{row['key']} {row['entity_path']}".lower()
        if "battery" not in key_text:
            continue
        value = _db_value(row)
        if isinstance(value, (int, float)) and value < threshold:
            result.append(_result_row(row))
    return result


def _detection_failure(rows: list[dict[str, Any]], threshold: float) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        if "/camera/pred" not in row["entity_path"]:
            continue
        value = _db_value(row)
        if row["key"] == "pred_box_count" and value == 0:
            result.append(_result_row(row, {"reason": "no_prediction", "value": value}))
        elif row["key"] in {"score_min", "score_mean"} and isinstance(value, (int, float)) and value < threshold:
            result.append(_result_row(row, {"reason": "low_score", "value": value}))
    return result


def _keypoint_count(frame: Any) -> int:
    if frame is None:
        return 0
    return sum(len(item.points) for item in frame.keypoints)


def _topic_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_result_row(row) for row in rows if row["key"] == "topic_summary"]


def _state_duration(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    states = [row for row in rows if row["semantic_type"] == "state" and row["time"] is not None]
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in states:
        grouped.setdefault((row["recording_id"], row["entity_path"], row["key"]), []).append(row)

    result: list[dict[str, Any]] = []
    for group_rows in grouped.values():
        ordered = sorted(group_rows, key=lambda item: float(item["time"]))
        for index, row in enumerate(ordered):
            next_time = ordered[index + 1]["time"] if index + 1 < len(ordered) else row["time"]
            duration = max(float(next_time) - float(row["time"]), 0.0)
            result.append(_result_row(row, {"state": _db_value(row), "duration": duration}))
    return result


def _time_sync(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    topics = [row for row in rows if row["key"] == "topic_summary"]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in topics:
        grouped.setdefault(row["recording_id"], []).append(row)

    result: list[dict[str, Any]] = []
    for recording_id, topic_rows in grouped.items():
        values = [_db_value(row) for row in topic_rows]
        timed = [
            value
            for value in values
            if isinstance(value.get("start_time"), (int, float))
            and isinstance(value.get("end_time"), (int, float))
        ]
        if not timed:
            for row in topic_rows:
                result.append(_result_row(row, {"reason": "missing_topic_time_range", "topic": _db_value(row).get("topic")}))
            continue
        base = timed[0]
        base_start = float(base["start_time"])
        base_end = float(base["end_time"])
        for value in timed[1:]:
            result.append(
                {
                    "recording_id": recording_id,
                    "time": None,
                    "entity_path": "/time_sync",
                    "key": "time_delta",
                    "value": {
                        "base_topic": base.get("topic"),
                        "topic": value.get("topic"),
                        "start_delta": float(value["start_time"]) - base_start,
                        "end_delta": float(value["end_time"]) - base_end,
                        "role": value.get("role"),
                    },
                }
            )
    return result


def _role_from_topic(topic: str, schema_name: str) -> str:
    from datascope_core.adapters.mcap_adapter import classify_topic

    return classify_topic(topic, schema_name)[0]
