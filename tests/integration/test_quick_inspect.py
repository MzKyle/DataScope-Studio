from pathlib import Path

from fastapi.testclient import TestClient

from datascope_api.main import app
from datascope_api.services import services


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_quick_inspect_uses_isolated_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("DATASCOPE_QUICK_INSPECT_ROOT", str(tmp_path / "quick-inspect"))
    services.stop()
    try:
        with TestClient(app) as client:
            before = client.get("/api/projects").json()

            response = client.post(
                "/api/quick-inspect",
                json={"path": str(FIXTURES / "sample_sensor.csv")},
            )

            after = client.get("/api/projects").json()
    finally:
        services.stop()

    assert response.status_code == 200
    assert response.json()["session_id"].startswith("session_")
    assert after == before
    assert all(project["name"] != "Quick Inspect" for project in after)


def test_quick_inspect_starting_second_session_cleans_previous_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    quick_root = tmp_path / "quick-inspect"
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("DATASCOPE_QUICK_INSPECT_ROOT", str(quick_root))
    services.stop()
    try:
        with TestClient(app) as client:
            first = client.post(
                "/api/quick-inspect",
                json={"path": str(FIXTURES / "sample_sensor.csv")},
            ).json()
            first_root = quick_root / first["session_id"]
            assert first_root.exists()

            second = client.post(
                "/api/quick-inspect",
                json={"path": str(FIXTURES / "sample_sensor.csv")},
            ).json()
            second_root = quick_root / second["session_id"]

            assert not first_root.exists()
            assert second_root.exists()
    finally:
        services.stop()


def test_quick_inspect_import_reuses_mapping_preview_and_validation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("DATASCOPE_QUICK_INSPECT_ROOT", str(tmp_path / "quick-inspect"))
    services.stop()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/quick-inspect",
                json={
                    "path": str(FIXTURES / "sample_sensor.csv"),
                    "storage_mode": "copy",
                    "template_id": "sensor_monitor",
                },
            )
    finally:
        services.stop()

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"]["status"] == "inspected"
    assert payload["streams"]
    assert payload["template_id"] == "sensor_monitor"
    assert payload["template_matches"]
    assert payload["mapping"]["mapping"]["source"] == payload["source"]["id"]
    assert payload["saved_mapping"]["id"] == payload["mapping"]["mapping"]["id"]
    assert payload["preview"]["rows"]
    assert payload["schema_profile"]["source_id"] == payload["source"]["id"]
    assert "valid" in payload["validation"]


def test_quick_inspect_confirm_and_build_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("DATASCOPE_QUICK_INSPECT_ROOT", str(tmp_path / "quick-inspect"))
    services.stop()
    try:
        with TestClient(app) as client:
            started = client.post(
                "/api/quick-inspect",
                json={"path": str(FIXTURES / "sample_sensor.csv")},
            ).json()
            session_id = started["session_id"]
            mapping = started["mapping"]["mapping"]

            confirm = client.post(
                f"/api/quick-inspect/{session_id}/mapping/confirm",
                json={"mapping": mapping},
            )
            build = client.post(
                f"/api/quick-inspect/{session_id}/build",
                json={
                    "template_id": started["template_id"],
                    "output_name": "quick_run",
                },
            )
            result = build.json()
            recording_exists = Path(result["recording_path"]).exists()
            blueprint_exists = Path(result["blueprint_path"]).exists()
    finally:
        services.stop()

    assert confirm.status_code == 200
    assert confirm.json()["validation"]["valid"] is True
    assert build.status_code == 200
    assert result["status"] == "succeeded"
    assert result["job_id"] == ""
    assert recording_exists
    assert blueprint_exists


def test_quick_inspect_invalid_path_returns_structured_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("DATASCOPE_QUICK_INSPECT_ROOT", str(tmp_path / "quick-inspect"))
    services.stop()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/quick-inspect",
                json={"path": str(tmp_path / "missing.csv")},
            )
    finally:
        services.stop()

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_request"
