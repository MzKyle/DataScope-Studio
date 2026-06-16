from pathlib import Path

from fastapi.testclient import TestClient

from datascope_api.main import app
from tests.api_helpers import wait_for_job


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_api_project_source_mapping_build_flow(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "workspace"))
    client = TestClient(app)

    project_response = client.post("/api/projects", json={"name": "API Test"})
    assert project_response.status_code == 200
    project = project_response.json()

    source_response = client.post(
        f"/api/projects/{project['id']}/sources",
        json={"path": str(FIXTURES / "sample_sensor.jsonl")},
    )
    assert source_response.status_code == 200
    source = source_response.json()

    inspect_response = client.post(f"/api/sources/{source['id']}/inspect")
    assert inspect_response.status_code == 200
    assert inspect_response.json()["streams"]

    mapping_response = client.get(f"/api/sources/{source['id']}/mapping/suggest")
    assert mapping_response.status_code == 200
    mapping_payload = mapping_response.json()["mapping"]

    save_mapping_response = client.post(
        f"/api/sources/{source['id']}/mapping",
        json={"mapping": mapping_payload},
    )
    assert save_mapping_response.status_code == 200
    mapping = save_mapping_response.json()

    build_response = client.post(
        "/api/recordings/build",
        json={
            "project_id": project["id"],
            "source_id": source["id"],
            "mapping_id": mapping["id"],
            "template_id": "sensor_monitor",
            "output_name": "api_run",
        },
    )
    assert build_response.status_code == 202
    job = wait_for_job(client, build_response.json()["id"])
    assert job["status"] == "succeeded"
    result = job["result"]
    assert Path(result["recording_path"]).exists()
    assert Path(result["blueprint_path"]).exists()

    conflict_response = client.post(
        "/api/recordings/build",
        json={
            "project_id": project["id"],
            "source_id": source["id"],
            "mapping_id": mapping["id"],
            "template_id": "sensor_monitor",
            "output_name": "api_run",
        },
    )
    assert conflict_response.status_code == 202
    conflict_job = wait_for_job(client, conflict_response.json()["id"])
    assert conflict_job["status"] == "failed"
    error = conflict_job["error"]
    assert error["code"] == "artifact_name_conflict"
    assert error["output_name"] == "api_run"
    assert result["recording_path"] in error["paths"]
    assert result["blueprint_path"] in error["paths"]


def test_api_build_defaults_artifact_names_to_source_name(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "workspace"))
    client = TestClient(app)

    project = client.post("/api/projects", json={"name": "API Default Name"}).json()
    source = client.post(
        f"/api/projects/{project['id']}/sources",
        json={"path": str(FIXTURES / "sample_sensor.jsonl")},
    ).json()
    client.post(f"/api/sources/{source['id']}/inspect")

    response = client.post(
        "/api/recordings/build",
        json={
            "project_id": project["id"],
            "source_id": source["id"],
            "template_id": "sensor_monitor",
        },
    )

    assert response.status_code == 202
    job = wait_for_job(client, response.json()["id"])
    assert job["status"] == "succeeded"
    result = job["result"]
    assert Path(result["recording_path"]).name == "sample_sensor.rrd"
    assert Path(result["blueprint_path"]).name == "sample_sensor.rbl"
