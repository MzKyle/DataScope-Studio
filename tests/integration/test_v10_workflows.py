import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from datascope_api.main import app as api_app
from datascope_core.workspace import Workspace
from tests.api_helpers import wait_for_job


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_batch_import_compare_time_sync_and_project_export(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("V10 Project")

    batch = workspace.batch_import(
        project["id"],
        [str(FIXTURES / "sample_sensor.csv"), str(FIXTURES / "sample_sensor.jsonl")],
        template_id="sensor_monitor",
        output_prefix="batch",
    )
    recording_ids = [item["recording_id"] for item in batch["items"] if item["recording_id"]]
    compare = workspace.compare(project["id"], recording_ids, metric_keys=["battery"])
    export = workspace.export_project(project["id"])
    time_sync = workspace.run_query(project["id"], "time_sync", recording_ids, {})

    assert batch["status"] == "succeeded"
    assert len(recording_ids) == 2
    assert any(row["key"] == "battery" for row in compare["rows"])
    assert time_sync["columns"] == ["recording_id", "time", "entity_path", "key", "value"]
    assert Path(export["path"]).exists()
    with zipfile.ZipFile(export["path"]) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["project"]["id"] == project["id"]
    assert len(manifest["recordings"]) == 2


def test_project_package_import_restores_recordings(tmp_path: Path) -> None:
    source_workspace = Workspace(tmp_path / "source_workspace")
    project = source_workspace.create_project("Packaged Project")
    source = source_workspace.add_source(project["id"], str(FIXTURES / "sample_sensor.csv"))
    source_workspace.inspect_source(source["id"])
    result = source_workspace.build_recording(
        project["id"],
        source["id"],
        output_name="packaged_run",
        template_id="sensor_monitor",
    )
    package = source_workspace.export_project(project["id"])

    target_workspace = Workspace(tmp_path / "target_workspace")
    imported = target_workspace.import_project_package(package["path"])
    imported_again = target_workspace.import_project_package(package["path"])

    assert imported["project"]["name"] == "Packaged Project"
    assert imported["recording_ids"]
    assert imported["recording_ids"][0] == result["recording_id"]
    assert imported_again["project"]["id"] != imported["project"]["id"]
    recording = imported["recordings"][0]
    assert Path(recording["path"]).exists()
    assert Path(recording["blueprint_path"]).exists()
    assert str(tmp_path / "target_workspace") in recording["path"]


def test_project_export_uses_visible_default_and_accepts_directory(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    workspace = Workspace()
    project = workspace.create_project("Visible Export")

    default_export = workspace.export_project(project["id"])
    custom_export = workspace.export_project(project["id"], output_path=str(tmp_path / "custom_exports"))

    assert Path(default_export["path"]).parent == home / "DataScope Studio Exports"
    assert Path(default_export["path"]).suffix == ".zip"
    assert Path(custom_export["path"]).parent == tmp_path / "custom_exports"
    assert Path(custom_export["path"]).suffix == ".zip"


def test_api_template_plugin_batch_compare_and_project_export(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "api_workspace"))
    client = TestClient(api_app)
    project = client.post("/api/projects", json={"name": "API V10"}).json()

    templates = client.get("/api/templates")
    assert templates.status_code == 200
    assert any(item["id"] == "experiment_compare" for item in templates.json())

    plugin_dir = _make_api_plugin(tmp_path)
    plugin_response = client.post("/api/plugins/install", json={"path": str(plugin_dir)})
    assert plugin_response.status_code == 200
    assert plugin_response.json()["id"] == "api_dummy_plugin"

    batch_response = client.post(
        "/api/batch/import",
        json={
            "project_id": project["id"],
            "patterns": [str(FIXTURES / "sample_sensor.csv")],
            "template_id": "sensor_monitor",
            "output_prefix": "api_batch",
        },
    )
    assert batch_response.status_code == 202
    batch_job = wait_for_job(client, batch_response.json()["id"])
    assert batch_job["status"] == "succeeded"
    recording_id = batch_job["result"]["items"][0]["recording_id"]

    compare_response = client.post(
        "/api/compare",
        json={"project_id": project["id"], "recording_ids": [recording_id], "metric_keys": ["battery"]},
    )
    assert compare_response.status_code == 200
    assert compare_response.json()["rows"]

    export_response = client.post(f"/api/projects/{project['id']}/export", json={})
    assert export_response.status_code == 200
    assert Path(export_response.json()["path"]).exists()

    import_response = client.post("/api/projects/import", json={"path": export_response.json()["path"]})
    assert import_response.status_code == 200
    assert import_response.json()["recordings"]


def _make_api_plugin(tmp_path: Path) -> Path:
    plugin_dir = tmp_path / "api_dummy_plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yaml").write_text(
        """
id: api_dummy_plugin
name: API Dummy Plugin
version: 1.0.0
entrypoints:
  adapters:
    dummy: adapter:ApiDummyAdapter
""",
        encoding="utf-8",
    )
    (plugin_dir / "adapter.py").write_text(
        """
class ApiDummyAdapter:
    adapter_id = "api_dummy"
    display_name = "API Dummy"
    supported_extensions = [".apidummy"]
""",
        encoding="utf-8",
    )
    return plugin_dir
