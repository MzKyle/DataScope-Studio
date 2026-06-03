import json
from pathlib import Path

from datascope_core.adapters.mcap_adapter import classify_topic
from datascope_core.cv_schema import parse_cv_sidecar
from datascope_core.plugin_registry import validate_plugin
from datascope_core.workspace import Workspace


def test_plugin_manifest_validation_and_adapter_loading(tmp_path: Path) -> None:
    plugin_dir = _make_dummy_plugin(tmp_path)

    validation = validate_plugin(plugin_dir)

    assert validation["valid"] is True
    assert validation["loaded"]["adapters"] == ["dummy"]


def test_plugin_manifest_accepts_design_entry_points_list(tmp_path: Path) -> None:
    plugin_dir = _make_dummy_plugin(tmp_path)
    (plugin_dir / "plugin.yaml").write_text(
        """
id: dummy_plugin
name: Dummy Plugin
version: 1.0.0
entry_points:
  adapters:
    - dummy_adapter:DummyAdapter
""",
        encoding="utf-8",
    )

    validation = validate_plugin(plugin_dir)

    assert validation["valid"] is True
    assert validation["loaded"]["adapters"] == ["DummyAdapter"]


def test_workspace_installed_plugin_adapter_can_inspect_source(tmp_path: Path) -> None:
    plugin_dir = _make_dummy_plugin(tmp_path)
    source_path = tmp_path / "sample.dummy"
    source_path.write_text("42\n", encoding="utf-8")
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Plugin Project")
    plugin = workspace.install_plugin(str(plugin_dir))

    source = workspace.add_source(project["id"], str(source_path))
    inspection = workspace.inspect_source(source["id"])

    assert plugin["id"] == "dummy_plugin"
    assert source["type"] == "dummy"
    assert inspection["streams"][0]["semantic_type"] == "scalar"


def test_template_registry_install_and_app_ids(tmp_path: Path) -> None:
    template_path = tmp_path / "template.yaml"
    template_path.write_text(
        """
template:
  id: lab_template
  name: Lab Template
  version: 1.0.0
  app_id: datascope.lab_template.v1
""",
        encoding="utf-8",
    )
    workspace = Workspace(tmp_path / "workspace")

    template = workspace.install_template(str(template_path))

    assert template["id"] == "lab_template"
    assert workspace.template_app_ids()["lab_template"] == "datascope.lab_template.v1"


def test_cv_schema_accepts_keypoints_and_masks() -> None:
    sidecar = parse_cv_sidecar(
        {
            "classes": [{"id": 1, "label": "person"}],
            "frames": [
                {
                    "image": "images/000001.png",
                    "keypoints": [{"points": [[1, 2], [3, 4]], "class_id": 1}],
                    "masks": [{"path": "masks/000001.png", "class_id": 1}],
                }
            ],
        },
        "annotations.json",
        "annotations",
    )

    assert sidecar.frames[0].keypoints[0].points == [[1.0, 2.0], [3.0, 4.0]]
    assert sidecar.frames[0].masks[0].path == "masks/000001.png"


def test_mcap_robot_description_topic_is_robot_model() -> None:
    role, semantic_type, confidence = classify_topic("/robot_description", "std_msgs/msg/String")

    assert role == "robot_model"
    assert semantic_type == "asset3d"
    assert confidence > 0.8


def _make_dummy_plugin(tmp_path: Path) -> Path:
    plugin_dir = tmp_path / "dummy_plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yaml").write_text(
        """
id: dummy_plugin
name: Dummy Plugin
version: 1.0.0
entrypoints:
  adapters:
    dummy: dummy_adapter:DummyAdapter
permissions:
  - read_files
""",
        encoding="utf-8",
    )
    (plugin_dir / "dummy_adapter.py").write_text(
        """
from pathlib import Path
from datascope_core.models import ConvertRequest, SourceInfo, StreamInfo


class DummyAdapter:
    adapter_id = "dummy"
    display_name = "Dummy"
    supported_extensions = [".dummy"]

    def inspect(self, path: str, source_id: str | None = None) -> SourceInfo:
        return SourceInfo(source_id or "source_dummy", "dummy", path, {"rows": 1})

    def infer_streams(self, source: SourceInfo) -> list[StreamInfo]:
        return [StreamInfo("stream_value", "value", "scalar", ["value"], "time", 0.9, {})]

    def preview(self, source: SourceInfo, stream_id: str, limit: int = 100) -> dict:
        return {"source_id": source.source_id, "stream_id": stream_id, "columns": ["value"], "rows": [{"value": 42}]}

    def convert(self, request: ConvertRequest) -> None:
        Path(request.output_rrd).parent.mkdir(parents=True, exist_ok=True)
        Path(request.output_rrd).write_bytes(b"dummy rrd")
""",
        encoding="utf-8",
    )
    return plugin_dir
