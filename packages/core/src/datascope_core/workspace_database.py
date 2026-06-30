from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4


SCHEMA_VERSION = 3


class WorkspaceDatabaseMixin:
    db_path: Path

    def _init_db(self) -> None:
        with self._connect() as conn:
            version = int(conn.execute("pragma user_version").fetchone()[0])
            has_projects = conn.execute(
                "select 1 from sqlite_master where type = 'table' and name = 'projects'"
            ).fetchone()
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Workspace schema {version} is newer than supported schema {SCHEMA_VERSION}"
                )
            if not has_projects:
                self._create_schema(conn)
                conn.execute(f"pragma user_version = {SCHEMA_VERSION}")
            else:
                if version == 0:
                    version = 1
                    conn.execute("pragma user_version = 1")
                if version == 1:
                    self._migrate_v1_to_v2(conn)
                    version = 2
                if version == 2:
                    self._migrate_v2_to_v3(conn)
            conn.execute("pragma journal_mode = WAL")
            conn.execute("pragma synchronous = NORMAL")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = ON")
        conn.execute("pragma busy_timeout = 5000")
        return conn

    def _available_id(
        self,
        table: str,
        preferred_id: str,
        prefix: str,
        conn: sqlite3.Connection | None = None,
    ) -> str:
        connection = conn or self._connect()
        close_connection = conn is None
        try:
            if not connection.execute(
                f"select 1 from {table} where id = ?",
                (preferred_id,),
            ).fetchone():
                return preferred_id
            while True:
                candidate = f"{prefix}_{uuid4().hex[:12]}"
                if not connection.execute(
                    f"select 1 from {table} where id = ?",
                    (candidate,),
                ).fetchone():
                    return candidate
        finally:
            if close_connection:
                connection.close()

    @staticmethod
    def _ensure_project_dirs(project_path: Path) -> None:
        for name in (
            "raw",
            "cache/previews",
            "cache/thumbnails",
            "cache/schemas",
            "cache/sampled_parquet",
            "cache/jobs",
            "recordings",
            "blueprints",
            "mappings",
            "templates",
            "mapping_templates",
            "exports",
            "logs",
        ):
            (project_path / name).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _create_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            create table projects (
              id text primary key,
              name text not null,
              description text not null default '',
              workspace_path text not null,
              created_at text not null,
              updated_at text not null
            );
            create table sources (
              id text primary key,
              project_id text not null,
              type text not null,
              uri text not null,
              checksum text not null,
              size_bytes integer not null,
              status text not null,
              metadata_json text not null default '{}',
              storage_mode text not null default 'copy',
              original_uri text,
              created_at text not null,
              updated_at text not null,
              foreign key(project_id) references projects(id)
            );
            create table streams (
              id text not null,
              source_id text not null,
              name text not null,
              semantic_type text not null,
              fields_json text not null,
              time_key text,
              sample_rate real,
              start_time real,
              end_time real,
              confidence real not null,
              metadata_json text not null default '{}',
              primary key(id, source_id),
              foreign key(source_id) references sources(id)
            );
            create table mappings (
              id text primary key,
              project_id text not null,
              source_id text not null,
              stream_id text,
              entity_path text,
              archetype text,
              config_json text not null,
              user_confirmed integer not null default 0,
              path text not null,
              created_at text not null,
              updated_at text not null,
              foreign key(project_id) references projects(id),
              foreign key(source_id) references sources(id)
            );
            create table recordings (
              id text primary key,
              project_id text not null,
              source_id text,
              app_id text not null,
              path text not null,
              blueprint_id text,
              blueprint_path text,
              run_name text not null,
              tags_json text not null default '[]',
              params_json text not null default '{}',
              created_at text not null,
              foreign key(project_id) references projects(id),
              foreign key(source_id) references sources(id)
            );
            create table jobs (
              id text primary key,
              project_id text not null,
              type text not null,
              status text not null,
              progress real not null,
              stage text not null default 'queued',
              log_path text,
              error_message text,
              payload_json text not null default '{}',
              result_json text,
              error_json text,
              attempt integer not null default 1,
              retry_of_job_id text,
              resource_type text,
              resource_id text,
              worker_pid integer,
              worker_token text,
              heartbeat_at text,
              started_at text,
              finished_at text,
              cancel_requested_at text,
              created_at text not null,
              updated_at text not null,
              foreign key(project_id) references projects(id),
              foreign key(retry_of_job_id) references jobs(id)
            );
            create table query_rows (
              recording_id text not null,
              source_id text not null,
              time real,
              entity_path text not null,
              semantic_type text not null,
              key text not null,
              value_json text not null,
              foreign key(recording_id) references recordings(id),
              foreign key(source_id) references sources(id)
            );
            create table query_exports (
              id text primary key,
              project_id text not null,
              recording_id text,
              path text not null,
              format text not null,
              created_at text not null,
              foreign key(project_id) references projects(id)
            );
            create table plugins (
              id text primary key,
              name text not null,
              version text not null,
              path text not null,
              status text not null,
              manifest_json text not null,
              installed_at text not null,
              updated_at text not null
            );
            create table template_registry (
              id text primary key,
              name text not null,
              version text not null,
              app_id text not null,
              source text not null,
              path text,
              manifest_json text not null,
              enabled integer not null default 1,
              installed_at text not null,
              updated_at text not null
            );
            create table schema_profiles (
              checksum text primary key,
              source_type text not null,
              profile_json text not null,
              created_at text not null,
              updated_at text not null
            );
            create table mapping_template_registry (
              id text primary key,
              name text not null,
              version text not null,
              source_family text not null,
              visual_template_id text not null,
              path text not null,
              config_json text not null,
              enabled integer not null default 1,
              installed_at text not null,
              updated_at text not null
            );
            create table batch_jobs (
              id text primary key,
              project_id text not null,
              job_id text,
              status text not null,
              template_id text not null default 'sensor_monitor',
              output_prefix text not null default 'batch_run',
              storage_mode text not null default 'copy',
              patterns_json text not null default '[]',
              total integer not null,
              succeeded integer not null,
              failed integer not null,
              cancelled integer not null default 0,
              created_at text not null,
              updated_at text not null,
              foreign key(project_id) references projects(id),
              foreign key(job_id) references jobs(id)
            );
            create table batch_items (
              id text primary key,
              batch_id text not null,
              source_path text not null,
              source_id text,
              recording_id text,
              status text not null,
              error_message text,
              attempt integer not null default 1,
              cancel_requested_at text,
              created_at text not null,
              updated_at text not null,
              foreign key(batch_id) references batch_jobs(id),
              foreign key(source_id) references sources(id),
              foreign key(recording_id) references recordings(id)
            );
            create table diagnostic_exports (
              id text primary key,
              project_id text not null,
              recording_ids_json text not null default '[]',
              thresholds_json text not null default '{}',
              summary_json text not null default '{}',
              path text not null,
              format text not null,
              created_at text not null,
              foreign key(project_id) references projects(id)
            );
            """
        )
        _create_indexes(conn)

    @staticmethod
    def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
        _ensure_column(conn, "recordings", "source_id", "text")
        _ensure_column(conn, "sources", "storage_mode", "text not null default 'copy'")
        _ensure_column(conn, "sources", "original_uri", "text")
        _ensure_column(conn, "jobs", "stage", "text not null default 'queued'")
        _ensure_column(conn, "jobs", "payload_json", "text not null default '{}'")
        _ensure_column(conn, "jobs", "result_json", "text")
        _ensure_column(conn, "jobs", "error_json", "text")
        _ensure_column(conn, "jobs", "attempt", "integer not null default 1")
        _ensure_column(conn, "jobs", "retry_of_job_id", "text")
        _ensure_column(conn, "jobs", "resource_type", "text")
        _ensure_column(conn, "jobs", "resource_id", "text")
        _ensure_column(conn, "jobs", "worker_pid", "integer")
        _ensure_column(conn, "jobs", "worker_token", "text")
        _ensure_column(conn, "jobs", "heartbeat_at", "text")
        _ensure_column(conn, "jobs", "started_at", "text")
        _ensure_column(conn, "jobs", "finished_at", "text")
        _ensure_column(conn, "jobs", "cancel_requested_at", "text")
        _ensure_column(conn, "batch_jobs", "job_id", "text")
        _ensure_column(conn, "batch_items", "attempt", "integer not null default 1")
        conn.execute(
            """
            create table if not exists diagnostic_exports (
              id text primary key,
              project_id text not null,
              recording_ids_json text not null default '[]',
              thresholds_json text not null default '{}',
              summary_json text not null default '{}',
              path text not null,
              format text not null,
              created_at text not null,
              foreign key(project_id) references projects(id)
            )
            """
        )
        conn.execute(
            "update sources set original_uri = uri where original_uri is null or original_uri = ''"
        )
        _create_indexes(conn)
        conn.execute("pragma user_version = 2")

    @staticmethod
    def _migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
        _ensure_column(conn, "batch_jobs", "template_id", "text not null default 'sensor_monitor'")
        _ensure_column(conn, "batch_jobs", "output_prefix", "text not null default 'batch_run'")
        _ensure_column(conn, "batch_jobs", "storage_mode", "text not null default 'copy'")
        _ensure_column(conn, "batch_jobs", "patterns_json", "text not null default '[]'")
        _ensure_column(conn, "batch_jobs", "cancelled", "integer not null default 0")
        _ensure_column(conn, "batch_items", "cancel_requested_at", "text")
        conn.execute(
            """
            create table if not exists diagnostic_exports (
              id text primary key,
              project_id text not null,
              recording_ids_json text not null default '[]',
              thresholds_json text not null default '{}',
              summary_json text not null default '{}',
              path text not null,
              format text not null,
              created_at text not null,
              foreign key(project_id) references projects(id)
            )
            """
        )
        _create_indexes(conn)
        conn.execute(f"pragma user_version = {SCHEMA_VERSION}")


def _create_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create index if not exists idx_jobs_project_status_created
          on jobs(project_id, status, created_at);
        create index if not exists idx_jobs_status_created
          on jobs(status, created_at);
        create index if not exists idx_sources_project_storage
          on sources(project_id, storage_mode, created_at);
        create index if not exists idx_batch_jobs_project_status
          on batch_jobs(project_id, status, created_at);
        create index if not exists idx_batch_items_batch_status
          on batch_items(batch_id, status, created_at);
        create index if not exists idx_diagnostic_exports_project_created
          on diagnostic_exports(project_id, created_at);
        create index if not exists idx_query_rows_recording
          on query_rows(recording_id);
        create index if not exists idx_query_rows_key
          on query_rows(key);
        create index if not exists idx_query_rows_recording_semantic_key
          on query_rows(recording_id, semantic_type, key, entity_path, time);
        """
    )


def _ensure_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    column_type: str,
) -> None:
    columns = {row["name"] for row in conn.execute(f"pragma table_info({table})")}
    if column not in columns:
        conn.execute(f"alter table {table} add column {column} {column_type}")
