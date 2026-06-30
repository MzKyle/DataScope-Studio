from pathlib import Path

import pytest

import datascope_core.workspace as workspace_module
from datascope_core.models import ConvertRequest
from datascope_core.workspace import RerunArtifactError, Workspace, _converter_id


def test_build_recording_persists_artifact_info(tmp_path: Path, monkeypatch) -> None:
    workspace, project, source, mapping = _mapped_csv_workspace(tmp_path)
    _install_fake_artifact_writers(monkeypatch, recording_payload=b"rrd", blueprint_payload=b"rbl")

    result = workspace.build_recording(
        project["id"],
        source["id"],
        mapping_id=mapping["id"],
        output_name="artifact_run",
    )
    recording = workspace.get_recording(result["recording_id"])

    assert result["artifact_info"] == {
        "recording_size_bytes": 3,
        "blueprint_size_bytes": 3,
        "app_id": "datascope.sensor_monitor.v1",
        "template_id": "sensor_monitor",
        "rerun_recording_id": result["artifact_info"]["rerun_recording_id"],
        "source_type": "csv",
        "converter": "rerun_python_sdk",
        "rerun_version": result["artifact_info"]["rerun_version"],
    }
    assert recording["params"]["rerun_artifact"] == result["artifact_info"]
    assert recording["artifact_status"]["status"] == "ready"
    assert recording["artifact_status"]["recording_size_bytes"] == 3


def test_recording_artifact_status_reports_missing_and_empty_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace, project, source, mapping = _mapped_csv_workspace(tmp_path)
    _install_fake_artifact_writers(monkeypatch, recording_payload=b"rrd", blueprint_payload=b"rbl")
    result = workspace.build_recording(
        project["id"],
        source["id"],
        mapping_id=mapping["id"],
        output_name="status_run",
    )

    Path(result["recording_path"]).unlink()
    missing = workspace.get_recording(result["recording_id"])
    assert missing["artifact_status"]["status"] == "missing"

    Path(result["recording_path"]).write_bytes(b"")
    empty = workspace.get_recording(result["recording_id"])
    assert empty["artifact_status"]["status"] == "empty"


@pytest.mark.parametrize(
    ("recording_payload", "blueprint_payload"),
    [(b"", b"rbl"), (b"rrd", b"")],
)
def test_build_recording_rejects_empty_artifacts(
    tmp_path: Path,
    monkeypatch,
    recording_payload: bytes,
    blueprint_payload: bytes,
) -> None:
    workspace, project, source, mapping = _mapped_csv_workspace(tmp_path)
    _install_fake_artifact_writers(
        monkeypatch,
        recording_payload=recording_payload,
        blueprint_payload=blueprint_payload,
    )

    with pytest.raises(RerunArtifactError) as exc_info:
        workspace.build_recording(
            project["id"],
            source["id"],
            mapping_id=mapping["id"],
            output_name="empty_artifact",
        )

    recording_path = Path(project["workspace_path"]) / "recordings" / "empty_artifact.rrd"
    blueprint_path = Path(project["workspace_path"]) / "blueprints" / "empty_artifact.rbl"
    job = workspace.list_jobs(project["id"])[0]
    assert exc_info.value.code == "rerun_artifact_invalid"
    assert job["status"] == "failed"
    assert job["error"]["code"] == "rerun_artifact_invalid"
    assert not recording_path.exists()
    assert not blueprint_path.exists()
    assert workspace.list_recordings(project["id"]) == []


def test_build_recording_rejects_missing_artifact(tmp_path: Path, monkeypatch) -> None:
    workspace, project, source, mapping = _mapped_csv_workspace(tmp_path)

    class MissingRecordingAdapter:
        def convert(self, request: ConvertRequest) -> None:
            Path(request.output_rrd).unlink(missing_ok=True)

    monkeypatch.setattr(
        Workspace,
        "_adapter_for_path",
        lambda self, path, source_type=None: MissingRecordingAdapter(),
    )
    monkeypatch.setattr(
        workspace_module,
        "save_blueprint",
        lambda spec, template_id, path: Path(path).write_bytes(b"rbl"),
    )

    with pytest.raises(RerunArtifactError):
        workspace.build_recording(
            project["id"],
            source["id"],
            mapping_id=mapping["id"],
            output_name="missing_artifact",
        )

    assert not (Path(project["workspace_path"]) / "blueprints" / "missing_artifact.rbl").exists()


def test_converter_ids_are_stable() -> None:
    assert _converter_id("mcap") == "rerun_mcap_cli"
    assert _converter_id("ros2_db3") == "ros2_db3_to_mcap_to_rerun_cli"
    assert _converter_id("csv") == "rerun_python_sdk"
    assert _converter_id("custom") == "adapter_python"


def _mapped_csv_workspace(tmp_path: Path) -> tuple[Workspace, dict, dict, dict]:
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("time,value\n1,2\n2,3\n", encoding="utf-8")
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Artifacts")
    source = workspace.add_source(project["id"], str(csv_path))
    workspace.inspect_source(source["id"])
    spec = workspace.suggest_mapping(source["id"])
    mapping = workspace.save_mapping(project["id"], source["id"], spec)
    return workspace, project, source, mapping


def _install_fake_artifact_writers(
    monkeypatch,
    *,
    recording_payload: bytes,
    blueprint_payload: bytes,
) -> None:
    class FakeAdapter:
        def convert(self, request: ConvertRequest) -> None:
            Path(request.output_rrd).write_bytes(recording_payload)

    monkeypatch.setattr(
        Workspace,
        "_adapter_for_path",
        lambda self, path, source_type=None: FakeAdapter(),
    )
    monkeypatch.setattr(
        workspace_module,
        "save_blueprint",
        lambda spec, template_id, path: Path(path).write_bytes(blueprint_payload),
    )
