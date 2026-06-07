from __future__ import annotations

import hashlib
import json
import glob
import os
import shutil
import sqlite3
import zipfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from datascope_core.adapters.registry import adapter_for_path, adapter_for_type
from datascope_core.mapping import (
    load_mapping_yaml,
    mapping_from_yaml_dict,
    mapping_to_yaml_dict,
    save_mapping_yaml,
    suggest_mapping,
)
from datascope_core.mapping_templates import (
    apply_mapping_template,
    diff_template_applications,
    load_mapping_template,
    save_mapping_template,
    template_from_mapping,
    validate_mapping_template,
)
from datascope_core.mapping_validation import MappingValidationError, validate_mapping
from datascope_core.models import (
    ConvertRequest,
    MappingSpec,
    SourceInfo,
    StreamInfo,
    detect_source_type,
)
from datascope_core.mapping import TEMPLATE_APP_IDS
from datascope_core.plugin_registry import (
    instantiate_entrypoint,
    load_plugin_manifest,
    validate_plugin,
)
from datascope_core.query import (
    QUERY_TEMPLATES,
    build_query_rows,
    compare_recordings,
    export_query_result,
    run_query_template,
)
from datascope_core.template_registry import (
    BUILTIN_TEMPLATES,
    load_template_manifest,
    validate_template,
)
from datascope_core.templates import match_templates, save_blueprint
from datascope_core.schema_profile import build_schema_profile
from datascope_core.version import __version__


def default_workspace_path() -> Path:
    return Path.home() / ".datascope-studio"


