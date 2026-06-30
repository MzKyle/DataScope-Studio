from pathlib import Path

from typer.testing import CliRunner

from datascope_cli.main import app as cli_app
from datascope_core.workspace import Workspace


def test_workspace_text_log_to_rerun_artifacts_and_query_index(tmp_path: Path) -> None:
    log_path = tmp_path / "run.log"
    log_path.write_text(
        "INFO boot complete\n"
        "WARN battery low\n"
        "ERROR motor stalled\n",
        encoding="utf-8",
    )
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Text Log Pipeline")
    source = workspace.add_source(project["id"], str(log_path))
    inspection = workspace.inspect_source(source["id"])
    spec = workspace.suggest_mapping(source["id"], template_id="sensor_monitor")
    mapping = workspace.save_mapping(project["id"], source["id"], spec)

    result = workspace.build_recording(
        project["id"],
        source["id"],
        mapping_id=mapping["id"],
        output_name="text_log_run",
        template_id="sensor_monitor",
    )
    query_result = workspace.run_query(project["id"], "find_errors")

    assert source["type"] == "text_table"
    assert inspection["source"]["metadata"]["text"]["mode"] == "log"
    assert any(stream["semantic_type"] == "text_log" for stream in inspection["streams"])
    assert Path(result["recording_path"]).exists()
    assert Path(result["blueprint_path"]).exists()
    assert result["artifact_info"]["converter"] == "rerun_python_sdk"
    assert result["artifact_info"]["recording_size_bytes"] > 0
    assert any("ERROR motor stalled" in str(row["value"]) for row in query_result["rows"])


def test_cli_text_table_inspect(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "samples.tsv"
    path.write_text("time\tvoltage\n0\t12.4\n1\t11.8\n", encoding="utf-8")
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "cli_workspace"))
    runner = CliRunner()

    inspect_result = runner.invoke(cli_app, ["inspect", str(path)])

    assert inspect_result.exit_code == 0
    assert "Source type: text_table" in inspect_result.output
    assert "Rows: 2" in inspect_result.output
    assert "Columns: time, voltage" in inspect_result.output
