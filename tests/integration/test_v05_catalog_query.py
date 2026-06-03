import json
from pathlib import Path

from fastapi.testclient import TestClient
from mcap.writer import Writer
from PIL import Image
from typer.testing import CliRunner

import datascope_core.adapters.mcap_adapter as mcap_adapter
from datascope_api.main import app as api_app
from datascope_cli.main import app as cli_app
from datascope_core.workspace import Workspace


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_csv_recording_catalog_low_battery_and_export(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Catalog CSV")
    result = _import_source(
        workspace,
        project["id"],
        str(FIXTURES / "sample_sensor.csv"),
        "sensor_monitor",
        "csv_run",
    )

    recording = workspace.update_recording(
        result["recording_id"],
        add_tags=["failed", "firmware:v1.2"],
        params={"firmware": "v1.2"},
    )
    recordings = workspace.list_recordings(project["id"])
    query = workspace.run_query(
        project["id"],
        "low_battery",
        recording_ids=[result["recording_id"]],
        params={"threshold": 0.925},
    )
    export = workspace.export_query(
        project["id"],
        "low_battery",
        recording_ids=[result["recording_id"]],
        params={"threshold": 0.925},
        fmt="csv",
    )

    assert "failed" in recording["tags"]
    assert recordings[0]["params"]["firmware"] == "v1.2"
    assert len(query["rows"]) == 2
    assert Path(export["path"]).exists()


def test_jsonl_find_errors_and_state_duration(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Catalog JSONL")
    result = _import_source(
        workspace,
        project["id"],
        str(FIXTURES / "sample_sensor.jsonl"),
        "sensor_monitor",
        "jsonl_run",
    )

    errors = workspace.run_query(project["id"], "find_errors", [result["recording_id"]], {})
    durations = workspace.run_query(project["id"], "state_duration", [result["recording_id"]], {})

    assert any("ERROR" in str(row["value"]) for row in errors["rows"])
    assert any(row["key"] == "state" for row in durations["rows"])


def test_cv_detection_failure_query(tmp_path: Path) -> None:
    image_dir = _make_cv_fixture(tmp_path)
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Catalog CV")
    result = _import_source(
        workspace,
        project["id"],
        str(image_dir),
        "cv_detection",
        "cv_run",
    )

    query = workspace.run_query(
        project["id"],
        "detection_failure",
        [result["recording_id"]],
        {"threshold": 0.5},
    )

    assert any(row["value"]["reason"] == "low_score" for row in query["rows"])


def test_mcap_topic_summary_query(tmp_path: Path, monkeypatch) -> None:
    _mock_rerun_converter(monkeypatch)
    mcap_path = _make_mcap_fixture(tmp_path)
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Catalog MCAP")
    result = _import_source(
        workspace,
        project["id"],
        str(mcap_path),
        "robotics_debug",
        "robot_run",
    )

    query = workspace.run_query(project["id"], "topic_summary", [result["recording_id"]], {})

    assert any(row["value"]["role"] == "camera_image" for row in query["rows"])
    assert any(row["value"]["role"] == "point_cloud" for row in query["rows"])


def test_api_recording_patch_query_and_export(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "api_workspace"))
    client = TestClient(api_app)
    project = client.post("/api/projects", json={"name": "API Catalog"}).json()
    result = _api_import(client, project["id"], str(FIXTURES / "sample_sensor.csv"), "sensor_monitor")

    recordings_response = client.get(f"/api/projects/{project['id']}/recordings")
    assert recordings_response.status_code == 200
    assert recordings_response.json()

    patch_response = client.patch(
        f"/api/recordings/{result['recording_id']}",
        json={"add_tags": ["failed"], "params": {"firmware": "v1.2"}},
    )
    assert patch_response.status_code == 200
    assert "failed" in patch_response.json()["tags"]

    query_response = client.post(
        f"/api/projects/{project['id']}/query",
        json={
            "template_id": "low_battery",
            "recording_ids": [result["recording_id"]],
            "params": {"threshold": 0.925},
            "limit": 1000,
        },
    )
    assert query_response.status_code == 200
    assert len(query_response.json()["rows"]) == 2

    export_response = client.post(
        f"/api/projects/{project['id']}/query/export",
        json={
            "template_id": "low_battery",
            "recording_ids": [result["recording_id"]],
            "params": {"threshold": 0.925},
            "format": "csv",
        },
    )
    assert export_response.status_code == 200
    assert Path(export_response.json()["path"]).exists()


def test_cli_recordings_tag_query_and_export(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "cli_workspace"))
    runner = CliRunner()
    import_result = runner.invoke(
        cli_app,
        [
            "import",
            str(FIXTURES / "sample_sensor.csv"),
            "--project",
            "CLI Catalog",
            "--out",
            "cli_catalog_run",
        ],
    )
    assert import_result.exit_code == 0

    workspace = Workspace(tmp_path / "cli_workspace")
    project = workspace.list_projects()[0]
    recording_id = workspace.list_recordings(project["id"])[0]["id"]

    list_result = runner.invoke(cli_app, ["recordings", "--project", "CLI Catalog"])
    assert list_result.exit_code == 0
    assert recording_id in list_result.output

    tag_result = runner.invoke(cli_app, ["tag", recording_id, "--add", "failed"])
    assert tag_result.exit_code == 0
    assert "failed" in tag_result.output

    query_result = runner.invoke(
        cli_app,
        [
            "query",
            "--project",
            "CLI Catalog",
            "--template",
            "low_battery",
            "--threshold",
            "0.925",
        ],
    )
    assert query_result.exit_code == 0
    assert "battery" in query_result.output

    export_result = runner.invoke(
        cli_app,
        [
            "export-query",
            "--project",
            "CLI Catalog",
            "--template",
            "low_battery",
            "--threshold",
            "0.925",
        ],
    )
    assert export_result.exit_code == 0
    assert "Exported" in export_result.output


