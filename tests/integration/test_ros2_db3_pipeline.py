from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

import datascope_core.adapters.mcap_adapter as mcap_adapter
import datascope_core.workspace as workspace_module
from datascope_api.main import app as api_app
from datascope_cli.main import app as cli_app
from datascope_core.workspace import Workspace
from tests.ros2_bag_helpers import make_ros2_directory
from tests.api_helpers import install_fake_rerun, wait_for_job


def test_workspace_ros2_db3_file_build_and_query(
    tmp_path: Path,
    monkeypatch,
) -> None:
    commands = _mock_rerun_converter(monkeypatch)
    source_bag = make_ros2_directory(
        tmp_path / "source_bag",
        [
            (
                "robot_run.db3",
                [
                    ("/chatter", "std_msgs/msg/String"),
                    ("/custom", "acme_msgs/msg/Unknown"),
                ],
            )
        ],
    )
    db3_path = source_bag / "robot_run.db3"
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("ROS2 DB3")

    source = workspace.add_source(project["id"], str(db3_path))
    inspection = workspace.inspect_source(source["id"])
    spec = workspace.suggest_mapping(source["id"], template_id="robotics_debug")
    validation = workspace.validate_mapping_spec(source["id"], spec)
    mapping = workspace.save_mapping(project["id"], source["id"], spec)
    result = workspace.build_recording(
        project["id"],
        source["id"],
        mapping_id=mapping["id"],
        template_id="robotics_debug",
    )
    query = workspace.run_query(
        project["id"],
        "topic_summary",
        [result["recording_id"]],
        {},
    )

    stored_source = workspace.get_source(source["id"])
    assert source["type"] == "ros2_db3"
    assert Path(stored_source["uri"]).parent.joinpath("metadata.yaml").is_file()
    assert inspection["source"]["metadata"]["effective_ros_distro"] == "humble"
    assert validation["valid"] is True
    assert any(issue["code"] == "ros2_topics_skipped" for issue in validation["warnings"])
    assert Path(result["recording_path"]).name == "robot_run.rrd"
    assert Path(result["blueprint_path"]).name == "robot_run.rbl"
    assert result["artifact_info"]["converter"] == "ros2_db3_to_mcap_to_rerun_cli"
    assert "-d" not in commands[0]
    assert any(
        row["value"].get("message_type") == "acme_msgs/msg/Unknown"
        and row["value"].get("convertible") is False
        for row in query["rows"]
        if isinstance(row["value"], dict)
    )


def test_workspace_ros2_db3_passes_mcap_decoders(
    tmp_path: Path,
    monkeypatch,
) -> None:
    commands = _mock_rerun_converter(monkeypatch)
    monkeypatch.setattr(
        workspace_module,
        "require_supported_artifact_options",
        lambda **kwargs: None,
    )
    source_bag = make_ros2_directory(
        tmp_path / "source_bag",
        [("robot_run.db3", [("/chatter", "std_msgs/msg/String")])],
    )
    db3_path = source_bag / "robot_run.db3"
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("ROS2 DB3 Decoders")
    source = workspace.add_source(project["id"], str(db3_path))
    workspace.inspect_source(source["id"])
    spec = workspace.suggest_mapping(source["id"], template_id="robotics_debug")
    mapping = workspace.save_mapping(project["id"], source["id"], spec)

    result = workspace.build_recording(
        project["id"],
        source["id"],
        mapping_id=mapping["id"],
        template_id="robotics_debug",
        mcap_decoders=["ros2msg", "raw"],
    )

    decoder_args = [
        value
        for index, value in enumerate(commands[0])
        if index > 0 and commands[0][index - 1] == "-d"
    ]
    assert decoder_args == ["ros2msg", "raw"]
    assert result["artifact_info"]["mcap_decoders"] == ["ros2msg", "raw"]


def test_api_ros2_db3_directory_flow(tmp_path: Path, monkeypatch) -> None:
    _mock_rerun_converter(monkeypatch)
    install_fake_rerun(tmp_path, monkeypatch)
    bag = make_ros2_directory(
        tmp_path / "api_bag",
        [("api_bag.db3", [("/tf", "tf2_msgs/msg/TFMessage")])],
    )
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "api_workspace"))
    client = TestClient(api_app)

    project = client.post("/api/projects", json={"name": "ROS2 API"}).json()
    source_response = client.post(
        f"/api/projects/{project['id']}/sources",
        json={"path": str(bag)},
    )
    source = source_response.json()
    inspect_response = client.post(f"/api/sources/{source['id']}/inspect")
    templates_response = client.get(f"/api/sources/{source['id']}/templates/suggest")
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
            "output_name": "api_ros2",
        },
    )

    assert source_response.status_code == 200
    assert source["type"] == "ros2_db3"
    assert inspect_response.status_code == 200
    assert inspect_response.json()["source"]["metadata"]["topic_count"] == 1
    assert templates_response.json()[0]["template_id"] == "robotics_debug"
    assert build_response.status_code == 202
    job = wait_for_job(client, build_response.json()["id"])
    assert job["status"] == "succeeded"
    assert Path(job["result"]["recording_path"]).is_file()


def test_cli_ros2_db3_import(tmp_path: Path, monkeypatch) -> None:
    _mock_rerun_converter(monkeypatch)
    install_fake_rerun(tmp_path, monkeypatch)
    bag = make_ros2_directory(
        tmp_path / "cli_bag",
        [("cli_bag.db3", [("/odom", "nav_msgs/msg/Odometry")])],
    )
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "cli_workspace"))
    runner = CliRunner()

    inspect_result = runner.invoke(cli_app, ["inspect", str(bag)])
    import_result = runner.invoke(
        cli_app,
        [
            "import",
            str(bag),
            "--project",
            "ROS2 CLI",
            "--template",
            "robotics_debug",
        ],
    )

    assert inspect_result.exit_code == 0
    assert "Source type: ros2_db3" in inspect_result.output
    assert "ROS distribution: humble" in inspect_result.output
    assert import_result.exit_code == 0
    assert "Recording:" in import_result.output
    assert len(list((tmp_path / "cli_workspace").rglob("cli_bag.rrd"))) == 1


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
