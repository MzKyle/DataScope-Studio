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


def test_workspace_fanuc_millisecond_timestamp_csv_to_rerun_artifacts(tmp_path: Path) -> None:
    fanuc_csv = tmp_path / "fanuc_robot_info.csv"
    fanuc_csv.write_text(
        "\n".join(
            [
                "timestamp,main_pgm,cur_pgm,cur_seq,ncstatus,mode,voltage1,current1,alarm_msg",
                "1780523938361,MAIN,MAIN,5,START,0,0,0,",
                "1780523938484,MAIN,WELDFUN,3,START,0,7.14377,111.056,",
                "1780523938603,MAIN,WELDFUN,3,START,0,14.4958,223.173,",
            ]
        ),
        encoding="utf-8",
    )
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("FANUC Test")
    source = workspace.add_source(project["id"], str(fanuc_csv))
    workspace.inspect_source(source["id"])
    spec = workspace.suggest_mapping(source["id"])
    saved_mapping = workspace.save_mapping(project["id"], source["id"], spec)

    result = workspace.build_recording(
        project["id"],
        source["id"],
        mapping_id=saved_mapping["id"],
        output_name="fanuc_robot_info",
    )
    query = workspace.run_query(project["id"], "state_duration", [result["recording_id"]], {})

    assert result["status"] == "succeeded"
    assert Path(result["recording_path"]).exists()
    assert Path(result["blueprint_path"]).exists()
    assert query["rows"]
