from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from statistics import mean
from typing import Any

from PIL import Image

from datascope_core.cv_schema import (
    CvFrame,
    find_sidecar,
    load_annotations,
    load_predictions,
    merge_classes,
    resolve_image_path,
    sidecar_frame_map,
    supported_image_paths,
)
from datascope_core.inference import safe_slug
from datascope_core.models import ConvertRequest, IMAGE_EXTENSIONS, MappingSpec, SourceInfo, StreamInfo


class ImageFolderAdapter:
    adapter_id = "image_folder"
    display_name = "Image Folder"
    supported_extensions = sorted(IMAGE_EXTENSIONS)

    def inspect(self, path: str, source_id: str | None = None) -> SourceInfo:
        root = Path(path)
        images = supported_image_paths(root)
        if not images:
            raise ValueError(f"No supported images found: {path}")

        annotations = load_annotations(root)
        predictions = load_predictions(root)
        classes = merge_classes(annotations, predictions)
        sampled_dimensions = {
            _image_display_path(root, image): _image_dimensions(image)
            for image in images[: min(10, len(images))]
        }
        return SourceInfo(
            source_id=source_id or f"source_{safe_slug(root.name)}",
            source_type="image_folder",
            path=str(root),
            metadata={
                "image_count": len(images),
                "images": [_image_display_path(root, image) for image in images],
                "sidecars": {
                    "annotations": str(find_sidecar(root, "annotations.json") or ""),
                    "predictions": str(find_sidecar(root, "predictions.json") or ""),
                },
                "template_keypoint_sidecars": _template_sidecars(root),
                "annotation_frame_count": len(annotations.frames) if annotations else 0,
                "prediction_frame_count": len(predictions.frames) if predictions else 0,
                "annotation_keypoint_count": _keypoint_count(annotations.frames if annotations else []),
                "prediction_keypoint_count": _keypoint_count(predictions.frames if predictions else []),
                "annotation_mask_count": _mask_count(annotations.frames if annotations else []),
                "prediction_mask_count": _mask_count(predictions.frames if predictions else []),
                "classes": [asdict(item) for item in classes],
                "sampled_dimensions": sampled_dimensions,
                "size_bytes": sum(image.stat().st_size for image in images),
            },
        )

    def infer_streams(self, source: SourceInfo) -> list[StreamInfo]:
        root = Path(source.path)
        annotations = load_annotations(root)
        predictions = load_predictions(root)
        streams = [
            StreamInfo(
                stream_id="stream_camera_image",
                name="camera_image",
                semantic_type="image",
                fields=["image"],
                time_key="time",
                confidence=0.98,
                metadata={"role": "image"},
            )
        ]
        if annotations and any(frame.boxes for frame in annotations.frames):
            streams.append(
                StreamInfo(
                    stream_id="stream_gt_boxes",
                    name="gt_boxes",
                    semantic_type="boxes2d",
                    fields=["annotations.boxes"],
                    time_key="time",
                    confidence=0.94,
                    metadata={"role": "gt"},
                )
            )
        if annotations and any(frame.keypoints for frame in annotations.frames):
            streams.append(
                StreamInfo(
                    stream_id="stream_gt_keypoints",
                    name="gt_keypoints",
                    semantic_type="points2d",
                    fields=["annotations.keypoints"],
                    time_key="time",
                    confidence=0.9,
                    metadata={"role": "gt_keypoints"},
                )
            )
        if annotations and any(frame.masks for frame in annotations.frames):
            streams.append(
                StreamInfo(
                    stream_id="stream_gt_masks",
                    name="gt_masks",
                    semantic_type="segmentation",
                    fields=["annotations.masks"],
                    time_key="time",
                    confidence=0.9,
                    metadata={"role": "gt_masks"},
                )
            )
        if predictions and any(frame.boxes for frame in predictions.frames):
            streams.append(
                StreamInfo(
                    stream_id="stream_pred_boxes",
                    name="pred_boxes",
                    semantic_type="boxes2d",
                    fields=["predictions.boxes"],
                    time_key="time",
                    confidence=0.94,
                    metadata={"role": "pred"},
                )
            )
            if any(box.score is not None for frame in predictions.frames for box in frame.boxes):
                streams.append(
                    StreamInfo(
                        stream_id="stream_pred_scores",
                        name="pred_scores",
                        semantic_type="scalar",
                        fields=["predictions.scores"],
                        time_key="time",
                        confidence=0.86,
                        metadata={"role": "pred_scores"},
                    )
                )
        if predictions and any(frame.keypoints for frame in predictions.frames):
            streams.append(
                StreamInfo(
                    stream_id="stream_pred_keypoints",
                    name="pred_keypoints",
                    semantic_type="points2d",
                    fields=["predictions.keypoints"],
                    time_key="time",
                    confidence=0.9,
                    metadata={"role": "pred_keypoints"},
                )
            )
        if predictions and any(frame.masks for frame in predictions.frames):
            streams.append(
                StreamInfo(
                    stream_id="stream_pred_masks",
                    name="pred_masks",
                    semantic_type="segmentation",
                    fields=["predictions.masks"],
                    time_key="time",
                    confidence=0.9,
                    metadata={"role": "pred_masks"},
                )
            )
        return streams

    def preview(self, source: SourceInfo, stream_id: str, limit: int = 100) -> dict[str, Any]:
        root = Path(source.path)
        images = supported_image_paths(root)
        annotations = load_annotations(root)
        predictions = load_predictions(root)
        annotation_map = sidecar_frame_map(root, annotations)
        prediction_map = sidecar_frame_map(root, predictions)
        rows = []
        for index, image in enumerate(images[:limit]):
            key = str(image.resolve())
            annotation_frame = annotation_map.get(key)
            prediction_frame = prediction_map.get(key)
            rows.append(
                {
                    "image": _image_display_path(root, image),
                    "dimensions": _image_dimensions(image),
                    "annotation_boxes": len(annotation_frame.boxes) if annotation_frame else 0,
                    "prediction_boxes": len(prediction_frame.boxes) if prediction_frame else 0,
                    "annotation_keypoints": _keypoint_count([annotation_frame] if annotation_frame else []),
                    "prediction_keypoints": _keypoint_count([prediction_frame] if prediction_frame else []),
                    "annotation_masks": _mask_count([annotation_frame] if annotation_frame else []),
                    "prediction_masks": _mask_count([prediction_frame] if prediction_frame else []),
                    "labels": _labels(annotation_frame, prediction_frame),
                    "scores": _scores(prediction_frame),
                }
            )
        return {
            "source_id": source.source_id,
            "stream_id": stream_id,
            "columns": [
                "image",
                "dimensions",
                "annotation_boxes",
                "prediction_boxes",
                "annotation_keypoints",
                "prediction_keypoints",
                "annotation_masks",
                "prediction_masks",
                "labels",
                "scores",
            ],
            "rows": rows,
        }

    def convert(self, request: ConvertRequest) -> None:
        import rerun as rr

        root = Path(request.source.path)
        images = supported_image_paths(root)
        annotations = load_annotations(root)
        predictions = load_predictions(root)
        annotation_map = sidecar_frame_map(root, annotations)
        prediction_map = sidecar_frame_map(root, predictions)
        classes = merge_classes(annotations, predictions)

        image_path = _entity_path(request.mappings, "image", "/camera/image")
        gt_boxes_path = _entity_path(request.mappings, "gt", "/camera/gt/boxes")
        pred_boxes_path = _entity_path(request.mappings, "pred", "/camera/pred/boxes")
        pred_scores_path = _entity_path(request.mappings, "pred_scores", "/camera/pred/scores")
        gt_keypoints_path = _entity_path(request.mappings, "gt_keypoints", "/camera/gt/keypoints")
        pred_keypoints_path = _entity_path(request.mappings, "pred_keypoints", "/camera/pred/keypoints")
        gt_masks_path = _entity_path(request.mappings, "gt_masks", "/camera/gt/masks")
        pred_masks_path = _entity_path(request.mappings, "pred_masks", "/camera/pred/masks")

        Path(request.output_rrd).parent.mkdir(parents=True, exist_ok=True)
        with rr.RecordingStream(
            request.app_id,
            recording_id=request.recording_id,
            send_properties=False,
        ) as rec:
            rec.save(request.output_rrd)
            rec.send_recording_name(request.recording_id)
            if classes:
                rec.log("/camera", rr.AnnotationContext(_annotation_context(classes)), static=True)

            for index, image in enumerate(images):
                if request.cancel_check is not None:
                    request.cancel_check()
                key = str(image.resolve())
                annotation_frame = annotation_map.get(key)
                prediction_frame = prediction_map.get(key)
                rec.set_time("time", duration=_frame_time(index, annotation_frame, prediction_frame))
                rec.log(image_path, _image_archetype(image))
                if annotation_frame and annotation_frame.boxes:
                    rec.log(gt_boxes_path, _boxes2d(annotation_frame.boxes))
                if annotation_frame and annotation_frame.keypoints:
                    rec.log(gt_keypoints_path, _points2d(annotation_frame.keypoints))
                if annotation_frame and annotation_frame.masks:
                    for mask_index, mask in enumerate(annotation_frame.masks):
                        rec.log(f"{gt_masks_path}/{mask_index}", _segmentation_image(root, mask.path))
                if prediction_frame and prediction_frame.boxes:
                    rec.log(pred_boxes_path, _boxes2d(prediction_frame.boxes))
                    scores = [box.score for box in prediction_frame.boxes if box.score is not None]
                    if scores:
                        rec.log(pred_scores_path, rr.Scalars(mean(scores)))
                if prediction_frame and prediction_frame.keypoints:
                    rec.log(pred_keypoints_path, _points2d(prediction_frame.keypoints))
                if prediction_frame and prediction_frame.masks:
                    for mask_index, mask in enumerate(prediction_frame.masks):
                        rec.log(f"{pred_masks_path}/{mask_index}", _segmentation_image(root, mask.path))
                if request.progress_callback is not None:
                    request.progress_callback(
                        "converting",
                        (index + 1) / max(len(images), 1),
                    )

    def validate_mapping(
        self,
        source: SourceInfo,
        spec: MappingSpec,
        profile: dict[str, Any],
    ) -> list[dict[str, Any]]:
        enabled_types = {
            stream.get("semantic_type")
            for stream in spec.streams
            if stream.get("enabled", True)
        }
        if "image" in enabled_types:
            return []
        return [
            {
                "severity": "error",
                "code": "image_stream_required",
                "message": "Image folder mappings require an enabled image stream.",
                "stream_id": None,
                "rule_key": None,
                "field": "image",
            }
        ]


