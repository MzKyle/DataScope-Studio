from __future__ import annotations

import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from mcap.writer import Writer
from typer.testing import CliRunner

from datascope_api.main import app as api_app
from datascope_cli.main import app as cli_app
from datascope_core.workspace import Workspace
from tests.api_helpers import install_fake_rerun, wait_for_job


def test_workspace_api_and_cli_diagnostics(tmp_path: Path, monkeypatch) -> None:
    install_fake_rerun(tmp_path, monkeypatch)
    workspace_root = tmp_path / "workspace"
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(workspace_root))
    mcap_path = _make_mcap_fixture(tmp_path)

    workspace = Workspace(workspace_root)
    project = workspace.create_project("Diagnostics")
    source = workspace.add_source(project["id"], str(mcap_path))
    workspace.inspect_source(source["id"])
    spec = workspace.suggest_mapping(source["id"], template_id="robotics_debug")
    mapping = workspace.save_mapping(project["id"], source["id"], spec)
    result = workspace.build_recording(
        project["id"],
        source["id"],
        mapping_id=mapping["id"],
        template_id="robotics_debug",
        output_name="diagnostic_robot",
    )

    report = workspace.run_diagnostics(project["id"], [result["recording_id"]])
    assert report["summary"]["recording_count"] == 1
    assert report["summary"]["topic_count"] >= 3
    assert any(check["id"] == "topic_coverage" for check in report["checks"])
    presets = workspace.diagnostic_presets(project["id"])
    balanced = next(item for item in presets if item["id"] == "balanced")
    strict = next(item for item in presets if item["id"] == "strict")
    assert balanced["thresholds"] == report["thresholds"]
    assert (
        strict["thresholds"]["detection_confidence"]
        > balanced["thresholds"]["detection_confidence"]
    )

    json_export = workspace.export_diagnostics(
        project["id"],
        [result["recording_id"]],
        preset="strict",
        fmt="json",
    )
    csv_export = workspace.export_diagnostics(
        project["id"],
        [result["recording_id"]],
        fmt="csv",
        output_path=str(tmp_path / "diagnostics.csv"),
    )
    html_export = workspace.export_diagnostics(
        project["id"],
        [result["recording_id"]],
        fmt="html",
        output_path=str(tmp_path / "diagnostics.html"),
    )
    assert Path(json_export["path"]).is_file()
    assert json.loads(Path(json_export["path"]).read_text(encoding="utf-8"))["summary"][
        "recording_count"
    ] == 1
    assert Path(csv_export["path"]).read_text(encoding="utf-8").startswith(
        "id,severity,category,recording_id,source_id,topic"
    )
    assert "DataScope Diagnostics Report" in Path(html_export["path"]).read_text(encoding="utf-8")
    assert len(workspace.list_diagnostic_exports(project["id"])) == 3

    package = workspace.export_project(project["id"], str(tmp_path / "diagnostics_project.zip"))
    with zipfile.ZipFile(package["path"]) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert len(manifest["diagnostic_exports"]) == 3
    imported = workspace.import_project_package(package["path"], project_name="Diagnostics Imported")
    assert len(workspace.list_diagnostic_exports(imported["project"]["id"])) == 3

    client = TestClient(api_app)
    presets_response = client.get(f"/api/projects/{project['id']}/diagnostics/presets")
    assert presets_response.status_code == 200
    assert {item["id"] for item in presets_response.json()} >= {"balanced", "strict", "lenient"}
    response = client.post(
        f"/api/projects/{project['id']}/diagnostics",
        json={"recording_ids": [result["recording_id"]], "preset": "lenient"},
    )
    assert response.status_code == 200
    assert response.json()["summary"]["recording_count"] == 1
    export_response = client.post(
        f"/api/projects/{project['id']}/diagnostics/export",
        json={
            "recording_ids": [result["recording_id"]],
            "preset": "balanced",
            "format": "html",
        },
    )
    assert export_response.status_code == 200
    assert Path(export_response.json()["path"]).is_file()
    exports_response = client.get(f"/api/projects/{project['id']}/diagnostics/exports")
    assert exports_response.status_code == 200
    assert len(exports_response.json()) >= 4

    runner = CliRunner()
    cli_json = runner.invoke(
        cli_app,
        [
            "diagnose",
            "--project",
            project["id"],
            "--recording",
            result["recording_id"],
            "--json",
        ],
    )
    assert cli_json.exit_code == 0
    assert json.loads(cli_json.output)["summary"]["recording_count"] == 1

    output_path = tmp_path / "diagnostics.json"
    cli_out = runner.invoke(
        cli_app,
        [
            "diagnose",
            "--project",
            project["id"],
            "--recording",
            result["recording_id"],
            "--out",
            str(output_path),
        ],
    )
    assert cli_out.exit_code == 0
    assert output_path.is_file()
    assert json.loads(output_path.read_text())["summary"]["topic_count"] >= 3
    csv_path = tmp_path / "diagnostics_cli.csv"
    cli_csv = runner.invoke(
        cli_app,
        [
            "diagnose",
            "--project",
            project["id"],
            "--recording",
            result["recording_id"],
            "--format",
            "csv",
            "--out",
            str(csv_path),
        ],
    )
    assert cli_csv.exit_code == 0
    assert csv_path.read_text(encoding="utf-8").startswith(
        "id,severity,category,recording_id,source_id,topic"
    )


