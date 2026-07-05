from pathlib import Path

from fastapi.testclient import TestClient
from mcap.writer import Writer
from typer.testing import CliRunner

import datascope_core.adapters.mcap_adapter as mcap_adapter
import datascope_core.workspace as workspace_module
from datascope_core.rerun_artifacts import normalize_mcap_decoders
from datascope_api.main import app as api_app
from datascope_cli.main import app as cli_app
from datascope_core.workspace import Workspace
from tests.api_helpers import install_fake_rerun, wait_for_job


def test_workspace_mcap_build_uses_rerun_converter(tmp_path: Path, monkeypatch) -> None:
    mcap_path = _make_mcap_fixture(tmp_path)
    commands = _mock_rerun_converter(monkeypatch)
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Robot Pipeline")
    source = workspace.add_source(project["id"], str(mcap_path))
    inspection = workspace.inspect_source(source["id"])
    templates = workspace.suggest_templates(source["id"])
    spec = workspace.suggest_mapping(source["id"], template_id="robotics_debug")
    mapping = workspace.save_mapping(project["id"], source["id"], spec)

    result = workspace.build_recording(
        project["id"],
        source["id"],
        mapping_id=mapping["id"],
        output_name="robot_run",
        template_id="robotics_debug",
    )

    assert source["type"] == "mcap"
    assert len(inspection["streams"]) >= 2
    assert templates[0]["template_id"] == "robotics_debug"
    assert Path(result["recording_path"]).exists()
    assert Path(result["blueprint_path"]).exists()
    assert result["artifact_info"]["converter"] == "rerun_mcap_cli"
    assert "-d" not in commands[0]


def test_workspace_mcap_build_passes_selected_decoders(
    tmp_path: Path,
    monkeypatch,
) -> None:
    mcap_path = _make_mcap_fixture(tmp_path)
    commands = _mock_rerun_converter(monkeypatch)
    monkeypatch.setattr(
        workspace_module,
        "require_supported_artifact_options",
        lambda **kwargs: None,
    )
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Robot Decoders")
    source = workspace.add_source(project["id"], str(mcap_path))
    workspace.inspect_source(source["id"])
    spec = workspace.suggest_mapping(source["id"], template_id="robotics_debug")
    mapping = workspace.save_mapping(project["id"], source["id"], spec)

    result = workspace.build_recording(
        project["id"],
        source["id"],
        mapping_id=mapping["id"],
        output_name="robot_decoders",
        template_id="robotics_debug",
        mcap_decoders=["ros2msg", "foxglove"],
    )

    decoder_args = [
        value
        for index, value in enumerate(commands[0])
        if index > 0 and commands[0][index - 1] == "-d"
    ]
    assert decoder_args == ["ros2msg", "foxglove"]
    assert result["artifact_info"]["mcap_decoders"] == ["ros2msg", "foxglove"]


def test_mcap_decoder_validation_rejects_invalid_decoder() -> None:
    try:
        normalize_mcap_decoders(["ros2msg", "invalid"])
    except ValueError as exc:
        assert "Unsupported MCAP decoder" in str(exc)
    else:
        raise AssertionError("invalid MCAP decoder was accepted")


def test_api_mcap_flow(tmp_path: Path, monkeypatch) -> None:
    mcap_path = _make_mcap_fixture(tmp_path)
    _mock_rerun_converter(monkeypatch)
    install_fake_rerun(tmp_path, monkeypatch)
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "api_workspace"))
    client = TestClient(api_app)

    project = client.post("/api/projects", json={"name": "Robot API"}).json()
    source = client.post(
        f"/api/projects/{project['id']}/sources",
        json={"path": str(mcap_path)},
    ).json()
    assert source["type"] == "mcap"

    inspect_response = client.post(f"/api/sources/{source['id']}/inspect")
    assert inspect_response.status_code == 200

    templates = client.get(f"/api/sources/{source['id']}/templates/suggest").json()
    assert templates[0]["template_id"] == "robotics_debug"

    mapping_payload = client.get(
        f"/api/sources/{source['id']}/mapping/suggest?template_id=robotics_debug"
    ).json()["mapping"]
    mapping = client.post(
        f"/api/sources/{source['id']}/mapping",
        json={"mapping": mapping_payload},
    ).json()
    build_response = client.post(
        "/api/recordings/build",
        json={
            "project_id": project["id"],
            "source_id": source["id"],
            "mapping_id": mapping["id"],
            "template_id": "robotics_debug",
            "output_name": "api_robot_run",
        },
    )

    assert build_response.status_code == 202
    job = wait_for_job(client, build_response.json()["id"])
    assert job["status"] == "succeeded"
    assert Path(job["result"]["recording_path"]).exists()


def test_cli_mcap_import(tmp_path: Path, monkeypatch) -> None:
    mcap_path = _make_mcap_fixture(tmp_path)
    _mock_rerun_converter(monkeypatch)
    install_fake_rerun(tmp_path, monkeypatch)
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "cli_workspace"))
    runner = CliRunner()

    inspect_result = runner.invoke(cli_app, ["inspect", str(mcap_path)])
    assert inspect_result.exit_code == 0
    assert "Source type: mcap" in inspect_result.output
    assert "Topics:" in inspect_result.output

    import_result = runner.invoke(
        cli_app,
        [
            "import",
            str(mcap_path),
            "--project",
            "Robot CLI",
            "--template",
            "robotics_debug",
            "--out",
            "cli_robot_run",
        ],
    )

    assert import_result.exit_code == 0
    assert "Recording:" in import_result.output


def _make_mcap_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "robot.mcap"
    with open(path, "wb") as stream:
        writer = Writer(stream)
        writer.start(profile="ros2", library="datascope-test")
        for index, (topic, schema_name) in enumerate(
            [
                ("/camera/front/image_raw", "sensor_msgs/msg/Image"),
                ("/lidar/points", "sensor_msgs/msg/PointCloud2"),
                ("/tf", "tf2_msgs/msg/TFMessage"),
            ],
            start=1,
        ):
            schema_id = writer.register_schema(schema_name, "ros2msg", b"uint8[] data")
            channel_id = writer.register_channel(topic, "cdr", schema_id)
            writer.add_message(channel_id, log_time=index, publish_time=index, data=b"\x00")
        writer.finish()
    return path


def _mock_rerun_converter(monkeypatch) -> list[list[str]]:
    commands: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, capture_output, text, check, env=None):
        commands.append(list(command))
        output = Path(command[command.index("--output") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"mock rrd")
        return Result()

    monkeypatch.setattr(mcap_adapter, "rerun_command", lambda: ["/usr/bin/rerun"])
    monkeypatch.setattr(mcap_adapter.subprocess, "run", fake_run)
    return commands