def _import_source(
    workspace: Workspace,
    project_id: str,
    path: str,
    template_id: str,
    output_name: str,
) -> dict:
    source = workspace.add_source(project_id, path)
    workspace.inspect_source(source["id"])
    spec = workspace.suggest_mapping(source["id"], template_id=template_id)
    mapping = workspace.save_mapping(project_id, source["id"], spec)
    return workspace.build_recording(
        project_id,
        source["id"],
        mapping_id=mapping["id"],
        template_id=template_id,
        output_name=output_name,
    )


def _api_import(client: TestClient, project_id: str, path: str, template_id: str) -> dict:
    source = client.post(f"/api/projects/{project_id}/sources", json={"path": path}).json()
    client.post(f"/api/sources/{source['id']}/inspect")
    mapping = client.get(
        f"/api/sources/{source['id']}/mapping/suggest?template_id={template_id}"
    ).json()["mapping"]
    saved_mapping = client.post(
        f"/api/sources/{source['id']}/mapping",
        json={"mapping": mapping},
    ).json()
    return client.post(
        "/api/recordings/build",
        json={
            "project_id": project_id,
            "source_id": source["id"],
            "mapping_id": saved_mapping["id"],
            "template_id": template_id,
            "output_name": "api_catalog_run",
        },
    ).json()


def _make_cv_fixture(tmp_path: Path) -> Path:
    image_dir = tmp_path / "dataset" / "images"
    image_dir.mkdir(parents=True)
    for index in (1, 2):
        Image.new("RGB", (96, 64), (220, 70, 70)).save(image_dir / f"{index:06d}.png")

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
                    "score": 0.4 if index == 2 else 0.9,
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


def _make_mcap_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "robot.mcap"
    with open(path, "wb") as stream:
        writer = Writer(stream)
        writer.start(profile="ros2", library="datascope-test")
        for index, (topic, schema_name) in enumerate(
            [
                ("/camera/front/image_raw", "sensor_msgs/msg/Image"),
                ("/lidar/points", "sensor_msgs/msg/PointCloud2"),
            ],
            start=1,
        ):
            schema_id = writer.register_schema(schema_name, "ros2msg", b"uint8[] data")
            channel_id = writer.register_channel(topic, "cdr", schema_id)
            writer.add_message(channel_id, log_time=index, publish_time=index, data=b"\x00")
        writer.finish()
    return path


def _mock_rerun_converter(monkeypatch) -> None:
    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, capture_output, text, check):
        output = Path(command[command.index("--output") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"mock rrd")
        return Result()

    monkeypatch.setattr(mcap_adapter.shutil, "which", lambda _: "/usr/bin/rerun")
    monkeypatch.setattr(mcap_adapter.subprocess, "run", fake_run)