def _image_dimensions(path: Path) -> dict[str, int]:
    with Image.open(path) as image:
        return {"width": image.width, "height": image.height}


def _image_display_path(root: Path, image: Path) -> str:
    if root.is_file():
        return image.name
    return str(image.relative_to(root))


def _template_sidecars(root: Path) -> list[str]:
    if root.is_file():
        return [
            sidecar.name
            for sidecar in sorted(root.parent.glob(f"{root.stem}_template.json"))
        ]
    return [str(sidecar.relative_to(root)) for sidecar in sorted(root.rglob("*_template.json"))]


def _image_archetype(path: Path):
    import numpy as np
    import rerun as rr

    if path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
        return rr.EncodedImage(path=path)
    with Image.open(path) as image:
        try:
            image.seek(0)
        except EOFError:
            pass
        return rr.Image(np.asarray(image.convert("RGBA")))


def _labels(*frames: CvFrame | None) -> list[str]:
    labels: list[str] = []
    for frame in frames:
        if frame is None:
            continue
        labels.extend(box.label for box in frame.boxes if box.label)
    return labels


def _scores(frame: CvFrame | None) -> list[float]:
    if frame is None:
        return []
    scores = [box.score for box in frame.boxes if box.score is not None]
    scores.extend(keypoints.score for keypoints in frame.keypoints if keypoints.score is not None)
    scores.extend(mask.score for mask in frame.masks if mask.score is not None)
    return scores


