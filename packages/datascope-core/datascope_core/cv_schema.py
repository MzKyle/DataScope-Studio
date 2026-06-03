from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from datascope_core.models import IMAGE_EXTENSIONS


SIDECAR_NAMES = ("annotations.json", "predictions.json")


@dataclass(slots=True)
class CvClass:
    id: int
    label: str | None = None
    color: tuple[int, int, int] | None = None


@dataclass(slots=True)
class CvBox:
    bbox: list[float]
    class_id: int | None = None
    label: str | None = None
    score: float | None = None


@dataclass(slots=True)
class CvKeypoints:
    points: list[list[float]]
    class_id: int | None = None
    label: str | None = None
    score: float | None = None


@dataclass(slots=True)
class CvMask:
    path: str
    class_id: int | None = None
    label: str | None = None
    score: float | None = None


@dataclass(slots=True)
class CvFrame:
    image: str
    time: float | None = None
    boxes: list[CvBox] = field(default_factory=list)
    keypoints: list[CvKeypoints] = field(default_factory=list)
    masks: list[CvMask] = field(default_factory=list)


@dataclass(slots=True)
class CvSidecar:
    path: Path
    kind: str
    classes: list[CvClass]
    frames: list[CvFrame]


def supported_image_paths(root: str | Path) -> list[Path]:
    root_path = Path(root)
    return sorted(
        child
        for child in root_path.rglob("*")
        if child.is_file() and child.suffix.lower() in IMAGE_EXTENSIONS
    )


def find_sidecar(root: str | Path, name: str) -> Path | None:
    root_path = Path(root)
    for candidate in (root_path / name, root_path.parent / name):
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def load_sidecar(root: str | Path, name: str) -> CvSidecar | None:
    sidecar_path = find_sidecar(root, name)
    if sidecar_path is None:
        return None
    with open(sidecar_path, "r", encoding="utf-8") as handle:
        try:
            payload = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid {name}: {exc}") from exc
    return parse_cv_sidecar(payload, sidecar_path, "predictions" if name == "predictions.json" else "annotations")


def parse_cv_sidecar(payload: dict[str, Any], path: str | Path, kind: str) -> CvSidecar:
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    classes = [_parse_class(item, path) for item in payload.get("classes", [])]
    frames_payload = payload.get("frames")
    if not isinstance(frames_payload, list):
        raise ValueError(f"{path} must contain a frames array")
    frames = [_parse_frame(item, path, index) for index, item in enumerate(frames_payload)]
    return CvSidecar(path=Path(path), kind=kind, classes=classes, frames=frames)


