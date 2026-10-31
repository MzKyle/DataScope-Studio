import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from datascope_api.main import app
from datascope_api.services import services
from datascope_core.workspace import Workspace
from datascope_core.workspace_diagnostics import _diagnostics_html


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.mark.parametrize("storage", ["legacy", "auto", "typed_sqlite"])
def test_quick_build_can_skip_all_query_writes(tmp_path, monkeypatch, storage):
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("DATASCOPE_QUICK_INSPECT_ROOT", str(tmp_path / "quick"))
    services.stop()
    try:
        with TestClient(app) as client:
            started = client.post("/api/quick-inspect", json={
                "path": str(FIXTURES / "sample_sensor.csv"),
            }).json()
            session = services.quick_inspect()._active
            def forbidden(*args, **kwargs):
                raise AssertionError("lightweight build must not invoke the query writer")
            monkeypatch.setattr(session.workspace, "_index_recording", forbidden)
            response = client.post(f"/api/quick-inspect/{started['session_id']}/build", json={
                "build_query_index": False, "query_storage": storage,
            })
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["query_index"] == {"storage": "none", "status": "skipped"}
            assert Path(result["recording_path"]).stat().st_size > 0
            assert Path(result["blueprint_path"]).stat().st_size > 0
            recording = session.workspace.get_recording(result["recording_id"])
            assert recording["params"]["query_index"] == result["query_index"]
            with sqlite3.connect(session.workspace.db_path) as connection:
                for table in ("query_rows", "typed_indexes", "typed_datasets", "typed_summaries"):
                    assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
            estimate = session.workspace.estimate_build(session.project_id, session.source_id,
                query_storage=storage, _build_query_index=False)
            assert estimate["query_storage"] == "none"
            assert "query_temporary" not in estimate["components"]
            assert "query_index_and_journal" not in estimate["components"]
            assert client.get("/api/projects").json() == []
    finally:
        services.stop()


def test_skipped_index_build_failure_cleans_own_artifacts(tmp_path, monkeypatch):
    workspace = Workspace(tmp_path)
    project = workspace.create_project("lightweight")
    source = workspace.add_source(project["id"], str(FIXTURES / "sample_sensor.csv"))
    workspace.inspect_source(source["id"])
    def fail(*args, **kwargs):
        raise RuntimeError("blueprint failed")
    monkeypatch.setattr("datascope_core.workspace.save_blueprint", fail)
    with pytest.raises(RuntimeError, match="blueprint failed"):
        workspace.build_recording(project["id"], source["id"], _build_query_index=False)
    assert workspace.list_recordings(project["id"]) == []
    project_path = Path(project["workspace_path"])
    assert not list((project_path / "recordings").glob("*.rrd"))
    assert not list((project_path / "blueprints").glob("*.rbl"))


def test_html_explains_rule_scope_without_mutating_structured_report():
    report = {"summary": {"health_score": 100}, "findings": []}
    rendered = _diagnostics_html(report)
    assert "Rule-check score: 100" in rendered
    assert "No rule matches" in rendered
    assert "not per-message" in rendered
    assert report == {"summary": {"health_score": 100}, "findings": []}


def test_lightweight_rrd_preserves_business_components_and_timelines(tmp_path):
    experimental = pytest.importorskip("rerun.experimental")
    if not hasattr(experimental, "RrdReader"):
        pytest.skip("Business-row decoding requires the supported 0.33 SDK")
    from benchmarks.rrd_contract import semantic_summary
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("parity")
    source = workspace.add_source(project["id"], str(FIXTURES / "sample_sensor.csv"))
    workspace.inspect_source(source["id"])
    spec = workspace.suggest_mapping(source["id"])
    saved = workspace.save_mapping(project["id"], source["id"], spec)
    full = workspace.build_recording(project["id"], source["id"], mapping_id=saved["id"], output_name="full")
    quick = workspace.build_recording(project["id"], source["id"], mapping_id=saved["id"], output_name="quick", _build_query_index=False)
    left = semantic_summary(full["recording_path"], tmp_path / "scratch")
    right = semantic_summary(quick["recording_path"], tmp_path / "scratch")
    assert left["sha256"] == right["sha256"]
    assert left["logical_component_rows"] > 0
