from pathlib import Path

from datascope_core.workspace import Workspace


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_workspace_csv_to_rerun_artifacts(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Pipeline Test")
    source = workspace.add_source(project["id"], str(FIXTURES / "sample_sensor.csv"))
    inspection = workspace.inspect_source(source["id"])
    spec = workspace.suggest_mapping(source["id"])
    saved_mapping = workspace.save_mapping(project["id"], source["id"], spec)

    result = workspace.build_recording(
        project["id"],
        source["id"],
        mapping_id=saved_mapping["id"],
        output_name="sample_sensor",
    )

    assert len(inspection["streams"]) >= 4
    assert result["status"] == "succeeded"
    assert Path(result["recording_path"]).exists()
    assert Path(result["blueprint_path"]).exists()
    assert workspace.get_job(result["job_id"])["status"] == "succeeded"

