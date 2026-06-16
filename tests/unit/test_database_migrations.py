from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from datascope_core.workspace import Workspace


def test_migrates_v1_database_and_preserves_catalog(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    db_path = root / "metadata.sqlite"
    _create_v1_database(db_path, tmp_path / "project")

    workspace = Workspace(root)
    project = workspace.get_project("project_legacy")
    source = workspace.get_source("source_legacy")

    assert project["name"] == "Legacy"
    assert source["storage_mode"] == "copy"
    assert source["original_uri"] == source["uri"]
    assert _pragma(db_path, "user_version") == 2
    assert _pragma(db_path, "journal_mode") == "wal"
    assert _pragma(db_path, "foreign_keys", workspace) == 1
    assert _pragma(db_path, "busy_timeout", workspace) == 5000

    Workspace(root)
    assert _pragma(db_path, "user_version") == 2


def test_rejects_future_database_version(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    db_path = root / "metadata.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute("pragma user_version = 99")
        conn.execute("create table projects (id text primary key)")

    with pytest.raises(RuntimeError, match="newer than supported"):
        Workspace(root)


def test_connections_enforce_foreign_keys(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "workspace")
    with workspace._connect() as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            insert into sources
              (id, project_id, type, uri, checksum, size_bytes, status,
               metadata_json, storage_mode, original_uri, created_at, updated_at)
            values ('source_bad', 'missing', 'csv', '/tmp/x', 'x', 1, 'ready',
                    '{}', 'copy', '/tmp/x', 'now', 'now')
            """
        )


def _pragma(
    db_path: Path,
    name: str,
    workspace: Workspace | None = None,
):
    if workspace is not None:
        with workspace._connect() as conn:
            return conn.execute(f"pragma {name}").fetchone()[0]
    with sqlite3.connect(db_path) as conn:
        return conn.execute(f"pragma {name}").fetchone()[0]


def _create_v1_database(db_path: Path, project_path: Path) -> None:
    project_path.mkdir()
    source_path = project_path / "legacy.csv"
    source_path.write_text("time,value\n0,1\n", encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            create table projects (
              id text primary key, name text not null, description text not null,
              workspace_path text not null, created_at text not null, updated_at text not null
            );
            create table sources (
              id text primary key, project_id text not null, type text not null,
              uri text not null, checksum text not null, size_bytes integer not null,
              status text not null, metadata_json text not null default '{}',
              created_at text not null, updated_at text not null
            );
            create table recordings (
              id text primary key, project_id text not null, source_id text,
              app_id text not null, path text not null, blueprint_id text,
              blueprint_path text, run_name text not null, tags_json text not null default '[]',
              params_json text not null default '{}', created_at text not null
            );
            create table jobs (
              id text primary key, project_id text not null, type text not null,
              status text not null, progress real not null, log_path text,
              error_message text, created_at text not null, updated_at text not null
            );
            create table query_rows (
              recording_id text not null, source_id text not null, time real,
              entity_path text not null, semantic_type text not null,
              key text not null, value_json text not null
            );
            create table template_registry (
              id text primary key, name text not null, version text not null,
              app_id text not null, source text not null, path text,
              manifest_json text not null, enabled integer not null default 1,
              installed_at text not null, updated_at text not null
            );
            create table batch_jobs (
              id text primary key, project_id text not null, status text not null,
              total integer not null, succeeded integer not null, failed integer not null,
              created_at text not null, updated_at text not null
            );
            create table batch_items (
              id text primary key, batch_id text not null, source_path text not null,
              source_id text, recording_id text, status text not null,
              error_message text, created_at text not null, updated_at text not null
            );
            pragma user_version = 1;
            """
        )
        conn.execute(
            "insert into projects values (?, ?, ?, ?, ?, ?)",
            ("project_legacy", "Legacy", "", str(project_path), "now", "now"),
        )
        conn.execute(
            "insert into sources values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "source_legacy",
                "project_legacy",
                "csv",
                str(source_path),
                "checksum",
                source_path.stat().st_size,
                "ready",
                "{}",
                "now",
                "now",
            ),
        )
