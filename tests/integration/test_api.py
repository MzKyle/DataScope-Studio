import logging
from pathlib import Path

from fastapi.testclient import TestClient

from datascope_api.main import app
from tests.api_helpers import wait_for_job


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_api_logs_file_open_errors(tmp_path: Path, monkeypatch, caplog) -> None:
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "workspace"))
    client = TestClient(app)
    project = client.post("/api/projects", json={"name": "Logging"}).json()
    missing = tmp_path / "missing.ply"

    with caplog.at_level(logging.WARNING, logger="uvicorn.error.datascope"):
        response = client.post(
            f"/api/projects/{project['id']}/sources",
            json={"path": str(missing)},
        )

    assert response.status_code == 400
    assert "api_error method=POST" in caplog.text
    assert f"path=/api/projects/{project['id']}/sources" in caplog.text
    assert "code=bad_request" in caplog.text
    assert "missing.ply" in caplog.text


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
    assert result["artifact_info"]["converter"] == "rerun_python_sdk"
    assert result["artifact_info"]["recording_size_bytes"] > 0
    recording_response = client.get(f"/api/recordings/{result['recording_id']}")
    assert recording_response.status_code == 200
    assert recording_response.json()["params"]["rerun_artifact"] == result["artifact_info"]

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


def test_api_batch_management_retry_and_job_settings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "batch_workspace"))
    client = TestClient(app)
    project = client.post("/api/projects", json={"name": "Batch API"}).json()
    good_path = tmp_path / "good.csv"
    bad_path = tmp_path / "recoverable.jsonl"
    good_path.write_text((FIXTURES / "sample_sensor.csv").read_text(), encoding="utf-8")
    bad_path.write_text('{"timestamp": 1, "value": 2}\nnot-json\n', encoding="utf-8")

    settings = client.get("/api/jobs/settings")
    assert settings.status_code == 200
    patched = client.patch("/api/jobs/settings", json={"max_workers": 2})
    assert patched.status_code == 200
    assert patched.json()["max_workers"] == 2

    estimate = client.post(
        f"/api/projects/{project['id']}/estimates/batch-import",
        json={"patterns": [str(good_path), str(bad_path)], "storage_mode": "copy"},
    )
    assert estimate.status_code == 200
    assert estimate.json()["kind"] == "batch_import"

    response = client.post(
        "/api/batch/import",
        json={
            "project_id": project["id"],
            "patterns": [str(good_path), str(bad_path)],
            "template_id": "sensor_monitor",
            "output_prefix": "api_retry",
        },
    )
    assert response.status_code == 202
    failed_job = wait_for_job(client, response.json()["id"])
    assert failed_job["status"] == "failed"
    batch_id = failed_job["resource_id"]

    batches = client.get(f"/api/projects/{project['id']}/batches")
    assert batches.status_code == 200
    assert batches.json()[0]["id"] == batch_id

    detail = client.get(f"/api/batch/{batch_id}")
    assert detail.status_code == 200
    failed_item = next(item for item in detail.json()["items"] if item["status"] == "failed")

    bad_path.write_text('{"timestamp": 1, "value": 2}\n', encoding="utf-8")
    retry = client.post(f"/api/batch/{batch_id}/items/{failed_item['id']}/retry")
    assert retry.status_code == 202
    retry_job = wait_for_job(client, retry.json()["id"])
    assert retry_job["status"] == "succeeded"

    retried = client.get(f"/api/batch/{batch_id}").json()
    assert retried["status"] == "succeeded"
    assert retried["succeeded"] == 2
    assert next(item for item in retried["items"] if item["id"] == failed_item["id"])[
        "attempt"
    ] == 2


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


def test_api_headerless_csv_and_custom_artifact_directory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "workspace"))
    source_path = tmp_path / "pose.csv"
    source_path.write_text(
        "1781733042228,1,2,3,0.1,0.2,0.3\n"
        "1781733042271,4,5,6,0.4,0.5,0.6\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "rerun-artifacts"
    client = TestClient(app)
    project = client.post("/api/projects", json={"name": "Headerless CSV"}).json()
    source = client.post(
        f"/api/projects/{project['id']}/sources",
        json={
            "path": str(source_path),
            "import_options": {
                "csv": {
                    "header_mode": "no_header",
                    "column_names": ["timestamp", "x", "y", "z", "rx", "ry", "rz"],
                }
            },
        },
    ).json()
    inspection = client.post(f"/api/sources/{source['id']}/inspect").json()
    mapping = client.get(f"/api/sources/{source['id']}/mapping/suggest").json()["mapping"]
    saved = client.post(
        f"/api/sources/{source['id']}/mapping",
        json={"mapping": mapping},
    ).json()

    response = client.post(
        "/api/recordings/build",
        json={
            "project_id": project["id"],
            "source_id": source["id"],
            "mapping_id": saved["id"],
            "output_name": "pose",
            "output_dir": str(output_dir),
        },
    )
    job = wait_for_job(client, response.json()["id"])

    assert inspection["schema_profile"]["field_names"] == [
        "timestamp",
        "x",
        "y",
        "z",
        "rx",
        "ry",
        "rz",
    ]
    assert job["status"] == "succeeded"
    assert Path(job["result"]["recording_path"]) == output_dir / "pose.rrd"
    assert Path(job["result"]["blueprint_path"]) == output_dir / "pose.rbl"