def test_api_diagnostics_after_async_build(tmp_path: Path, monkeypatch) -> None:
    install_fake_rerun(tmp_path, monkeypatch)
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "api_workspace"))
    client = TestClient(api_app)
    mcap_path = _make_mcap_fixture(tmp_path)

    project = client.post("/api/projects", json={"name": "Diagnostics API"}).json()
    source = client.post(
        f"/api/projects/{project['id']}/sources",
        json={"path": str(mcap_path)},
    ).json()
    client.post(f"/api/sources/{source['id']}/inspect")
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
            "output_name": "diagnostic_api",
        },
    )
    job = wait_for_job(client, build_response.json()["id"])

    diagnostics = client.post(
        f"/api/projects/{project['id']}/diagnostics",
        json={"recording_ids": [job["result"]["recording_id"]]},
    )

    assert diagnostics.status_code == 200
    assert diagnostics.json()["summary"]["recording_count"] == 1
    assert "health_score" in diagnostics.json()["summary"]


def test_tabular_diagnostics_report_data_health_findings(tmp_path: Path) -> None:
    csv_path = tmp_path / "quality.csv"
    csv_path.write_text(
        "timestamp,temperature,voltage,state,message\n"
        "0.0,20.0,12.0,IDLE,boot\n"
        "0.1,,12.1,IDLE,ok\n"
        "0.1,,12.2,IDLE,duplicate time\n"
        "0.2,,12.3,IDLE,ok\n"
        "8.0,,55.0,IDLE,spike\n"
        "8.1,,12.4,IDLE,ok\n",
        encoding="utf-8",
    )
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Tabular Diagnostics")
    source = workspace.add_source(project["id"], str(csv_path))
    workspace.inspect_source(source["id"])
    spec = workspace.suggest_mapping(source["id"], template_id="sensor_monitor")
    mapping = workspace.save_mapping(project["id"], source["id"], spec)
    result = workspace.build_recording(
        project["id"],
        source["id"],
        mapping_id=mapping["id"],
        output_name="quality_run",
        template_id="sensor_monitor",
    )

    report = workspace.run_diagnostics(
        project["id"],
        [result["recording_id"]],
        thresholds={
            "missing_ratio_warn": 0.2,
            "missing_ratio_critical": 0.5,
            "time_gap_factor_warn": 5.0,
        },
    )
    categories = {finding["category"] for finding in report["findings"]}
    export = workspace.export_diagnostics(
        project["id"],
        [result["recording_id"]],
        thresholds={"missing_ratio_warn": 0.2},
        fmt="json",
    )

    assert report["summary"]["recording_count"] == 1
    assert report["summary"]["topic_count"] == 0
    assert {"schema_quality", "time_series_quality", "data_quality"} <= categories
    assert any(check["id"] == "schema_quality" for check in report["checks"])
    assert Path(export["path"]).is_file()
    assert "schema_quality" in Path(export["path"]).read_text(encoding="utf-8")


def _make_mcap_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "diagnostic_robot.mcap"
    with path.open("wb") as stream:
        writer = Writer(stream)
        writer.start(profile="ros2", library="datascope-test")
        topics = [
            ("/tf", "tf2_msgs/msg/TFMessage"),
            ("/camera/image", "sensor_msgs/msg/Image"),
            ("/lidar/points", "sensor_msgs/msg/PointCloud2"),
            ("/odom", "nav_msgs/msg/Odometry"),
        ]
        for index, (topic, schema_name) in enumerate(topics, start=1):
            schema_id = writer.register_schema(schema_name, "ros2msg", b"uint8[] data")
            channel_id = writer.register_channel(topic, "cdr", schema_id)
            writer.add_message(
                channel_id,
                log_time=1_700_000_000_000_000_000 + index,
                publish_time=1_700_000_000_000_000_000 + index,
                data=b"\x00",
            )
        writer.finish()
    return path