def _keypoint_count(frames) -> int:
    return sum(len(item.points) for frame in frames if frame is not None for item in frame.keypoints)


def _mask_count(frames) -> int:
    return sum(len(frame.masks) for frame in frames if frame is not None)


def _frame_time(index: int, *frames: CvFrame | None) -> float:
    for frame in frames:
        if frame is not None and frame.time is not None:
            return frame.time
    return float(index)


def _entity_path(mappings: list[dict[str, Any]], role: str, fallback: str) -> str:
    for mapping in mappings:
        if mapping.get("role") == role:
            return str(mapping.get("entity_path") or fallback)
    return fallback


def _boxes2d(boxes):
    import rerun as rr

    return rr.Boxes2D(
        array=[box.bbox for box in boxes],
        array_format=rr.Box2DFormat.XYWH,
        labels=[box.label or "" for box in boxes],
        class_ids=[box.class_id or 0 for box in boxes],
    )


def _points2d(keypoints_groups):
    import rerun as rr

    positions = []
    labels = []
    class_ids = []
    keypoint_ids = []
    for group_index, group in enumerate(keypoints_groups):
        for point_index, point in enumerate(group.points):
            positions.append(point)
            labels.append(group.label or "")
            class_ids.append(group.class_id or 0)
            keypoint_ids.append(point_index + group_index * 1000)
    return rr.Points2D(
        positions,
        labels=labels,
        class_ids=class_ids,
        keypoint_ids=keypoint_ids,
    )


def _segmentation_image(root: Path, mask_path: str):
    import numpy as np
    import rerun as rr

    resolved = resolve_image_path(root, mask_path)
    with Image.open(resolved) as image:
        return rr.SegmentationImage(np.asarray(image.convert("L")))


def _annotation_context(classes):
    import rerun as rr

    return [
        rr.ClassDescription(
            info=rr.AnnotationInfo(
                class_info.id,
                class_info.label,
                class_info.color or _default_color(class_info.id),
            )
        )
        for class_info in classes
    ]


def _default_color(class_id: int) -> tuple[int, int, int]:
    palette = [
        (255, 80, 80),
        (80, 160, 255),
        (90, 200, 120),
        (255, 190, 80),
        (180, 120, 255),
    ]
    return palette[class_id % len(palette)]
