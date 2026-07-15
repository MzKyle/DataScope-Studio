import json
import sys
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from datascope_core.adapters.image_folder_adapter import ImageFolderAdapter
from datascope_core.mapping import suggest_mapping
from datascope_core.models import ConvertRequest, detect_source_type
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


def test_image_folder_infers_template_json_keypoints(tmp_path: Path) -> None:
    image_dir = tmp_path / "captures"
    image_dir.mkdir()
    Image.new("RGB", (128, 96), (80, 120, 180)).save(image_dir / "scan3d_custom_001.png")
    (image_dir / "scan3d_custom_001_template.json").write_text(
        json.dumps(
            {
                "image_path": str(image_dir / "scan3d_custom_001.png"),
                "points": [
                    {"x": 10, "y": 20, "type": "A"},
                    {"x": 14, "y": 24, "type": "A"},
                    {"x": 40, "y": 52, "type": "B"},
                ],
            }
        ),
        encoding="utf-8",
    )
    adapter = ImageFolderAdapter()

    source = adapter.inspect(str(image_dir), source_id="source_template_points")
    streams = adapter.infer_streams(source)
    preview = adapter.preview(source, "stream_gt_keypoints")

    assert source.metadata["annotation_frame_count"] == 1
    assert source.metadata["annotation_keypoint_count"] == 3
    assert source.metadata["classes"] == [
        {"id": 1, "label": "A", "color": None},
        {"id": 2, "label": "B", "color": None},
    ]
    assert "scan3d_custom_001_template.json" in source.metadata["template_keypoint_sidecars"]
    assert any(stream.semantic_type == "points2d" for stream in streams)
    assert preview["rows"][0]["annotation_keypoints"] == 3


def test_single_tiff_image_is_supported_source(tmp_path: Path) -> None:
    image_path = tmp_path / "frame_001.tif"
    Image.new("RGB", (48, 32), (120, 80, 200)).save(image_path)
    adapter = ImageFolderAdapter()

    source = adapter.inspect(str(image_path), source_id="source_single_image")
    streams = adapter.infer_streams(source)
    preview = adapter.preview(source, "stream_camera_image")

    assert detect_source_type(image_path) == "image_folder"
    assert source.source_type == "image_folder"
    assert source.metadata["image_count"] == 1
    assert source.metadata["images"] == ["frame_001.tif"]
    assert streams[0].semantic_type == "image"
    assert preview["rows"][0]["image"] == "frame_001.tif"
    assert preview["rows"][0]["dimensions"] == {"width": 48, "height": 32}


def test_single_gif_image_is_supported_source(tmp_path: Path) -> None:
    image_path = tmp_path / "frame_002.gif"
    Image.new("P", (24, 18)).save(image_path)

    source = ImageFolderAdapter().inspect(str(image_path), source_id="source_gif")

    assert detect_source_type(image_path) == "image_folder"
    assert source.metadata["image_count"] == 1
    assert source.metadata["sampled_dimensions"]["frame_002.gif"] == {"width": 24, "height": 18}


def test_image_folder_convert_logs_stable_score_paths(tmp_path: Path, monkeypatch) -> None:
    image_dir = _make_cv_fixture(tmp_path)
    adapter = ImageFolderAdapter()
    source = adapter.inspect(str(image_dir), source_id="source_cv")
    streams = adapter.infer_streams(source)
    spec = suggest_mapping(source, streams, template_id="cv_detection")
    recorder = FakeRerunRecording()
    monkeypatch.setitem(sys.modules, "rerun", FakeRerun(recorder))

    adapter.convert(
        ConvertRequest(
            source=source,
            mappings=spec.streams,
            output_rrd=str(tmp_path / "cv.rrd"),
            app_id=spec.app_id,
            recording_id=spec.recording_id,
        )
    )

    logged_paths = [path for path, _, _ in recorder.logs]
    assert "/camera/pred/scores" in logged_paths
    assert "/camera/pred/scores/min" in logged_paths
    assert "/camera/pred/scores/mean" in logged_paths
    assert recorder.disconnected is True


class FakeRerunRecording:
    def __init__(self) -> None:
        self.logs = []
        self.disconnected = False

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def save(self, path: str) -> None:
        Path(path).write_bytes(b"fake rrd")

    def disconnect(self) -> None:
        self.disconnected = True

    def send_recording_name(self, recording_id: str) -> None:
        self.recording_id = recording_id

    def set_time(self, timeline: str, **kwargs) -> None:
        self.time = (timeline, kwargs)

    def log(self, path: str, value, static: bool = False) -> None:
        self.logs.append((path, value, static))


class FakeRerun(SimpleNamespace):
    def __init__(self, recorder: FakeRerunRecording) -> None:
        super().__init__(
            RecordingStream=lambda *args, **kwargs: recorder,
            EncodedImage=lambda **kwargs: ("EncodedImage", kwargs),
            AnnotationContext=lambda value: ("AnnotationContext", value),
            AnnotationInfo=lambda *args: ("AnnotationInfo", args),
            ClassDescription=lambda **kwargs: ("ClassDescription", kwargs),
            Boxes2D=lambda **kwargs: ("Boxes2D", kwargs),
            Box2DFormat=SimpleNamespace(XYWH="XYWH"),
            Points2D=lambda *args, **kwargs: ("Points2D", args, kwargs),
            SegmentationImage=lambda value: ("SegmentationImage", value),
            Scalars=lambda value: ("Scalars", value),
        )


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
