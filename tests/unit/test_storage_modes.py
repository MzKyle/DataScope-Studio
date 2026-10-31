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


@pytest.mark.parametrize('devices', [(0, 0, 0), (0, 1, 1), (0, 1, 2)])
def test_typed_budget_checks_catalog_project_cache_and_output_volumes(tmp_path, monkeypatch, devices):
    import datascope_core.workspace_storage as storage
    workspace = Workspace(tmp_path / 'catalog')
    project_path, output = tmp_path / 'project', tmp_path / 'output'
    project = workspace.create_project('Separated disks', workspace_path=str(project_path))
    source_path = tmp_path / 'source.csv'
    source_path.write_text('time,value\n0,1\n')
    source = workspace.add_source(project['id'], str(source_path), storage_mode='reference')
    locations = dict(zip((workspace.db_path.parent, project_path, output), devices))
    monkeypatch.setattr(storage, '_disk_device', lambda path: locations[path])
    def estimate(operation, size, path, **kwargs):
        return {'kind': operation, 'estimated': size, 'required': size + 100, 'margin': 100,
                'free': 0 if locations[path] == 0 else 10**12,
                'sufficient': locations[path] != 0, 'confidence': 'medium', 'warnings': []}
    monkeypatch.setattr(storage, 'disk_estimate', estimate)
    result = workspace.estimate_build(project['id'], source['id'], output_dir=str(output),
                                      query_storage='auto')
    assert result['estimated'] == source['size_bytes'] * 9
    volumes = result.get('volumes', [result])
    assert len(volumes) == len(set(devices))
    assert result['required'] == result['estimated'] + 100 * len(volumes)
    actual = {key: value for volume in volumes for key, value in volume['components'].items()}
    assert actual == {'query_index_and_journal': source['size_bytes'] * 5,
                      'query_temporary': source['size_bytes'] * 2,
                      'rerun_artifacts': source['size_bytes'] * 2}
    assert next(v for v in volumes if 'query_index_and_journal' in v['components'])['destination'] == str(workspace.root.resolve())
    assert result['sufficient'] is False  # A full Catalog disk cannot be hidden by a free output disk.


@pytest.mark.parametrize('mode', ['copy', 'reference'])
def test_auto_batch_budget_includes_typed_csv_and_legacy_non_csv(tmp_path, mode):
    workspace = Workspace(tmp_path / 'workspace')
    project = workspace.create_project('Mixed budget')
    csv = tmp_path / 'values.csv'
    csv.write_text('time,value\n0,1\n')
    jsonl = tmp_path / 'values.jsonl'
    jsonl.write_text('{"time":0,"value":1}\n')
    result = workspace.estimate_batch_import(project['id'], [str(csv), str(jsonl)],
                                              storage_mode=mode, query_storage='auto')
    assert result['query_storage'] == 'auto'
    assert result['components']['query_index_and_journal'] == csv.stat().st_size * 5
    assert result['components']['query_temporary'] == csv.stat().st_size * 2
    assert result['components']['rerun_artifacts'] == csv.stat().st_size * 2 + 64 * 1024 * 1024
    assert result['components'].get('source_copy', 0) == (
        csv.stat().st_size + jsonl.stat().st_size if mode == 'copy' else 0)
    assert result['estimated'] == sum(result['components'].values())


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
