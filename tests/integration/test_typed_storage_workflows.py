from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from datascope_api.main import app as api_app
from datascope_cli.main import app as cli_app
from datascope_core.workspace import Workspace
from tests.api_helpers import wait_for_job
from tests.unit.test_rerun_artifacts import _install_fake_artifact_writers, _mapped_csv_workspace


@pytest.mark.parametrize("storage", ["legacy", "typed_sqlite"])
def test_core_build_default_and_opt_in(tmp_path, monkeypatch, storage):
    workspace, project, source, mapping = _mapped_csv_workspace(tmp_path)
    _install_fake_artifact_writers(monkeypatch, recording_payload=b"rrd", blueprint_payload=b"rbl")
    kwargs = {} if storage == "legacy" else {"query_storage": storage}
    result = workspace.build_recording(project["id"], source["id"], mapping["id"], **kwargs)
    with workspace._connect() as conn:
        count = conn.execute("SELECT count(*) FROM typed_indexes").fetchone()[0]
    assert count == (storage == "typed_sqlite")
    assert len(workspace.custom_query(project["id"])["rows"]) == 2
    assert Path(result["recording_path"]).exists()


def test_failed_build_cleans_committed_typed_index(tmp_path, monkeypatch):
    workspace, project, source, mapping = _mapped_csv_workspace(tmp_path)
    _install_fake_artifact_writers(monkeypatch, recording_payload=b"rrd", blueprint_payload=b"rbl")
    original = workspace._index_recording

    def fail_after_commit(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("after index commit")

    monkeypatch.setattr(workspace, "_index_recording", fail_after_commit)
    with pytest.raises(RuntimeError, match="after index"):
        workspace.build_recording(project["id"], source["id"], mapping["id"], query_storage="typed_sqlite")
    with workspace._connect() as conn:
        for table in ("recordings", "typed_indexes", "typed_datasets", "typed_schemas", "typed_bindings", "query_rows"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_api_typed_build_and_invalid_option(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(root))
    path = tmp_path / "values.csv"
    path.write_text("time,battery,state\n0,0.9,idle\n1,0.1,error\n", encoding="utf-8")
    with TestClient(api_app) as client:
        project = client.post("/api/projects", json={"name": "Typed API"}).json()
        source = client.post(f"/api/projects/{project['id']}/sources", json={"path": str(path)}).json()
        client.post(f"/api/sources/{source['id']}/inspect")
        request = {"project_id": project["id"], "source_id": source["id"], "query_storage": "unknown"}
        assert client.post("/api/recordings/build", json=request).status_code == 422
        request["query_storage"] = "typed_sqlite"
        response = client.post("/api/recordings/build", json=request)
        assert response.status_code == 202
        job = wait_for_job(client, response.json()["id"])
        assert job["status"] == "succeeded", job
        assert job["payload"]["query_storage"] == "typed_sqlite"
    workspace = Workspace(root)
    assert workspace.run_query(project["id"], "low_battery")["rows"][0]["value"] == 0.1
    with workspace._connect() as conn:
        assert conn.execute("SELECT count(*) FROM typed_indexes").fetchone()[0] == 1


def test_cli_typed_import(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(root))
    path = tmp_path / "values.csv"
    path.write_text("time,battery,state\n0,0.9,idle\n1,0.1,error\n", encoding="utf-8")
    result = CliRunner().invoke(cli_app, ["import", str(path), "--project", "Typed CLI",
                                        "--query-storage", "typed_sqlite", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["job"]["payload"]["query_storage"] == "typed_sqlite"
    workspace = Workspace(root)
    with workspace._connect() as conn:
        assert conn.execute("SELECT count(*) FROM typed_indexes").fetchone()[0] == 1


def test_project_package_keeps_existing_index_export_policy(tmp_path, monkeypatch):
    workspace, project, source, mapping = _mapped_csv_workspace(tmp_path)
    _install_fake_artifact_writers(monkeypatch, recording_payload=b"rrd", blueprint_payload=b"rbl")
    workspace.build_recording(project["id"], source["id"], mapping["id"], query_storage="typed_sqlite")
    exported = workspace.export_project(project["id"], str(tmp_path / "project.zip"))
    imported = Workspace(tmp_path / "imported")
    result = imported.import_project_package(exported["path"])
    assert len(result["recordings"]) == 1
    # Existing project packages carry artifacts/metadata, not query indexes.
    with imported._connect() as conn:
        assert conn.execute("SELECT count(*) FROM typed_indexes").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM query_rows").fetchone()[0] == 0


def test_interrupted_typed_job_cleanup_uses_exact_owner(tmp_path, monkeypatch):
    workspace, project, source, mapping = _mapped_csv_workspace(tmp_path)
    _install_fake_artifact_writers(monkeypatch, recording_payload=b"rrd", blueprint_payload=b"rbl")
    result = workspace.build_recording(project["id"], source["id"], mapping["id"], query_storage="typed_sqlite")
    original_job = workspace.get_job(result["job_id"])
    # A second job with the same artifact name must leave the successful build intact.
    other = workspace.enqueue_build_recording(project["id"], source["id"], query_storage="typed_sqlite")
    workspace.cancel_job(other["id"])
    assert workspace.get_recording(result["recording_id"])
    assert Path(result["recording_path"]).exists()
    # Simulate a process dying after index commit but before publishing job success.
    with workspace._connect() as conn:
        conn.execute("UPDATE jobs SET status = 'running', result_json = NULL WHERE id = ?", (original_job["id"],))
    workspace.interrupt_running_jobs([original_job["id"]])
    with workspace._connect() as conn:
        for table in ("recordings", "typed_indexes", "typed_datasets", "typed_schemas"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    assert not Path(result["recording_path"]).exists()


def test_cancel_reaches_writer_while_sqlite_write_lock_is_held(tmp_path, monkeypatch):
    import threading
    import datascope_core.workspace_query as query_module
    from datascope_core.workspace_jobs import JobCancelled

    workspace, project, source, mapping = _mapped_csv_workspace(tmp_path)
    _install_fake_artifact_writers(monkeypatch, recording_payload=b"rrd", blueprint_payload=b"rbl")
    job = workspace.enqueue_build_recording(project["id"], source["id"], mapping["id"],
                                            query_storage="typed_sqlite")
    assert workspace.claim_job(job["id"], "worker")
    entered = threading.Event()
    original = query_module.build_typed_index

    def slow_sql(conn, *args, **kwargs):
        entered.set()
        conn.execute("WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<10000000) SELECT sum(x) FROM n").fetchone()
        return original(conn, *args, **kwargs)

    monkeypatch.setattr(query_module, "build_typed_index", slow_sql)
    errors = []

    def execute():
        try:
            workspace.execute_job(job["id"], "worker")
        except Exception as error:
            errors.append(error)

    thread = threading.Thread(target=execute)
    thread.start()
    try:
        assert entered.wait(10)
        workspace.cancel_job(job["id"])
    finally:
        thread.join(10)
    assert not thread.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], JobCancelled), errors
    assert workspace.get_job(job["id"])["status"] == "cancelled"
    with workspace._connect() as conn:
        assert conn.execute("SELECT count(*) FROM recordings").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM typed_indexes").fetchone()[0] == 0
