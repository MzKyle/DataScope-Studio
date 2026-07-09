from pathlib import Path
import json

from typer.testing import CliRunner

from datascope_core.workspace import Workspace
from datascope_cli.main import app


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_cli_inspect_prints_detected_streams() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["inspect", str(FIXTURES / "sample_sensor.csv")])

    assert result.exit_code == 0
    assert "Source type: csv" in result.output
    assert "Detected streams:" in result.output


def test_cli_import_builds_artifacts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "workspace"))
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "import",
            str(FIXTURES / "sample_sensor.csv"),
            "--project",
            "CLI Test",
            "--out",
            "cli_run",
        ],
    )

    assert result.exit_code == 0
    assert "Recording:" in result.output
    assert "Blueprint:" in result.output
    assert "Artifact sizes:" in result.output
    assert (tmp_path / "workspace").exists()


def test_cli_import_json_includes_artifact_info(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "workspace"))
    result = CliRunner().invoke(
        app,
        [
            "import",
            str(FIXTURES / "sample_sensor.csv"),
            "--project",
            "CLI JSON",
            "--out",
            "cli_json_run",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    artifact_info = payload["job"]["result"]["artifact_info"]
    assert artifact_info["converter"] == "rerun_python_sdk"
    assert artifact_info["recording_size_bytes"] > 0
    assert artifact_info["artifact_validation"] == "basic"
    assert artifact_info["rrd_optimize_profile"] == "none"


def test_cli_catalog_registration_requires_catalog_url(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "workspace"))

    result = CliRunner().invoke(
        app,
        [
            "import",
            str(FIXTURES / "sample_sensor.csv"),
            "--project",
            "CLI Catalog",
            "--catalog-dataset",
            "robot_runs",
        ],
    )

    assert result.exit_code != 0
    assert "--catalog-url is required" in result.output


def test_cli_import_defaults_artifact_names_to_source_name(tmp_path: Path, monkeypatch) -> None:
    workspace_path = tmp_path / "workspace"
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(workspace_path))

    result = CliRunner().invoke(
        app,
        [
            "import",
            str(FIXTURES / "sample_sensor.csv"),
            "--project",
            "CLI Default Name",
        ],
    )

    assert result.exit_code == 0
    assert len(list(workspace_path.rglob("sample_sensor.rrd"))) == 1
    assert len(list(workspace_path.rglob("sample_sensor.rbl"))) == 1


def test_cli_project_import_package(tmp_path: Path, monkeypatch) -> None:
    package_workspace = Workspace(tmp_path / "package_workspace")
    project = package_workspace.create_project("CLI Package")
    source = package_workspace.add_source(project["id"], str(FIXTURES / "sample_sensor.csv"))
    package_workspace.inspect_source(source["id"])
    package_workspace.build_recording(project["id"], source["id"], output_name="cli_package")
    package = package_workspace.export_project(project["id"])

    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "import_workspace"))
    runner = CliRunner()
    result = runner.invoke(app, ["project", "import", package["path"]])

    assert result.exit_code == 0
    assert "Imported project CLI Package" in result.output
    assert "with 1 recordings" in result.output
