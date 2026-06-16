from __future__ import annotations

from pathlib import Path

import pytest

from datascope_core.workspace import SourceUnavailableError, Workspace


def test_reference_source_detects_changes(tmp_path: Path) -> None:
    source_path = tmp_path / "source.csv"
    source_path.write_text("time,value\n0,1\n", encoding="utf-8")
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Reference")
    source = workspace.add_source(
        project["id"],
        str(source_path),
        storage_mode="reference",
    )

    assert source["storage_mode"] == "reference"
    assert source["uri"] == str(source_path.resolve())
    source_path.write_text("time,value\n0,2\n", encoding="utf-8")

    with pytest.raises(SourceUnavailableError) as error:
        workspace.inspect_source(source["id"])
    assert error.value.code == "source_changed"


def test_copy_source_survives_original_removal(tmp_path: Path) -> None:
    source_path = tmp_path / "source.csv"
    source_path.write_text("time,value\n0,1\n", encoding="utf-8")
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Copy")
    source = workspace.add_source(project["id"], str(source_path))
    source_path.unlink()

    inspection = workspace.inspect_source(source["id"])
    assert source["storage_mode"] == "copy"
    assert inspection["streams"]


def test_disk_estimate_uses_required_margin(tmp_path: Path) -> None:
    source_path = tmp_path / "source.csv"
    source_path.write_bytes(b"x" * 1024)
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Estimate")

    estimate = workspace.estimate_source_import(project["id"], str(source_path))

    assert estimate["estimated"] == 1024
    assert estimate["margin"] == 512 * 1024 * 1024
    assert estimate["required"] == estimate["estimated"] + estimate["margin"]


def test_reference_project_export_imports_as_copy(tmp_path: Path) -> None:
    source_path = tmp_path / "external" / "source.csv"
    source_path.parent.mkdir()
    source_path.write_text("time,value\n0,1\n", encoding="utf-8")
    source_workspace = Workspace(tmp_path / "source_workspace")
    project = source_workspace.create_project("Reference Package")
    source_workspace.add_source(
        project["id"],
        str(source_path),
        storage_mode="reference",
    )

    package = source_workspace.export_project(project["id"])
    imported_workspace = Workspace(tmp_path / "imported_workspace")
    imported = imported_workspace.import_project_package(package["path"])
    imported_source = imported_workspace.list_sources(imported["project"]["id"])[0]

    assert imported_source["storage_mode"] == "copy"
    assert Path(imported_source["uri"]).is_file()
    source_path.unlink()
    assert imported_workspace.inspect_source(imported_source["id"])["streams"]


def test_reference_project_export_rejects_missing_source(tmp_path: Path) -> None:
    source_path = tmp_path / "source.csv"
    source_path.write_text("time,value\n0,1\n", encoding="utf-8")
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Missing Reference")
    workspace.add_source(project["id"], str(source_path), storage_mode="reference")
    source_path.unlink()

    with pytest.raises(SourceUnavailableError):
        workspace.export_project(project["id"])
