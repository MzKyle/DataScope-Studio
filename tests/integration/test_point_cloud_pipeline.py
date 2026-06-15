from pathlib import Path

from typer.testing import CliRunner

from datascope_cli.main import app as cli_app
from datascope_core.workspace import Workspace


def test_workspace_point_cloud_to_rerun_artifacts(tmp_path: Path) -> None:
    cloud_dir = _make_point_cloud_fixture(tmp_path)
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Point Cloud Pipeline")
    source = workspace.add_source(project["id"], str(cloud_dir))
    inspection = workspace.inspect_source(source["id"])
    templates = workspace.suggest_templates(source["id"])
    spec = workspace.suggest_mapping(source["id"], template_id="robotics_debug")
    mapping = workspace.save_mapping(project["id"], source["id"], spec)

    result = workspace.build_recording(
        project["id"],
        source["id"],
        mapping_id=mapping["id"],
        output_name="cloud_run",
        template_id="robotics_debug",
    )

    assert source["type"] == "point_cloud"
    assert inspection["streams"][0]["semantic_type"] == "points3d"
    assert templates[0]["template_id"] == "robotics_debug"
    assert Path(result["recording_path"]).exists()
    assert Path(result["blueprint_path"]).exists()


def test_workspace_defaults_artifact_names_to_source_folder(tmp_path: Path) -> None:
    cloud_dir = _make_point_cloud_fixture(tmp_path)
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Point Cloud Default Name")
    source = workspace.add_source(project["id"], str(cloud_dir))
    workspace.inspect_source(source["id"])

    result = workspace.build_recording(
        project["id"],
        source["id"],
        template_id="robotics_debug",
    )

    assert Path(result["recording_path"]).name == "clouds.rrd"
    assert Path(result["blueprint_path"]).name == "clouds.rbl"


def test_cli_point_cloud_inspect(tmp_path: Path, monkeypatch) -> None:
    cloud_dir = _make_point_cloud_fixture(tmp_path)
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "cli_workspace"))
    runner = CliRunner()

    inspect_result = runner.invoke(cli_app, ["inspect", str(cloud_dir)])

    assert inspect_result.exit_code == 0
    assert "Source type: point_cloud" in inspect_result.output
    assert "Point clouds: 2" in inspect_result.output


def _make_point_cloud_fixture(tmp_path: Path) -> Path:
    cloud_dir = tmp_path / "clouds"
    cloud_dir.mkdir()
    _write_ply(cloud_dir / "1780166165355.ply", [[0, 0, 0], [1, 0, 0], [0, 1, 0]])
    _write_ply(cloud_dir / "1780166166355.ply", [[0, 0, 1], [1, 1, 1], [2, 2, 2]])
    return cloud_dir


def _write_ply(path: Path, points: list[list[float]]) -> None:
    lines = [
        "ply",
        "format ascii 1.0",
        f"element vertex {len(points)}",
        "property float x",
        "property float y",
        "property float z",
        "end_header",
    ]
    lines.extend(" ".join(str(value) for value in point) for point in points)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