class Workspace:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root else default_workspace_path()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "metadata.sqlite"
        self._init_db()
        self._register_builtin_templates()

    def create_project(
        self,
        name: str,
        workspace_path: str | None = None,
        description: str = "",
    ) -> dict[str, Any]:
        project_id = f"project_{uuid4().hex[:12]}"
        project_path = Path(workspace_path) if workspace_path else self.root / "projects" / project_id
        self._ensure_project_dirs(project_path)
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                insert into projects (id, name, description, workspace_path, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                (project_id, name, description, str(project_path), now, now),
            )
        return self.get_project(project_id)

    def list_projects(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("select * from projects order by updated_at desc").fetchall()
        return [_row_to_dict(row) for row in rows]

    def get_project(self, project_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("select * from projects where id = ?", (project_id,)).fetchone()
        if row is None:
            raise KeyError(f"Project not found: {project_id}")
        return _row_to_dict(row)

    def add_source(self, project_id: str, path: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        source_id = f"source_{uuid4().hex[:12]}"
        source_path = Path(path).expanduser().resolve()
        if not source_path.exists():
            raise ValueError(f"Source path does not exist: {source_path}")
        try:
            source_type = detect_source_type(source_path)
        except ValueError:
            source_type = self._detect_plugin_source_type(source_path)

        raw_dir = Path(project["workspace_path"]) / "raw" / source_id
        raw_dir.mkdir(parents=True, exist_ok=True)
        stored_path = raw_dir / source_path.name
        if source_path.is_dir():
            if stored_path.exists():
                shutil.rmtree(stored_path)
            shutil.copytree(source_path, stored_path)
            _copy_parent_sidecars(source_path, raw_dir)
        elif source_path != stored_path:
            shutil.copy2(source_path, stored_path)

        now = _now()
        checksum = _source_checksum(stored_path)
        size_bytes = _source_size(stored_path)
        with self._connect() as conn:
            conn.execute(
                """
                insert into sources
                  (id, project_id, type, uri, checksum, size_bytes, status, metadata_json, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    project_id,
                    source_type,
                    str(stored_path),
                    checksum,
                    size_bytes,
                    "imported",
                    "{}",
                    now,
                    now,
                ),
            )
        return self.get_source(source_id)

    def get_source(self, source_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("select * from sources where id = ?", (source_id,)).fetchone()
        if row is None:
            raise KeyError(f"Source not found: {source_id}")
        result = _row_to_dict(row)
        result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
        return result

    def list_sources(self, project_id: str) -> list[dict[str, Any]]:
        self.get_project(project_id)
        with self._connect() as conn:
            rows = conn.execute(
                "select * from sources where project_id = ? order by created_at desc",
                (project_id,),
            ).fetchall()
        results = []
        for row in rows:
            result = _row_to_dict(row)
            result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
            results.append(result)
        return results

    def inspect_source(self, source_id: str) -> dict[str, Any]:
        source_row = self.get_source(source_id)
        adapter = self._adapter_for_type(source_row["type"])
        source = adapter.inspect(source_row["uri"], source_id=source_id)
        streams = adapter.infer_streams(source)
        now = _now()
        with self._connect() as conn:
            conn.execute("delete from streams where source_id = ?", (source_id,))
            conn.execute(
                "update sources set status = ?, metadata_json = ?, updated_at = ? where id = ?",
                ("inspected", json.dumps(source.metadata), now, source_id),
            )
            for stream in streams:
                conn.execute(
                    """
                    insert into streams
                      (id, source_id, name, semantic_type, fields_json, time_key, sample_rate,
                       start_time, end_time, confidence, metadata_json)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        stream.stream_id,
                        source_id,
                        stream.name,
                        stream.semantic_type,
                        json.dumps(stream.fields),
                        stream.time_key,
                        None,
                        None,
                        None,
                        stream.confidence,
                        json.dumps(stream.metadata),
                    ),
                )
        with self._connect() as conn:
            cached_profile = conn.execute(
                "select profile_json from schema_profiles where checksum = ?",
                (source_row["checksum"],),
            ).fetchone()
        profile = (
            json.loads(cached_profile["profile_json"])
            if cached_profile is not None
            else build_schema_profile(source, streams)
        )
        profile["source_id"] = source_id
        profile["adapter_metadata"] = source.metadata
        with self._connect() as conn:
            conn.execute(
                """
                insert into schema_profiles (checksum, source_type, profile_json, created_at, updated_at)
                values (?, ?, ?, ?, ?)
                on conflict(checksum) do update set
                  source_type = excluded.source_type,
                  profile_json = excluded.profile_json,
                  updated_at = excluded.updated_at
                """,
                (
                    source_row["checksum"],
                    source.source_type,
                    json.dumps(profile, ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return {
            "source": self.get_source(source_id),
            "streams": [asdict(stream) for stream in streams],
            "schema_profile": profile,
        }

    def get_streams(self, source_id: str) -> list[StreamInfo]:
        with self._connect() as conn:
            rows = conn.execute(
                "select * from streams where source_id = ? order by rowid asc",
                (source_id,),
            ).fetchall()
        return [
            StreamInfo(
                stream_id=row["id"],
                name=row["name"],
                semantic_type=row["semantic_type"],
                fields=json.loads(row["fields_json"]),
                time_key=row["time_key"],
                confidence=row["confidence"],
                metadata=json.loads(row["metadata_json"] or "{}"),
            )
            for row in rows
        ]

    def preview_source(self, source_id: str, stream_id: str, limit: int = 100) -> dict[str, Any]:
        source_row = self.get_source(source_id)
        adapter = self._adapter_for_type(source_row["type"])
        return adapter.preview(_source_info_from_row(source_row), stream_id, limit=limit)

    def get_schema_profile(self, source_id: str) -> dict[str, Any]:
        source = self.get_source(source_id)
        with self._connect() as conn:
            row = conn.execute(
                "select profile_json from schema_profiles where checksum = ?",
                (source["checksum"],),
            ).fetchone()
        if row is None:
            self.inspect_source(source_id)
            return self.get_schema_profile(source_id)
        profile = json.loads(row["profile_json"])
        profile["source_id"] = source_id
        return profile

    def suggest_mapping(self, source_id: str, template_id: str | None = None) -> MappingSpec:
        source_row = self.get_source(source_id)
        streams = self.get_streams(source_id)
        if not streams:
            self.inspect_source(source_id)
            streams = self.get_streams(source_id)
        source = _source_info_from_row(source_row)
        app_id = self.template_app_ids().get(template_id or "")
        spec = suggest_mapping(source, streams, template_id=template_id, app_id=app_id)
        profile = self.get_schema_profile(source_id)
        spec.timeline_unit = "auto"
        spec.effective_timeline_unit = profile.get("timeline", {}).get("inferred_unit")
        for stream in spec.streams:
            stream["time_key"] = spec.primary_timeline
            stream["timeline_source_field"] = spec.primary_timeline
        return spec

    def suggest_templates(self, source_id: str) -> list[dict[str, float | str]]:
        streams = self.get_streams(source_id)
        if not streams:
            self.inspect_source(source_id)
            streams = self.get_streams(source_id)
        return match_templates(streams)

    def save_mapping(
        self,
        project_id: str,
        source_id: str,
        spec: MappingSpec,
        *,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        spec.status = "confirmed" if confirmed else "draft"
        path = Path(project["workspace_path"]) / "mappings" / f"{spec.mapping_id}.yaml"
        save_mapping_yaml(spec, path)
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                insert into mappings
                  (id, project_id, source_id, stream_id, entity_path, archetype,
                   config_json, user_confirmed, path, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                  config_json = excluded.config_json,
                  user_confirmed = excluded.user_confirmed,
                  path = excluded.path,
                  updated_at = excluded.updated_at
                """,
                (
                    spec.mapping_id,
                    project_id,
                    source_id,
                    None,
                    None,
                    None,
                    json.dumps(mapping_to_yaml_dict(spec)),
                    1 if confirmed else 0,
                    str(path),
                    now,
                    now,
                ),
            )
        return self.get_mapping(spec.mapping_id)

    def get_mapping(self, mapping_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("select * from mappings where id = ?", (mapping_id,)).fetchone()
        if row is None:
            raise KeyError(f"Mapping not found: {mapping_id}")
        result = _row_to_dict(row)
        result["config"] = json.loads(result.pop("config_json") or "{}")
        result["user_confirmed"] = bool(result["user_confirmed"])
        return result

    def validate_mapping_spec(self, source_id: str, spec: MappingSpec) -> dict[str, Any]:
        source = self.get_source(source_id)
        report = validate_mapping(
            _source_info_from_row(source),
            spec,
            self.get_schema_profile(source_id),
        )
        adapter = self._adapter_for_type(source["type"])
        adapter_validator = getattr(adapter, "validate_mapping", None)
        if callable(adapter_validator):
            adapter_issues = adapter_validator(
                _source_info_from_row(source),
                spec,
                self.get_schema_profile(source_id),
            )
            report["issues"].extend(adapter_issues)
            report["errors"] = [
                issue for issue in report["issues"] if issue.get("severity") == "error"
            ]
            report["warnings"] = [
                issue for issue in report["issues"] if issue.get("severity") == "warning"
            ]
            report["valid"] = not report["errors"]
            report["summary"] = {
                "errors": len(report["errors"]),
                "warnings": len(report["warnings"]),
            }
        spec.effective_timeline_unit = report["effective_timeline_unit"]
        return report

    def validate_saved_mapping(self, mapping_id: str) -> dict[str, Any]:
        mapping = self.get_mapping(mapping_id)
        spec = mapping_from_yaml_dict(mapping["config"])
        return self.validate_mapping_spec(mapping["source_id"], spec)

    def mapping_preview(self, source_id: str, spec: MappingSpec) -> dict[str, Any]:
        streams = self.get_streams(source_id)
        preview = (
            self.preview_source(source_id, streams[0].stream_id, limit=25)
            if streams
            else {"columns": [], "rows": []}
        )
        return {
            "mapping": mapping_to_yaml_dict(spec)["mapping"],
            "schema_profile": self.get_schema_profile(source_id),
            "validation": self.validate_mapping_spec(source_id, spec),
            "preview": preview,
        }

    def confirm_mapping(self, mapping_id: str) -> dict[str, Any]:
        mapping = self.get_mapping(mapping_id)
        spec = mapping_from_yaml_dict(mapping["config"])
        report = self.validate_mapping_spec(mapping["source_id"], spec)
        if not report["valid"]:
            raise MappingValidationError(report)
        spec.effective_timeline_unit = report["effective_timeline_unit"]
        saved = self.save_mapping(
            mapping["project_id"],
            mapping["source_id"],
            spec,
            confirmed=True,
        )
        with self._connect() as conn:
            conn.execute(
                "update sources set status = ?, updated_at = ? where id = ?",
                ("mapped", _now(), mapping["source_id"]),
            )
        return {"mapping": saved, "validation": report}

    def build_recording(
        self,
        project_id: str,
        source_id: str,
        mapping_id: str | None = None,
        output_name: str = "run",
        template_id: str = "sensor_monitor",
    ) -> dict[str, Any]:
        template_app_ids = self.template_app_ids()
        if template_id not in template_app_ids:
            raise ValueError(f"Unsupported template: {template_id}")
        project = self.get_project(project_id)
        source_row = self.get_source(source_id)
        if mapping_id:
            mapping_row = self.get_mapping(mapping_id)
            spec = load_mapping_yaml(mapping_row["path"])
        else:
            spec = self.suggest_mapping(source_id, template_id=template_id)
            self.save_mapping(project_id, source_id, spec)
        spec.app_id = template_app_ids[template_id]
        spec.template_id = template_id
        report = self.validate_mapping_spec(source_id, spec)
        if not report["valid"]:
            raise MappingValidationError(report)
        spec.effective_timeline_unit = report["effective_timeline_unit"]
        self.save_mapping(project_id, source_id, spec, confirmed=True)

        job_id = f"job_{uuid4().hex[:12]}"
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                insert into jobs (id, project_id, type, status, progress, log_path, error_message, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    project_id,
                    "convert",
                    "pending",
                    0.0,
                    str(Path(project["workspace_path"]) / "logs" / f"{job_id}.log"),
                    None,
                    now,
                    now,
                ),
            )

        try:
            self._update_job(job_id, status="running", progress=0.1)
            recording_id = spec.recording_id
            output_base = _safe_output_name(output_name)
            recording_path = Path(project["workspace_path"]) / "recordings" / f"{output_base}.rrd"
            blueprint_path = Path(project["workspace_path"]) / "blueprints" / f"{output_base}.rbl"
            request = ConvertRequest(
                source=_source_info_from_row(source_row),
                mappings=spec.streams,
                output_rrd=str(recording_path),
                app_id=spec.app_id,
                recording_id=recording_id,
                primary_timeline=spec.primary_timeline,
                timeline_unit=spec.effective_timeline_unit or spec.timeline_unit,
            )
            self._adapter_for_path(source_row["uri"], source_row["type"]).convert(request)
            self._update_job(job_id, status="running", progress=0.8)
            save_blueprint(spec, template_id, blueprint_path)
            recording_db_id = f"recording_{uuid4().hex[:12]}"
            with self._connect() as conn:
                conn.execute(
                    """
                    insert into recordings
                      (id, project_id, source_id, app_id, path, blueprint_id, blueprint_path,
                       run_name, tags_json, params_json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        recording_db_id,
                        project_id,
                        source_id,
                        spec.app_id,
                        str(recording_path),
                        template_id,
                        str(blueprint_path),
                        output_base,
                        "[]",
                        "{}",
                        _now(),
                    ),
                )
            self._index_recording(recording_db_id, self.get_source(source_id), spec)
            with self._connect() as conn:
                conn.execute(
                    "update sources set status = ?, updated_at = ? where id = ?",
                    ("converted", _now(), source_id),
                )
            self._update_job(job_id, status="succeeded", progress=1.0)
            return {
                "job_id": job_id,
                "status": "succeeded",
                "recording_id": recording_db_id,
                "recording_path": str(recording_path),
                "blueprint_path": str(blueprint_path),
            }
        except Exception as exc:
            self._update_job(job_id, status="failed", progress=1.0, error_message=str(exc))
            raise

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("select * from jobs where id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"Job not found: {job_id}")
        return _row_to_dict(row)

    def list_jobs(self, project_id: str) -> list[dict[str, Any]]:
        self.get_project(project_id)
        with self._connect() as conn:
            rows = conn.execute(
                "select * from jobs where project_id = ? order by created_at desc",
                (project_id,),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def list_recordings(self, project_id: str) -> list[dict[str, Any]]:
        self.get_project(project_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                select r.*, s.type as source_type, s.uri as source_uri
                from recordings r
                left join sources s on s.id = r.source_id
                where r.project_id = ?
                order by r.created_at desc
                """,
                (project_id,),
            ).fetchall()
        return [_recording_from_row(row) for row in rows]

    def get_recording(self, recording_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                select r.*, s.type as source_type, s.uri as source_uri
                from recordings r
                left join sources s on s.id = r.source_id
                where r.id = ?
                """,
                (recording_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Recording not found: {recording_id}")
        return _recording_from_row(row)

    def update_recording(
        self,
        recording_id: str,
        *,
        run_name: str | None = None,
        tags: list[str] | None = None,
        params: dict[str, Any] | None = None,
        add_tags: list[str] | None = None,
        remove_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        current = self.get_recording(recording_id)
        next_run_name = run_name if run_name is not None else current["run_name"]
        next_tags = list(tags if tags is not None else current["tags"])
        for tag in add_tags or []:
            if tag not in next_tags:
                next_tags.append(tag)
        if remove_tags:
            next_tags = [tag for tag in next_tags if tag not in set(remove_tags)]
        next_params = dict(current["params"])
        if params:
            next_params.update(params)

        with self._connect() as conn:
            conn.execute(
                """
                update recordings
                set run_name = ?, tags_json = ?, params_json = ?
                where id = ?
                """,
                (
                    next_run_name,
                    json.dumps(next_tags, ensure_ascii=False),
                    json.dumps(next_params, ensure_ascii=False),
                    recording_id,
                ),
            )
        return self.get_recording(recording_id)

    def query_templates(self, project_id: str) -> list[dict[str, Any]]:
        self.get_project(project_id)
        return QUERY_TEMPLATES

    def run_query(
        self,
        project_id: str,
        template_id: str,
        recording_ids: list[str] | None = None,
        params: dict[str, Any] | None = None,
        limit: int = 1000,
    ) -> dict[str, Any]:
        self.get_project(project_id)
        rows = self._query_rows(project_id)
        return run_query_template(rows, template_id, recording_ids, params, limit)

    def export_query(
        self,
        project_id: str,
        template_id: str,
        recording_ids: list[str] | None = None,
        params: dict[str, Any] | None = None,
        limit: int = 1000,
        fmt: str = "csv",
        output_path: str | None = None,
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        result = self.run_query(project_id, template_id, recording_ids, params, limit)
        export_id = f"export_{uuid4().hex[:12]}"
        export_format = fmt.lower()
        output = Path(output_path) if output_path else (
            Path(project["workspace_path"]) / "exports" / f"{template_id}_{export_id}.{export_format}"
        )
        export_query_result(result, output, export_format)
        with self._connect() as conn:
            conn.execute(
                """
                insert into query_exports (id, project_id, recording_id, path, format, created_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    export_id,
                    project_id,
                    ",".join(recording_ids or []),
                    str(output),
                    export_format,
                    _now(),
                ),
            )
        return {"export_id": export_id, "path": str(output), "format": export_format, "rows": len(result["rows"])}

    def list_plugins(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("select * from plugins order by installed_at desc").fetchall()
        return [_plugin_from_row(row) for row in rows]

    def validate_plugin(self, path: str) -> dict[str, Any]:
        return validate_plugin(path)

    def install_plugin(self, path: str, enabled: bool = True) -> dict[str, Any]:
        validation = self.validate_plugin(path)
        if not validation["valid"]:
            raise ValueError("; ".join(validation["errors"]))
        manifest = load_plugin_manifest(path)
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                insert into plugins
                  (id, name, version, path, status, manifest_json, installed_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                  name = excluded.name,
                  version = excluded.version,
                  path = excluded.path,
                  status = excluded.status,
                  manifest_json = excluded.manifest_json,
                  updated_at = excluded.updated_at
                """,
                (
                    manifest.id,
                    manifest.name,
                    manifest.version,
                    manifest.path,
                    "enabled" if enabled else "disabled",
                    json.dumps(manifest.to_dict(), ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get_plugin(manifest.id)

    def get_plugin(self, plugin_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("select * from plugins where id = ?", (plugin_id,)).fetchone()
        if row is None:
            raise KeyError(f"Plugin not found: {plugin_id}")
        return _plugin_from_row(row)

    def list_templates(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("select * from template_registry order by source, name").fetchall()
        return [_template_from_row(row) for row in rows]

    def template_app_ids(self) -> dict[str, str]:
        return {template["id"]: template["app_id"] for template in self.list_templates() if template["enabled"]}

    def validate_template(self, path: str) -> dict[str, Any]:
        return validate_template(path)

    def install_template(self, path: str, enabled: bool = True) -> dict[str, Any]:
        validation = self.validate_template(path)
        if not validation["valid"]:
            raise ValueError("; ".join(validation.get("errors", [])))
        manifest = load_template_manifest(path)
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                insert into template_registry
                  (id, name, version, app_id, source, path, manifest_json, enabled, installed_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                  name = excluded.name,
                  version = excluded.version,
                  app_id = excluded.app_id,
                  source = excluded.source,
                  path = excluded.path,
                  manifest_json = excluded.manifest_json,
                  enabled = excluded.enabled,
                  updated_at = excluded.updated_at
                """,
                (
                    manifest.id,
                    manifest.name,
                    manifest.version,
                    manifest.app_id,
                    manifest.source,
                    manifest.path,
                    json.dumps(manifest.to_dict(), ensure_ascii=False),
                    1 if enabled else 0,
                    now,
                    now,
                ),
            )
        return self.get_template(manifest.id)

    def get_template(self, template_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("select * from template_registry where id = ?", (template_id,)).fetchone()
        if row is None:
            raise KeyError(f"Template not found: {template_id}")
        return _template_from_row(row)

    def list_mapping_templates(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "select * from mapping_template_registry order by name"
            ).fetchall()
        return [_mapping_template_from_row(row) for row in rows]

    def get_mapping_template(self, template_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "select * from mapping_template_registry where id = ?",
                (template_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Mapping template not found: {template_id}")
        return _mapping_template_from_row(row)

    def save_mapping_template(
        self,
        payload: dict[str, Any],
        *,
        enabled: bool = True,
    ) -> dict[str, Any]:
        validation = validate_mapping_template(payload)
        if not validation["valid"]:
            raise ValueError("; ".join(validation["errors"]))
        template = validation["template"]
        path = self.root / "mapping_templates" / f"{template['id']}.yaml"
        save_mapping_template({"mapping_template": template}, path)
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                insert into mapping_template_registry
                  (id, name, version, source_family, visual_template_id, path,
                   config_json, enabled, installed_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                  name = excluded.name,
                  version = excluded.version,
                  source_family = excluded.source_family,
                  visual_template_id = excluded.visual_template_id,
                  path = excluded.path,
                  config_json = excluded.config_json,
                  enabled = excluded.enabled,
                  updated_at = excluded.updated_at
                """,
                (
                    template["id"],
                    template["name"],
                    template["version"],
                    template["source_family"],
                    template.get("visual_template_id") or "sensor_monitor",
                    str(path),
                    json.dumps({"mapping_template": template}, ensure_ascii=False),
                    1 if enabled else 0,
                    now,
                    now,
                ),
            )
        return self.get_mapping_template(template["id"])

    def create_mapping_template(
        self,
        name: str,
        source_id: str,
        mapping_id: str,
        *,
        template_id: str | None = None,
    ) -> dict[str, Any]:
        source = self.get_source(source_id)
        mapping = self.get_mapping(mapping_id)
        if mapping["source_id"] != source_id:
            raise ValueError("Mapping does not belong to source")
        spec = mapping_from_yaml_dict(mapping["config"])
        payload = template_from_mapping(
            name,
            spec,
            _source_info_from_row(source),
            template_id=template_id,
        )
        return self.save_mapping_template(payload)

    def import_mapping_template(self, path: str, *, enabled: bool = True) -> dict[str, Any]:
        return self.save_mapping_template(load_mapping_template(path), enabled=enabled)

    def export_mapping_template(
        self,
        template_id: str,
        output_path: str | None = None,
    ) -> dict[str, Any]:
        template = self.get_mapping_template(template_id)
        source_path = Path(template["path"])
        if output_path:
            requested = Path(output_path).expanduser()
            destination = (
                requested / source_path.name
                if requested.exists() and requested.is_dir()
                else requested
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)
        else:
            destination = source_path
        return {"template_id": template_id, "path": str(destination)}

    def delete_mapping_template(self, template_id: str) -> dict[str, Any]:
        template = self.get_mapping_template(template_id)
        with self._connect() as conn:
            conn.execute("delete from mapping_template_registry where id = ?", (template_id,))
        path = Path(template["path"])
        if path.exists():
            path.unlink()
        return {"deleted": template_id}

    def apply_mapping_template(
        self,
        template_id: str,
        source_id: str,
    ) -> dict[str, Any]:
        template = self.get_mapping_template(template_id)
        source = self.get_source(source_id)
        streams = self.get_streams(source_id)
        if not streams:
            self.inspect_source(source_id)
            streams = self.get_streams(source_id)
        spec, match_issues = apply_mapping_template(
            template["config"],
            _source_info_from_row(source),
            streams,
            self.get_schema_profile(source_id),
        )
        spec.app_id = self.template_app_ids().get(
            spec.template_id or "",
            "datascope.sensor_monitor.v1",
        )
        report = self.validate_mapping_spec(source_id, spec)
        report["issues"] = [*match_issues, *report["issues"]]
        report["errors"] = [
            issue for issue in report["issues"] if issue.get("severity") == "error"
        ]
        report["warnings"] = [
            issue for issue in report["issues"] if issue.get("severity") == "warning"
        ]
        report["valid"] = not report["errors"]
        report["summary"] = {
            "errors": len(report["errors"]),
            "warnings": len(report["warnings"]),
        }
        spec.effective_timeline_unit = report["effective_timeline_unit"]
        return {
            "mapping": mapping_to_yaml_dict(spec)["mapping"],
            "validation": report,
            "match_issues": match_issues,
        }

    def diff_mapping_template(
        self,
        project_id: str,
        template_id: str,
        left_source_id: str,
        right_source_id: str,
    ) -> dict[str, Any]:
        source_ids = {source["id"] for source in self.list_sources(project_id)}
        if left_source_id not in source_ids or right_source_id not in source_ids:
            raise ValueError("Both diff sources must belong to the selected project")
        left_result = self._mapping_application_for_diff(template_id, left_source_id)
        right_result = self._mapping_application_for_diff(template_id, right_source_id)
        left = mapping_from_yaml_dict({"mapping": left_result["mapping"]})
        right = mapping_from_yaml_dict({"mapping": right_result["mapping"]})
        result = diff_template_applications(
            left,
            right,
            left_result["validation"]["issues"],
            right_result["validation"]["issues"],
        )
        result.update(
            {
                "template_id": template_id,
                "left_source_id": left_source_id,
                "right_source_id": right_source_id,
            }
        )
        return result

    def _mapping_application_for_diff(
        self,
        template_id: str,
        source_id: str,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select config_json
                from mappings
                where source_id = ?
                order by updated_at desc
                """,
                (source_id,),
            ).fetchall()
        for row in rows:
            config = json.loads(row["config_json"] or "{}")
            mapping = config.get("mapping", {})
            if mapping.get("mapping_template_id") != template_id:
                continue
            spec = mapping_from_yaml_dict(config)
            report = self.validate_mapping_spec(source_id, spec)
            return {
                "mapping": mapping_to_yaml_dict(spec)["mapping"],
                "validation": report,
                "match_issues": [],
            }
        return self.apply_mapping_template(template_id, source_id)

    def batch_import(
        self,
        project_id: str,
        patterns: list[str],
        template_id: str = "sensor_monitor",
        output_prefix: str = "batch_run",
    ) -> dict[str, Any]:
        self.get_project(project_id)
        paths = _resolve_patterns(patterns)
        if not paths:
            raise ValueError("Batch import did not match any source paths")

        batch_id = f"batch_{uuid4().hex[:12]}"
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                insert into batch_jobs
                  (id, project_id, status, total, succeeded, failed, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (batch_id, project_id, "running", len(paths), 0, 0, now, now),
            )

        succeeded = 0
        failed = 0
        for index, path in enumerate(paths, start=1):
            item_id = f"batch_item_{uuid4().hex[:12]}"
            with self._connect() as conn:
                conn.execute(
                    """
                    insert into batch_items
                      (id, batch_id, source_path, source_id, recording_id, status, error_message, created_at, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (item_id, batch_id, str(path), None, None, "running", None, _now(), _now()),
                )
            try:
                source = self.add_source(project_id, str(path))
                self.inspect_source(source["id"])
                spec = self.suggest_mapping(source["id"], template_id=template_id)
                mapping = self.save_mapping(project_id, source["id"], spec)
                result = self.build_recording(
                    project_id,
                    source["id"],
                    mapping_id=mapping["id"],
                    template_id=template_id,
                    output_name=f"{output_prefix}_{index:03d}",
                )
                succeeded += 1
                with self._connect() as conn:
                    conn.execute(
                        """
                        update batch_items
                        set source_id = ?, recording_id = ?, status = ?, error_message = ?, updated_at = ?
                        where id = ?
                        """,
                        (source["id"], result["recording_id"], "succeeded", None, _now(), item_id),
                    )
            except Exception as exc:
                failed += 1
                with self._connect() as conn:
                    conn.execute(
                        """
                        update batch_items
                        set status = ?, error_message = ?, updated_at = ?
                        where id = ?
                        """,
                        ("failed", str(exc), _now(), item_id),
                    )

            with self._connect() as conn:
                conn.execute(
                    """
                    update batch_jobs
                    set succeeded = ?, failed = ?, status = ?, updated_at = ?
                    where id = ?
                    """,
                    (
                        succeeded,
                        failed,
                        "running" if succeeded + failed < len(paths) else ("failed" if failed else "succeeded"),
                        _now(),
                        batch_id,
                    ),
                )
        return self.get_batch(batch_id)

    def get_batch(self, batch_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            batch = conn.execute("select * from batch_jobs where id = ?", (batch_id,)).fetchone()
            items = conn.execute(
                "select * from batch_items where batch_id = ? order by created_at",
                (batch_id,),
            ).fetchall()
        if batch is None:
            raise KeyError(f"Batch not found: {batch_id}")
        result = _row_to_dict(batch)
        result["items"] = [_row_to_dict(row) for row in items]
        return result

    def compare(
        self,
        project_id: str,
        recording_ids: list[str],
        metric_keys: list[str] | None = None,
        mode: str = "summary",
        limit: int = 1000,
    ) -> dict[str, Any]:
        self.get_project(project_id)
        rows = self._query_rows(project_id)
        return compare_recordings(rows, recording_ids, metric_keys, mode, limit)

    def export_project(self, project_id: str, output_path: str | None = None) -> dict[str, Any]:
        project = self.get_project(project_id)
        project_path = Path(project["workspace_path"])
        export_id = f"project_export_{uuid4().hex[:12]}"
        output = self._project_export_path(project, project_path, export_id, output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        manifest = self._project_manifest(project_id)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for path_value in _artifact_paths(manifest):
                path = Path(path_value)
                if not path.exists() or path.resolve() == output.resolve():
                    continue
                if path.is_dir():
                    for child in sorted(item for item in path.rglob("*") if item.is_file()):
                        archive.write(child, _archive_name(project_path, child))
                else:
                    archive.write(path, _archive_name(project_path, path))
        return {"export_id": export_id, "path": str(output), "format": "zip", "project_id": project_id}

    def import_project_package(self, package_path: str, project_name: str | None = None) -> dict[str, Any]:
        package = Path(package_path).expanduser().resolve()
        if not package.exists():
            raise ValueError(f"Project package does not exist: {package}")
        if package.suffix.lower() != ".zip":
            raise ValueError(f"Unsupported project package: {package}")

        with zipfile.ZipFile(package) as archive:
            try:
                manifest = json.loads(archive.read("manifest.json"))
            except KeyError as exc:
                raise ValueError("Project package is missing manifest.json") from exc
            except json.JSONDecodeError as exc:
                raise ValueError("Project package manifest.json is not valid JSON") from exc

        project_manifest = manifest.get("project")
        if not isinstance(project_manifest, dict):
            raise ValueError("Project package manifest is missing project metadata")

        original_project_id = str(project_manifest.get("id") or f"project_{uuid4().hex[:12]}")
        project_id = self._available_id("projects", original_project_id, "project")
        project_path = self.root / "projects" / project_id
        while project_path.exists() and any(project_path.iterdir()):
            project_id = f"project_{uuid4().hex[:12]}"
            project_path = self.root / "projects" / project_id

        self._ensure_project_dirs(project_path)
        with zipfile.ZipFile(package) as archive:
            _safe_extract_zip(archive, project_path)

        original_project_path = Path(project_manifest.get("workspace_path") or "")
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                insert into projects (id, name, description, workspace_path, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    project_name or project_manifest.get("name") or package.stem,
                    project_manifest.get("description") or "",
                    str(project_path),
                    project_manifest.get("created_at") or now,
                    now,
                ),
            )

            source_id_map: dict[str, str] = {}
            for source in manifest.get("sources", []):
                old_source_id = str(source.get("id") or f"source_{uuid4().hex[:12]}")
                source_id = self._available_id("sources", old_source_id, "source", conn=conn)
                source_id_map[old_source_id] = source_id
                uri = _relocated_artifact_path(source.get("uri"), original_project_path, project_path)
                checksum = str(source.get("checksum") or "")
                if not checksum and uri and Path(uri).exists():
                    checksum = _source_checksum(Path(uri))
                conn.execute(
                    """
                    insert into sources
                      (id, project_id, type, uri, checksum, size_bytes, status, metadata_json, created_at, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        project_id,
                        source.get("type") or "unknown",
                        uri or "",
                        checksum,
                        int(source.get("size_bytes") or 0),
                        source.get("status") or "imported",
                        source.get("metadata_json") or json.dumps(source.get("metadata") or {}),
                        source.get("created_at") or now,
                        source.get("updated_at") or now,
                    ),
                )

            for mapping in manifest.get("mappings", []):
                old_mapping_id = str(mapping.get("id") or f"mapping_{uuid4().hex[:12]}")
                mapping_id = self._available_id("mappings", old_mapping_id, "mapping", conn=conn)
                config = _json_object(mapping.get("config_json"), mapping.get("config") or {})
                if isinstance(config.get("mapping"), dict):
                    config["mapping"]["id"] = mapping_id
                    old_source = config["mapping"].get("source")
                    if old_source in source_id_map:
                        config["mapping"]["source"] = source_id_map[old_source]
                source_id = source_id_map.get(mapping.get("source_id")) or next(iter(source_id_map.values()), None)
                conn.execute(
                    """
                    insert into mappings
                      (id, project_id, source_id, stream_id, entity_path, archetype,
                       config_json, user_confirmed, path, created_at, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        mapping_id,
                        project_id,
                        source_id or "",
                        mapping.get("stream_id"),
                        mapping.get("entity_path"),
                        mapping.get("archetype"),
                        json.dumps(config, ensure_ascii=False),
                        int(mapping.get("user_confirmed") or 0),
                        _relocated_artifact_path(mapping.get("path"), original_project_path, project_path) or "",
                        mapping.get("created_at") or now,
                        mapping.get("updated_at") or now,
                    ),
                )

            recording_id_map: dict[str, str] = {}
            imported_recording_ids: list[str] = []
            for recording in manifest.get("recordings", []):
                old_recording_id = str(recording.get("id") or f"recording_{uuid4().hex[:12]}")
                recording_id = self._available_id("recordings", old_recording_id, "recording", conn=conn)
                recording_id_map[old_recording_id] = recording_id
                imported_recording_ids.append(recording_id)
                conn.execute(
                    """
                    insert into recordings
                      (id, project_id, source_id, app_id, path, blueprint_id, blueprint_path,
                       run_name, tags_json, params_json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        recording_id,
                        project_id,
                        source_id_map.get(recording.get("source_id")),
                        recording.get("app_id") or "datascope.imported.v1",
                        _relocated_artifact_path(recording.get("path"), original_project_path, project_path) or "",
                        recording.get("blueprint_id"),
                        _relocated_artifact_path(recording.get("blueprint_path"), original_project_path, project_path),
                        recording.get("run_name") or Path(str(recording.get("path") or "recording")).stem,
                        _json_array_text(recording.get("tags_json"), recording.get("tags")),
                        _json_object_text(recording.get("params_json"), recording.get("params")),
                        recording.get("created_at") or now,
                    ),
                )

            for export in manifest.get("query_exports", []):
                export_id = self._available_id("query_exports", str(export.get("id") or f"export_{uuid4().hex[:12]}"), "export", conn=conn)
                conn.execute(
                    """
                    insert into query_exports (id, project_id, recording_id, path, format, created_at)
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        export_id,
                        project_id,
                        recording_id_map.get(export.get("recording_id"), export.get("recording_id")),
                        _relocated_artifact_path(export.get("path"), original_project_path, project_path) or "",
                        export.get("format") or "csv",
                        export.get("created_at") or now,
                    ),
                )

        return {
            "project": self.get_project(project_id),
            "recordings": self.list_recordings(project_id),
            "recording_ids": imported_recording_ids,
            "package_path": str(package),
        }

    def _index_recording(
        self,
        recording_id: str,
        source_row: dict[str, Any],
        spec: MappingSpec,
    ) -> None:
        rows = build_query_rows(recording_id, _source_info_from_row(source_row), spec)
        with self._connect() as conn:
            conn.execute("delete from query_rows where recording_id = ?", (recording_id,))
            conn.executemany(
                """
                insert into query_rows
                  (recording_id, source_id, time, entity_path, semantic_type, key, value_json)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                [row.db_tuple() for row in rows],
            )

    def _query_rows(self, project_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select qr.*
                from query_rows qr
                join recordings r on r.id = qr.recording_id
                where r.project_id = ?
                order by qr.recording_id, qr.time, qr.entity_path, qr.key
                """,
                (project_id,),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def _update_job(
        self,
        job_id: str,
        *,
        status: str,
        progress: float,
        error_message: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                update jobs
                set status = ?, progress = ?, error_message = ?, updated_at = ?
                where id = ?
                """,
                (status, progress, error_message, _now(), job_id),
            )

    def _adapter_for_type(self, source_type: str):
        try:
            return adapter_for_type(source_type)
        except ValueError:
            plugin_adapter = self._plugin_adapter_for_type(source_type)
            if plugin_adapter is None:
                raise
            return plugin_adapter

    def _adapter_for_path(self, path: str, source_type: str | None = None):
        if source_type:
            return self._adapter_for_type(source_type)
        try:
            return adapter_for_path(path)
        except ValueError:
            return self._adapter_for_type(self._detect_plugin_source_type(Path(path)))

    def _detect_plugin_source_type(self, source_path: Path) -> str:
        for adapter in self._enabled_plugin_adapters():
            suffixes = {suffix.lower() for suffix in getattr(adapter, "supported_extensions", [])}
            if source_path.is_file() and source_path.suffix.lower() in suffixes:
                return str(getattr(adapter, "adapter_id"))
            if source_path.is_dir() and not suffixes:
                return str(getattr(adapter, "adapter_id"))
        raise ValueError(f"Unsupported source type for path: {source_path}")

    def _plugin_adapter_for_type(self, source_type: str):
        for adapter in self._enabled_plugin_adapters():
            if getattr(adapter, "adapter_id", None) == source_type:
                return adapter
        return None

    def _enabled_plugin_adapters(self) -> list[Any]:
        adapters = []
        for plugin in self.list_plugins():
            if plugin["status"] != "enabled":
                continue
            manifest = plugin["manifest"]
            for entrypoint in manifest.get("entrypoints", {}).get("adapters", {}).values():
                adapter = instantiate_entrypoint(plugin["path"], entrypoint)
                if not hasattr(adapter, "adapter_id"):
                    raise ValueError(f"Plugin adapter missing adapter_id: {entrypoint}")
                adapters.append(adapter)
        return adapters

    def _register_builtin_templates(self) -> None:
        now = _now()
        with self._connect() as conn:
            for template in BUILTIN_TEMPLATES:
                conn.execute(
                    """
                    insert into template_registry
                      (id, name, version, app_id, source, path, manifest_json, enabled, installed_at, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    on conflict(id) do update set
                      name = excluded.name,
                      version = excluded.version,
                      app_id = excluded.app_id,
                      source = excluded.source,
                      manifest_json = excluded.manifest_json,
                      enabled = 1,
                      updated_at = excluded.updated_at
                    """,
                    (
                        template["id"],
                        template["name"],
                        template["version"],
                        template["app_id"],
                        "builtin",
                        None,
                        json.dumps(template, ensure_ascii=False),
                        1,
                        now,
                        now,
                    ),
                )

    def _project_manifest(self, project_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        with self._connect() as conn:
            sources = [_row_to_dict(row) for row in conn.execute("select * from sources where project_id = ?", (project_id,))]
            mappings = [_row_to_dict(row) for row in conn.execute("select * from mappings where project_id = ?", (project_id,))]
            recordings = [self.get_recording(row["id"]) for row in conn.execute("select id from recordings where project_id = ?", (project_id,))]
            exports = [_row_to_dict(row) for row in conn.execute("select * from query_exports where project_id = ?", (project_id,))]
        return {
            "datascope_version": __version__,
            "project": project,
            "sources": sources,
            "mappings": mappings,
            "recordings": recordings,
            "query_exports": exports,
            "templates": self.list_templates(),
            "created_at": _now(),
        }

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists projects (
                  id text primary key,
                  name text not null,
                  description text not null default '',
                  workspace_path text not null,
                  created_at text not null,
                  updated_at text not null
                );
                create table if not exists sources (
                  id text primary key,
                  project_id text not null,
                  type text not null,
                  uri text not null,
                  checksum text not null,
                  size_bytes integer not null,
                  status text not null,
                  metadata_json text not null default '{}',
                  created_at text not null,
                  updated_at text not null,
                  foreign key(project_id) references projects(id)
                );
                create table if not exists streams (
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
                create table if not exists mappings (
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
                create table if not exists recordings (
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
                create table if not exists jobs (
                  id text primary key,
                  project_id text not null,
                  type text not null,
                  status text not null,
                  progress real not null,
                  log_path text,
                  error_message text,
                  created_at text not null,
                  updated_at text not null,
                  foreign key(project_id) references projects(id)
                );
                create table if not exists query_rows (
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
                create index if not exists idx_query_rows_recording on query_rows(recording_id);
                create index if not exists idx_query_rows_key on query_rows(key);
                create table if not exists query_exports (
                  id text primary key,
                  project_id text not null,
                  recording_id text,
                  path text not null,
                  format text not null,
                  created_at text not null,
                  foreign key(project_id) references projects(id)
                );
                create table if not exists plugins (
                  id text primary key,
                  name text not null,
                  version text not null,
                  path text not null,
                  status text not null,
                  manifest_json text not null,
                  installed_at text not null,
                  updated_at text not null
                );
                create table if not exists template_registry (
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
                create table if not exists schema_profiles (
                  checksum text primary key,
                  source_type text not null,
                  profile_json text not null,
                  created_at text not null,
                  updated_at text not null
                );
                create table if not exists mapping_template_registry (
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
                create table if not exists batch_jobs (
                  id text primary key,
                  project_id text not null,
                  status text not null,
                  total integer not null,
                  succeeded integer not null,
                  failed integer not null,
                  created_at text not null,
                  updated_at text not null,
                  foreign key(project_id) references projects(id)
                );
                create table if not exists batch_items (
                  id text primary key,
                  batch_id text not null,
                  source_path text not null,
                  source_id text,
                  recording_id text,
                  status text not null,
                  error_message text,
                  created_at text not null,
                  updated_at text not null,
                  foreign key(batch_id) references batch_jobs(id)
                );
                """
            )
            _ensure_column(conn, "recordings", "source_id", "text")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _project_export_path(
        self,
        project: dict[str, Any],
        project_path: Path,
        export_id: str,
        output_path: str | None,
    ) -> Path:
        filename = f"{_safe_output_name(project['name'])}_{export_id}.zip"
        if output_path:
            requested = Path(output_path).expanduser()
            if requested.suffix.lower() == ".zip":
                return requested
            return requested / filename
        if self.root.expanduser().resolve() == default_workspace_path().resolve():
            return Path.home() / "DataScope Studio Exports" / filename
        return project_path / "exports" / filename

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
            if not connection.execute(f"select 1 from {table} where id = ?", (preferred_id,)).fetchone():
                return preferred_id
            while True:
                candidate = f"{prefix}_{uuid4().hex[:12]}"
                if not connection.execute(f"select 1 from {table} where id = ?", (candidate,)).fetchone():
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
            "recordings",
            "blueprints",
            "mappings",
            "templates",
            "mapping_templates",
            "exports",
            "logs",
        ):
            (project_path / name).mkdir(parents=True, exist_ok=True)


def _source_info_from_row(row: dict[str, Any]) -> SourceInfo:
    return SourceInfo(
        source_id=row["id"],
        source_type=row["type"],
        path=row["uri"],
        metadata=row.get("metadata", {}),
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _recording_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = _row_to_dict(row)
    result["tags"] = json.loads(result.pop("tags_json") or "[]")
    result["params"] = json.loads(result.pop("params_json") or "{}")
    return result


def _plugin_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = _row_to_dict(row)
    result["manifest"] = json.loads(result.pop("manifest_json") or "{}")
    return result


def _template_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = _row_to_dict(row)
    result["manifest"] = json.loads(result.pop("manifest_json") or "{}")
    result["enabled"] = bool(result["enabled"])
    return result


def _mapping_template_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = _row_to_dict(row)
    result["config"] = json.loads(result.pop("config_json") or "{}")
    result["enabled"] = bool(result["enabled"])
    return result


def _resolve_patterns(patterns: list[str]) -> list[Path]:
    resolved: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        matches = glob.glob(str(Path(pattern).expanduser()), recursive=True)
        if not matches and Path(pattern).expanduser().exists():
            matches = [str(Path(pattern).expanduser())]
        for match in matches:
            path = Path(match).expanduser().resolve()
            if path in seen:
                continue
            seen.add(path)
            resolved.append(path)
    return sorted(resolved, key=lambda item: str(item))


def _artifact_paths(manifest: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for source in manifest.get("sources", []):
        if source.get("uri"):
            paths.append(source["uri"])
    for mapping in manifest.get("mappings", []):
        if mapping.get("path"):
            paths.append(mapping["path"])
    for recording in manifest.get("recordings", []):
        for key in ("path", "blueprint_path"):
            if recording.get(key):
                paths.append(recording[key])
    for export in manifest.get("query_exports", []):
        if export.get("path"):
            paths.append(export["path"])
    return paths


def _archive_name(project_path: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_path.resolve()))
    except ValueError:
        return f"external/{path.name}"


def _safe_extract_zip(archive: zipfile.ZipFile, destination: Path) -> None:
    destination_root = destination.resolve()
    for member in archive.infolist():
        member_path = destination / member.filename
        resolved = member_path.resolve()
        if os.path.commonpath([str(destination_root), str(resolved)]) != str(destination_root):
            raise ValueError(f"Unsafe project package path: {member.filename}")
        if member.is_dir():
            resolved.mkdir(parents=True, exist_ok=True)
            continue
        resolved.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(member) as source, open(resolved, "wb") as target:
            shutil.copyfileobj(source, target)


def _relocated_artifact_path(path_value: Any, original_project_path: Path, project_path: Path) -> str | None:
    if not path_value:
        return None
    original = Path(str(path_value))
    relative_path: Path
    try:
        relative_path = original.resolve().relative_to(original_project_path.resolve())
    except (OSError, RuntimeError, ValueError):
        relative_path = Path("external") / original.name
    return str(project_path / relative_path)


def _json_object(value: Any, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return dict(fallback or {})


def _json_object_text(value: Any, fallback: Any = None) -> str:
    return json.dumps(_json_object(value, fallback if isinstance(fallback, dict) else {}), ensure_ascii=False)


def _json_array_text(value: Any, fallback: Any = None) -> str:
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return json.dumps(parsed, ensure_ascii=False)
        except json.JSONDecodeError:
            pass
    if isinstance(fallback, list):
        return json.dumps(fallback, ensure_ascii=False)
    return "[]"


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
    columns = {row["name"] for row in conn.execute(f"pragma table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"alter table {table} add column {column} {column_type}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_checksum(path: Path) -> str:
    if path.is_file():
        return _sha256(path)
    digest = hashlib.sha256()
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        digest.update(str(child.relative_to(path)).encode("utf-8"))
        with open(child, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _source_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())


def _copy_parent_sidecars(source_path: Path, raw_dir: Path) -> None:
    for name in ("annotations.json", "predictions.json"):
        source_sidecar = source_path.parent / name
        if source_sidecar.exists() and source_sidecar.is_file():
            shutil.copy2(source_sidecar, raw_dir / name)


def _safe_output_name(value: str) -> str:
    return "".join(character if character.isalnum() or character in {"_", "-"} else "_" for character in value)
