import json
from pathlib import Path

from PIL import Image

from datascope_core.adapters.image_folder_adapter import ImageFolderAdapter
from datascope_core.mapping import suggest_mapping
from datascope_core.templates import match_templates


def test_image_folder_inspect_detects_sidecars_classes_and_streams(tmp_path: Path) -> None:
    image_dir = _make_cv_fixture(tmp_path)
    adapter = ImageFolderAdapter()

    source = adapter.inspect(str(image_dir), source_id="source_cv")
    streams = adapter.infer_streams(source)

    assert source.source_type == "image_folder"
    assert source.metadata["image_count"] == 2
    assert source.metadata["annotation_frame_count"] == 2
    assert source.metadata["prediction_frame_count"] == 2
    assert source.metadata["classes"][0]["label"] == "person"
    assert {stream.semantic_type for stream in streams} >= {"image", "boxes2d", "scalar"}


def test_cv_mapping_and_template_are_selected_for_image_boxes(tmp_path: Path) -> None:
    image_dir = _make_cv_fixture(tmp_path)
    adapter = ImageFolderAdapter()
    source = adapter.inspect(str(image_dir), source_id="source_cv")
    streams = adapter.infer_streams(source)

    spec = suggest_mapping(source, streams, mapping_id="mapping_cv", template_id="cv_detection")
    matches = match_templates(streams)

    assert spec.app_id == "datascope.cv_detection.v1"
    assert any(stream["entity_path"] == "/camera/image" for stream in spec.streams)
    assert any(stream["entity_path"] == "/camera/gt/boxes" for stream in spec.streams)
    assert any(stream["entity_path"] == "/camera/pred/boxes" for stream in spec.streams)
    assert matches[0]["template_id"] == "cv_detection"


def _make_cv_fixture(tmp_path: Path) -> Path:
    image_dir = tmp_path / "dataset" / "images"
    image_dir.mkdir(parents=True)
    for index, color in enumerate(((230, 60, 60), (60, 130, 230)), start=1):
        Image.new("RGB", (96, 64), color).save(image_dir / f"{index:06d}.png")

    classes = [{"id": 1, "label": "person", "color": [255, 80, 80]}]
    frames = [
        {
            "image": f"images/{index:06d}.png",
            "time": float(index - 1),
            "boxes": [{"bbox": [10, 12, 30, 24], "class_id": 1, "label": "person"}],
        }
        for index in (1, 2)
    ]
    predictions = [
        {
            "image": f"images/{index:06d}.png",
            "time": float(index - 1),
            "boxes": [
                {
                    "bbox": [12, 14, 28, 22],
                    "class_id": 1,
                    "label": "person",
                    "score": 0.9 - index * 0.1,
                }
            ],
        }
        for index in (1, 2)
    ]
    (tmp_path / "dataset" / "annotations.json").write_text(
        json.dumps({"classes": classes, "frames": frames}),
        encoding="utf-8",
    )
    (tmp_path / "dataset" / "predictions.json").write_text(
        json.dumps({"classes": classes, "frames": predictions}),
        encoding="utf-8",
    )
    return image_dir

