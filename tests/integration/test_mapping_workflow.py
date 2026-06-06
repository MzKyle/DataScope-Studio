from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from datascope_api.main import app
from datascope_core.mapping import mapping_from_yaml_dict
from datascope_core.workspace import Workspace
from datascope_cli.main import app as cli_app


def _write_sensor(path: Path, *, dotted: bool = False) -> None:
    prefix = "robot." if dotted else "robot_"
    path.write_text(
        f"timestamp,battery,{prefix}x,{prefix}y,{prefix}z\n"
        "1,0.9,1,2,3\n"
        "2,0.8,4,5,6\n",
        encoding="utf-8",
    )


def test_workspace_mapping_template_apply_diff_and_schema_cache(tmp_path: Path) -> None:
    left_path = tmp_path / "left.csv"
    right_path = tmp_path / "right.csv"
    _write_sensor(left_path)
    _write_sensor(right_path, dotted=True)
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Mapping Product")

    left = workspace.add_source(project["id"], str(left_path))
    right = workspace.add_source(project["id"], str(right_path))
    workspace.inspect_source(left["id"])
    workspace.inspect_source(right["id"])
    spec = workspace.suggest_mapping(left["id"])
    mapping = workspace.save_mapping(project["id"], left["id"], spec)
    confirmed = workspace.confirm_mapping(mapping["id"])
    template = workspace.create_mapping_template(
        "Robot Sensor",
        left["id"],
        mapping["id"],
        template_id="robot_sensor",
    )

    applied = workspace.apply_mapping_template(template["id"], right["id"])
    applied_spec = mapping_from_yaml_dict({"mapping": applied["mapping"]})
    applied_spec.streams[0]["entity_path"] = "/custom/saved/path"
    workspace.save_mapping(project["id"], right["id"], applied_spec)
    diff = workspace.diff_mapping_template(
        project["id"],
        template["id"],
        left["id"],
        right["id"],
    )
    reopened = Workspace(tmp_path / "workspace")

    assert workspace.get_schema_profile(left["id"])["field_names"][0] == "timestamp"
    assert mapping["user_confirmed"] is False
    assert confirmed["mapping"]["user_confirmed"] is True
    assert workspace.get_source(left["id"])["status"] == "mapped"
    assert applied["validation"]["valid"] is True
    assert any("source_fields" in row["changes"] for row in diff["rows"])
    assert any("entity_path" in row["changes"] for row in diff["rows"])
    assert reopened.get_mapping_template("robot_sensor")["name"] == "Robot Sensor"


def test_api_mapping_template_flow_and_validation_gate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "workspace"))
    source_path = tmp_path / "sensor.csv"
    _write_sensor(source_path)
    client = TestClient(app)
    project = client.post("/api/projects", json={"name": "Mapping API"}).json()
    source = client.post(
        f"/api/projects/{project['id']}/sources",
        json={"path": str(source_path)},
    ).json()
    inspection = client.post(f"/api/sources/{source['id']}/inspect")
    assert inspection.status_code == 200
    assert inspection.json()["schema_profile"]["source_family"] == "tabular"

    mapping_payload = client.get(
        f"/api/sources/{source['id']}/mapping/suggest"
    ).json()["mapping"]
    saved = client.post(
        f"/api/sources/{source['id']}/mapping",
        json={"mapping": mapping_payload},
    ).json()
    template = client.post(
        "/api/mapping-templates",
        json={
            "name": "API Mapping",
            "source_id": source["id"],
            "mapping_id": saved["id"],
            "template_id": "api_mapping",
        },
    )
    assert template.status_code == 200

    applied = client.post(
        "/api/mapping-templates/api_mapping/apply",
        json={"source_id": source["id"]},
    )
    assert applied.status_code == 200
    assert applied.json()["validation"]["valid"] is True

    invalid_mapping = dict(mapping_payload)
    invalid_mapping["streams"] = [dict(stream) for stream in mapping_payload["streams"]]
    invalid_mapping["streams"][0]["entity_path"] = "invalid path"
    invalid_saved = client.post(
        f"/api/sources/{source['id']}/mapping",
        json={"mapping": invalid_mapping},
    ).json()
    blocked = client.post(
        "/api/recordings/build",
        json={
            "project_id": project["id"],
            "source_id": source["id"],
            "mapping_id": invalid_saved["id"],
            "template_id": "sensor_monitor",
            "output_name": "blocked",
        },
    )

    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "mapping_validation_failed"
    assert blocked.json()["error"]["validation"]["valid"] is False


def test_cli_mapping_validate_and_template_list(tmp_path: Path, monkeypatch) -> None:
    workspace_path = tmp_path / "workspace"
    source_path = tmp_path / "sensor.csv"
    _write_sensor(source_path)
    workspace = Workspace(workspace_path)
    project = workspace.create_project("Mapping CLI")
    source = workspace.add_source(project["id"], str(source_path))
    workspace.inspect_source(source["id"])
    spec = workspace.suggest_mapping(source["id"])
    mapping = workspace.save_mapping(project["id"], source["id"], spec)
    workspace.create_mapping_template(
        "CLI Mapping",
        source["id"],
        mapping["id"],
        template_id="cli_mapping",
    )
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(workspace_path))
    runner = CliRunner()

    validation = runner.invoke(cli_app, ["mapping", "validate", mapping["id"]])
    templates = runner.invoke(cli_app, ["mapping", "template", "list"])

    assert validation.exit_code == 0
    assert "valid" in validation.output
    assert templates.exit_code == 0
    assert "cli_mapping" in templates.output