def resolve_image_path(root: str | Path, frame_image: str) -> Path:
    root_path = Path(root)
    candidate = Path(frame_image)
    if candidate.is_absolute():
        return candidate
    candidates = [
        root_path / candidate,
        root_path.parent / candidate,
        root_path / candidate.name,
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def sidecar_frame_map(root: str | Path, sidecar: CvSidecar | None) -> dict[str, CvFrame]:
    if sidecar is None:
        return {}
    return {
        str(resolve_image_path(root, frame.image).resolve()): frame
        for frame in sidecar.frames
    }


def merge_classes(*sidecars: CvSidecar | None) -> list[CvClass]:
    merged: dict[int, CvClass] = {}
    for sidecar in sidecars:
        if sidecar is None:
            continue
        for class_info in sidecar.classes:
            merged[class_info.id] = class_info
    return [merged[key] for key in sorted(merged)]


def _parse_class(item: Any, path: str | Path) -> CvClass:
    if not isinstance(item, dict):
        raise ValueError(f"{path} class entries must be objects")
    if "id" not in item:
        raise ValueError(f"{path} class entries require id")
    color = item.get("color")
    parsed_color = None
    if color is not None:
        if (
            not isinstance(color, list)
            or len(color) != 3
            or not all(isinstance(channel, int) and 0 <= channel <= 255 for channel in color)
        ):
            raise ValueError(f"{path} class color must be [r, g, b] integers")
        parsed_color = (color[0], color[1], color[2])
    return CvClass(id=int(item["id"]), label=item.get("label"), color=parsed_color)


def _parse_frame(item: Any, path: str | Path, index: int) -> CvFrame:
    if not isinstance(item, dict):
        raise ValueError(f"{path} frames[{index}] must be an object")
    image = item.get("image")
    if not isinstance(image, str) or not image:
        raise ValueError(f"{path} frames[{index}] requires image")
    boxes_payload = item.get("boxes", [])
    if not isinstance(boxes_payload, list):
        raise ValueError(f"{path} frames[{index}].boxes must be an array")
    keypoints_payload = item.get("keypoints", [])
    if not isinstance(keypoints_payload, list):
        raise ValueError(f"{path} frames[{index}].keypoints must be an array")
    masks_payload = item.get("masks", [])
    if not isinstance(masks_payload, list):
        raise ValueError(f"{path} frames[{index}].masks must be an array")
    time = item.get("time")
    return CvFrame(
        image=image,
        time=float(time) if time is not None else None,
        boxes=[_parse_box(box, path, index, box_index) for box_index, box in enumerate(boxes_payload)],
        keypoints=[
            _parse_keypoints(keypoints, path, index, keypoints_index)
            for keypoints_index, keypoints in enumerate(keypoints_payload)
        ],
        masks=[_parse_mask(mask, path, index, mask_index) for mask_index, mask in enumerate(masks_payload)],
    )


def _parse_box(item: Any, path: str | Path, frame_index: int, box_index: int) -> CvBox:
    if not isinstance(item, dict):
        raise ValueError(f"{path} frames[{frame_index}].boxes[{box_index}] must be an object")
    bbox = item.get("bbox")
    if (
        not isinstance(bbox, list)
        or len(bbox) != 4
        or not all(isinstance(value, (int, float)) for value in bbox)
    ):
        raise ValueError(
            f"{path} frames[{frame_index}].boxes[{box_index}].bbox must be [x, y, width, height]"
        )
    score = item.get("score")
    return CvBox(
        bbox=[float(value) for value in bbox],
        class_id=int(item["class_id"]) if item.get("class_id") is not None else None,
        label=item.get("label"),
        score=float(score) if score is not None else None,
    )


def _parse_keypoints(item: Any, path: str | Path, frame_index: int, keypoints_index: int) -> CvKeypoints:
    if not isinstance(item, dict):
        raise ValueError(f"{path} frames[{frame_index}].keypoints[{keypoints_index}] must be an object")
    points = item.get("points")
    if (
        not isinstance(points, list)
        or not points
        or not all(
            isinstance(point, list)
            and len(point) == 2
            and all(isinstance(value, (int, float)) for value in point)
            for point in points
        )
    ):
        raise ValueError(
            f"{path} frames[{frame_index}].keypoints[{keypoints_index}].points must be [[x, y], ...]"
        )
    score = item.get("score")
    return CvKeypoints(
        points=[[float(point[0]), float(point[1])] for point in points],
        class_id=int(item["class_id"]) if item.get("class_id") is not None else None,
        label=item.get("label"),
        score=float(score) if score is not None else None,
    )


def _parse_mask(item: Any, path: str | Path, frame_index: int, mask_index: int) -> CvMask:
    if not isinstance(item, dict):
        raise ValueError(f"{path} frames[{frame_index}].masks[{mask_index}] must be an object")
    mask_path = item.get("path")
    if not isinstance(mask_path, str) or not mask_path:
        raise ValueError(f"{path} frames[{frame_index}].masks[{mask_index}] requires path")
    score = item.get("score")
    return CvMask(
        path=mask_path,
        class_id=int(item["class_id"]) if item.get("class_id") is not None else None,
        label=item.get("label"),
        score=float(score) if score is not None else None,
    )
