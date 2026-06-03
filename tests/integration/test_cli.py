from pathlib import Path

from typer.testing import CliRunner

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
    assert (tmp_path / "workspace").exists()

