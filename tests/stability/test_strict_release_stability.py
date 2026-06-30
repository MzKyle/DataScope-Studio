from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from datascope_api.main import app as api_app
from datascope_core.workspace import Workspace
from tests.api_helpers import wait_for_job


pytestmark = pytest.mark.skipif(
    os.environ.get("DATASCOPE_STRICT_STABILITY") != "1",
    reason="Set DATASCOPE_STRICT_STABILITY=1 to run release stability tests.",
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
RSS_CUSHION_BYTES = 64 * 1024 * 1024


def test_repeated_import_build_query_loop(tmp_path: Path) -> None:
    loops = _env_int("DATASCOPE_STABILITY_LOOPS", 50)
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Strict Loop")
    recording_paths: set[str] = set()
    start_rss = None

    for index in range(loops):
        source = workspace.add_source(project["id"], str(FIXTURES / "sample_sensor.csv"))
        workspace.inspect_source(source["id"])
        mapping = workspace.save_mapping(
            project["id"],
            source["id"],
            workspace.suggest_mapping(source["id"]),
        )
        result = workspace.build_recording(
            project["id"],
            source["id"],
            mapping_id=mapping["id"],
            output_name=f"strict_loop_{index:03d}",
        )
        query = workspace.run_query(
            project["id"],
            "low_battery",
            recording_ids=[result["recording_id"]],
            params={"threshold": 0.925},
        )

        assert result["status"] == "succeeded"
        assert Path(result["recording_path"]).exists()
        assert Path(result["blueprint_path"]).exists()
        assert result["recording_path"] not in recording_paths
        assert query["rows"]
        recording_paths.add(result["recording_path"])
        if index == 0:
            start_rss = _current_rss_bytes()

    assert len(workspace.list_recordings(project["id"])) == loops
    _assert_memory_growth_within_limit(start_rss, _current_rss_bytes())


def test_batch_import_retry_and_worker_settings_are_stable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "api_workspace"))
    client = TestClient(api_app)
    project = client.post("/api/projects", json={"name": "Strict Batch"}).json()

    for workers in (1, 2, 4):
        patch = client.patch("/api/jobs/settings", json={"max_workers": workers})
        assert patch.status_code == 200
        assert patch.json()["max_workers"] == workers

        first = tmp_path / f"worker_{workers}_first.csv"
        second = tmp_path / f"worker_{workers}_second.csv"
        first.write_text((FIXTURES / "sample_sensor.csv").read_text(), encoding="utf-8")
        second.write_text((FIXTURES / "sample_sensor.csv").read_text(), encoding="utf-8")

        response = client.post(
            "/api/batch/import",
            json={
                "project_id": project["id"],
                "patterns": [str(first), str(second)],
                "template_id": "sensor_monitor",
                "output_prefix": f"worker_{workers}",
            },
        )
        assert response.status_code == 202
        job = wait_for_job(client, response.json()["id"], timeout=30)
        assert job["status"] == "succeeded"
        assert job["result"]["succeeded"] == 2

    bad = tmp_path / "recoverable.jsonl"
    good = tmp_path / "retry_good.csv"
    bad.write_text('{"timestamp": 1, "value": 2}\nnot-json\n', encoding="utf-8")
    good.write_text((FIXTURES / "sample_sensor.csv").read_text(), encoding="utf-8")
    response = client.post(
        "/api/batch/import",
        json={
            "project_id": project["id"],
            "patterns": [str(good), str(bad)],
            "template_id": "sensor_monitor",
            "output_prefix": "retry",
        },
    )
    assert response.status_code == 202
    failed_job = wait_for_job(client, response.json()["id"], timeout=30)
    assert failed_job["status"] == "failed"

    bad.write_text('{"timestamp": 1, "value": 2}\n', encoding="utf-8")
    detail = client.get(f"/api/batch/{failed_job['resource_id']}").json()
    failed_item = next(item for item in detail["items"] if item["status"] == "failed")
    retry = client.post(f"/api/batch/{failed_job['resource_id']}/items/{failed_item['id']}/retry")
    assert retry.status_code == 202
    retry_job = wait_for_job(client, retry.json()["id"], timeout=30)
    assert retry_job["status"] == "succeeded"


def test_api_health_and_core_requests_remain_stable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "health_workspace"))
    client = TestClient(api_app)
    assert client.get("/api/health").json() == {"status": "ok"}
    start_rss = _current_rss_bytes()

    duration = _env_int("DATASCOPE_HEALTH_DURATION_SECONDS", 1800)
    interval = max(1, _env_int("DATASCOPE_HEALTH_INTERVAL_SECONDS", 5))
    deadline = time.monotonic() + duration
    iterations = 0
    while True:
        health = client.get("/api/health")
        projects = client.get("/api/projects")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}
        assert projects.status_code == 200
        assert isinstance(projects.json(), list)
        iterations += 1
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(interval, remaining))

    assert iterations >= 1
    _assert_memory_growth_within_limit(start_rss, _current_rss_bytes())


def _env_int(name: str, default: int) -> int:
    value = int(os.environ.get(name, str(default)))
    if value < 1:
        raise AssertionError(f"{name} must be >= 1")
    return value


def _current_rss_bytes() -> int | None:
    statm = Path("/proc/self/statm")
    if not statm.exists():
        return None
    pages = int(statm.read_text(encoding="utf-8").split()[1])
    return pages * os.sysconf("SC_PAGE_SIZE")


def _assert_memory_growth_within_limit(start_rss: int | None, end_rss: int | None) -> None:
    if start_rss is None or end_rss is None:
        return
    limit = max(int(start_rss * 1.2), start_rss + RSS_CUSHION_BYTES)
    assert end_rss <= limit
