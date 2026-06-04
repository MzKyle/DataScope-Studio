from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from datascope_core.inference import safe_slug
from datascope_core.models import MappingSpec, SourceInfo, StreamInfo


ARCHETYPES = {
    "scalar": "Scalars",
    "scalar_group": "Scalars",
    "state": "StateChange",
    "text_log": "TextLog",
    "image": "EncodedImage",
    "boxes2d": "Boxes2D",
    "points2d": "Points2D",
    "segmentation": "SegmentationImage",
    "points3d": "Points3D",
    "asset3d": "Asset3D",
    "transform3d": "Transform3D",
    "trajectory3d": "LineStrips3D",
    "mcap": "AnyValues",
}

TEMPLATE_APP_IDS = {
    "sensor_monitor": "datascope.sensor_monitor.v1",
    "cv_detection": "datascope.cv_detection.v1",
    "robotics_debug": "datascope.robotics_debug.v1",
    "experiment_compare": "datascope.experiment_compare.v1",
}


def suggest_mapping(
    source: SourceInfo,
    streams: list[StreamInfo],
    *,
    mapping_id: str | None = None,
    recording_id: str | None = None,
    app_id: str | None = None,
    template_id: str | None = None,
) -> MappingSpec:
    primary_timeline = next((stream.time_key for stream in streams if stream.time_key), "time") or "time"
    resolved_template_id = template_id or _template_for_streams(streams)
    return MappingSpec(
        mapping_id=mapping_id or f"mapping_{uuid4().hex[:12]}",
        source_id=source.source_id,
        app_id=app_id or TEMPLATE_APP_IDS[resolved_template_id],
        recording_id=recording_id or f"recording_{uuid4().hex[:12]}",
        primary_timeline=primary_timeline,
        streams=[_stream_mapping(stream) for stream in streams],
    )


def mapping_to_yaml_dict(spec: MappingSpec) -> dict[str, Any]:
    return {
        "mapping": {
            "id": spec.mapping_id,
            "source": spec.source_id,
            "app_id": spec.app_id,
            "recording_id": spec.recording_id,
            "timelines": {
                "primary": {
                    "name": spec.primary_timeline,
                    "source_field": spec.primary_timeline,
                    "unit": "seconds",
                }
            },
            "streams": spec.streams,
        }
    }


def mapping_from_yaml_dict(data: dict[str, Any]) -> MappingSpec:
    mapping = data["mapping"]
    primary = mapping.get("timelines", {}).get("primary", {})
    return MappingSpec(
        mapping_id=mapping["id"],
        source_id=mapping["source"],
        app_id=mapping.get("app_id", "datascope.sensor_monitor.v1"),
        recording_id=mapping.get("recording_id", f"recording_{uuid4().hex[:12]}"),
        primary_timeline=primary.get("source_field") or primary.get("name") or "time",
        streams=mapping.get("streams", []),
    )


def save_mapping_yaml(spec: MappingSpec, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(mapping_to_yaml_dict(spec), handle, sort_keys=False, allow_unicode=True)


def load_mapping_yaml(path: str | Path) -> MappingSpec:
    with open(path, "r", encoding="utf-8") as handle:
        return mapping_from_yaml_dict(yaml.safe_load(handle))


def _stream_mapping(stream: StreamInfo) -> dict[str, Any]:
    semantic_type = stream.semantic_type
    fields = stream.fields
    mapping = {
        "stream_id": stream.stream_id,
        "source_fields": fields,
        "semantic_type": semantic_type,
        "entity_path": _entity_path(stream),
        "archetype": ARCHETYPES.get(semantic_type, "AnyValues"),
        "view": _view_for_semantic_type(semantic_type),
        "confidence": round(stream.confidence, 3),
    }
    if stream.metadata.get("role"):
        mapping["role"] = stream.metadata["role"]
    return mapping


def _entity_path(stream: StreamInfo) -> str:
    name = safe_slug(stream.name)
    role = stream.metadata.get("role")
    if stream.semantic_type == "image":
        if role == "camera_image":
            return "/sensors/camera/image"
        return "/camera/image"
    if stream.semantic_type == "points3d":
        return "/sensors/lidar/points"
    if stream.semantic_type == "transform3d":
        return "/world/tf"
    if stream.semantic_type == "trajectory3d":
        return "/world/trajectory"
    if stream.semantic_type == "mcap":
        return f"/topics/{name}"
    if stream.semantic_type == "boxes2d" and role == "gt":
        return "/camera/gt/boxes"
    if stream.semantic_type == "boxes2d" and role == "pred":
        return "/camera/pred/boxes"
    if stream.semantic_type == "points2d" and role == "gt_keypoints":
        return "/camera/gt/keypoints"
    if stream.semantic_type == "points2d" and role == "pred_keypoints":
        return "/camera/pred/keypoints"
    if stream.semantic_type == "segmentation" and role == "gt_masks":
        return "/camera/gt/masks"
    if stream.semantic_type == "segmentation" and role == "pred_masks":
        return "/camera/pred/masks"
    if stream.semantic_type == "scalar" and role == "pred_scores":
        return "/camera/pred/scores"
    if stream.semantic_type == "asset3d" or role == "robot_model":
        return "/world/robot_model"
    if stream.semantic_type in {"scalar", "scalar_group"}:
        return f"/metrics/{name}"
    if stream.semantic_type == "state":
        return f"/states/{name}"
    if stream.semantic_type == "text_log":
        return f"/logs/{name}"
    return f"/tables/{name}"


def _view_for_semantic_type(semantic_type: str) -> str:
    if semantic_type in {"image", "boxes2d", "points2d", "segmentation"}:
        return "Spatial2DView"
    if semantic_type in {"points3d", "transform3d", "trajectory3d"}:
        return "Spatial3DView"
    if semantic_type in {"scalar", "scalar_group"}:
        return "TimeSeriesView"
    if semantic_type == "state":
        return "StateTimelineView"
    if semantic_type == "text_log":
        return "TextLogView"
    return "DataframeView"


def _template_for_streams(streams: list[StreamInfo]) -> str:
    semantic_types = {stream.semantic_type for stream in streams}
    if "mcap" in semantic_types or any(stream.metadata.get("message_encoding") for stream in streams):
        return "robotics_debug"
    if semantic_types & {"points3d", "transform3d", "trajectory3d", "asset3d"}:
        return "robotics_debug"
    if "image" in semantic_types:
        return "cv_detection"
    return "sensor_monitor"
