from __future__ import annotations

import hashlib
import json
import glob
import os
import shutil
import sqlite3
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from datascope_core.adapters.registry import adapter_for_path, adapter_for_type
from datascope_core.adapters.ros2_db3_adapter import metadata_references_db3
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
from datascope_core.mapping_validation import (
    MappingValidationError,
    build_validation_report,
    validate_mapping,
)
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
    compare_recordings,
    export_query_result,
    iter_query_rows,
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
from datascope_core.workspace_database import WorkspaceDatabaseMixin
from datascope_core.workspace_storage import (
    DiskSpaceError,
    SourceUnavailableError,
    WorkspaceStorageMixin,
)
from datascope_core.workspace_jobs import JobCancelled, WorkspaceJobsMixin
from datascope_core.workspace_query import WorkspaceQueryMixin
from datascope_core.workspace_package import WorkspacePackageMixin
from datascope_core.workspace_registry import WorkspaceRegistryMixin
from datascope_core.workspace_utils import (
    archive_name as _archive_name,
    artifact_paths as _artifact_paths,
    copy_parent_sidecars as _copy_parent_sidecars,
    disk_estimate as _disk_estimate,
    job_from_row as _job_from_row,
    json_array_text as _json_array_text,
    json_object as _json_object,
    json_object_text as _json_object_text,
    mapping_template_from_row as _mapping_template_from_row,
    plugin_from_row as _plugin_from_row,
    recording_from_row as _recording_from_row,
    relocated_artifact_path as _relocated_artifact_path,
    resolve_patterns as _resolve_patterns,
    row_to_dict as _row_to_dict,
    safe_extract_zip as _safe_extract_zip,
    safe_output_name as _safe_output_name,
    source_checksum as _source_checksum,
    source_info_from_row as _source_info_from_row,
    source_output_name as _source_output_name,
    source_size as _source_size,
    structured_error as _structured_error,
    template_from_row as _template_from_row,
    utc_now as _now,
)


def default_workspace_path() -> Path:
    return Path.home() / ".datascope-studio"


class ArtifactConflictError(RuntimeError):
    code = "artifact_name_conflict"

    def __init__(self, output_name: str, paths: list[Path]) -> None:
        self.output_name = output_name
        self.paths = [str(path) for path in paths]
        joined_paths = ", ".join(self.paths)
        super().__init__(
            f"Output name '{output_name}' conflicts with existing artifacts: "
            f"{joined_paths}. Choose a different output name."
        )


class Workspace(
    WorkspaceRegistryMixin,
    WorkspacePackageMixin,
    WorkspaceQueryMixin,
    WorkspaceJobsMixin,
    WorkspaceStorageMixin,
    WorkspaceDatabaseMixin,
):
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

    def inspect_source(self, source_id: str) -> dict[str, Any]:
        source_row = self.get_source(source_id)
        self._assert_source_available(source_row)
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
        source_info = _source_info_from_row(source)
        profile = self.get_schema_profile(source_id)
        report = validate_mapping(
            source_info,
            spec,
            profile,
        )
        adapter = self._adapter_for_type(source["type"])
        adapter_validator = getattr(adapter, "validate_mapping", None)
        if callable(adapter_validator):
            adapter_issues = adapter_validator(
                source_info,
                spec,
                profile,
            )
            report = build_validation_report(
                source_info,
                spec,
                profile,
                [*report["issues"], *adapter_issues],
            )
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
        output_name: str | None = None,
        template_id: str = "sensor_monitor",
        *,
        _job_id: str | None = None,
        _manage_job: bool = True,
        _cache_dir: str | Path | None = None,
        _cancel_check: Callable[[], None] | None = None,
        _background_job: bool = False,
    ) -> dict[str, Any]:
        template_app_ids = self.template_app_ids()
        if template_id not in template_app_ids:
            raise ValueError(f"Unsupported template: {template_id}")
        project = self.get_project(project_id)
        source_row = self.get_source(source_id)
        self._assert_source_available(source_row)
        self._ensure_disk(self.estimate_build(project_id, source_id))
        requested_output_name = output_name.strip() if output_name else ""
        output_base = (
            _safe_output_name(requested_output_name or _source_output_name(source_row["uri"]))
            or "run"
        )
        recording_path = Path(project["workspace_path"]) / "recordings" / f"{output_base}.rrd"
        blueprint_path = Path(project["workspace_path"]) / "blueprints" / f"{output_base}.rbl"
        self._assert_artifact_paths_available(
            project_id,
            recording_path,
            blueprint_path,
        )
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

        job_id = _job_id
        if _manage_job and job_id is None:
            job_id = self._create_job(
                project_id,
                "conversion",
                {
                    "project_id": project_id,
                    "source_id": source_id,
                    "mapping_id": mapping_id,
                    "output_name": output_name,
                    "template_id": template_id,
                },
                resource_type="source",
                resource_id=source_id,
            )["id"]

        reserved_paths: list[Path] = []
        recording_db_id: str | None = None
        cache_dir = Path(
            _cache_dir
            or (
                Path(project["workspace_path"]) / "cache" / "jobs" / (job_id or uuid4().hex)
            )
        )
        cache_dir.mkdir(parents=True, exist_ok=True)

        def check_cancel() -> None:
            if _cancel_check is not None:
                _cancel_check()
            if job_id is not None:
                self._check_job_cancelled(job_id)

        def report_progress(stage: str, progress: float) -> None:
            check_cancel()
            if _manage_job and job_id is not None:
                self._update_job(
                    job_id,
                    status="running",
                    progress=0.1 + min(max(progress, 0.0), 1.0) * 0.65,
                    stage=stage,
                )

        try:
            if _manage_job and job_id is not None:
                self._update_job(
                    job_id,
                    status="running",
                    progress=0.05,
                    stage="preparing",
                    started=True,
                )
            check_cancel()
            reserved_paths = self._reserve_artifact_paths(recording_path, blueprint_path)
            recording_id = spec.recording_id
            request = ConvertRequest(
                source=_source_info_from_row(source_row),
                mappings=spec.streams,
                output_rrd=str(recording_path),
                app_id=spec.app_id,
                recording_id=recording_id,
                primary_timeline=spec.primary_timeline,
                timeline_unit=spec.effective_timeline_unit or spec.timeline_unit,
                timeline_sort=spec.timeline_sort,
                cache_dir=str(cache_dir),
                progress_callback=report_progress,
                cancel_check=check_cancel,
                poll_subprocess=_background_job,
            )
            self._adapter_for_path(source_row["uri"], source_row["type"]).convert(request)
            check_cancel()
            if _manage_job and job_id is not None:
                self._update_job(
                    job_id,
                    status="running",
                    progress=0.8,
                    stage="blueprint",
                )
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
            result = {
                "job_id": job_id or "",
                "status": "succeeded",
                "recording_id": recording_db_id,
                "recording_path": str(recording_path),
                "blueprint_path": str(blueprint_path),
            }
            if _manage_job and job_id is not None:
                self._update_job(
                    job_id,
                    status="succeeded",
                    progress=1.0,
                    stage="completed",
                    result=result,
                    finished=True,
                )
            return result
        except Exception as exc:
            for path in reserved_paths:
                path.unlink(missing_ok=True)
            if recording_db_id is not None:
                with self._connect() as conn:
                    conn.execute("delete from query_rows where recording_id = ?", (recording_db_id,))
                    conn.execute("delete from recordings where id = ?", (recording_db_id,))
            if _manage_job and job_id is not None:
                cancelled = isinstance(exc, JobCancelled)
                self._update_job(
                    job_id,
                    status="cancelled" if cancelled else "failed",
                    progress=1.0,
                    stage="cancelled" if cancelled else "failed",
                    error=None if cancelled else _structured_error(exc),
                    error_message=None if cancelled else str(exc),
                    finished=True,
                )
            raise
        finally:
            shutil.rmtree(cache_dir, ignore_errors=True)

    def _assert_artifact_paths_available(
        self,
        project_id: str,
        recording_path: Path,
        blueprint_path: Path,
    ) -> None:
        target_paths = (recording_path, blueprint_path)
        conflicts = {path for path in target_paths if path.exists()}
        with self._connect() as conn:
            rows = conn.execute(
                """
                select path, blueprint_path
                from recordings
                where project_id = ? and (path = ? or blueprint_path = ?)
                """,
                (project_id, str(recording_path), str(blueprint_path)),
            ).fetchall()
        for row in rows:
            for key in ("path", "blueprint_path"):
                value = row[key]
                if value:
                    path = Path(value)
                    if path in target_paths:
                        conflicts.add(path)
        if conflicts:
            raise ArtifactConflictError(
                recording_path.stem,
                sorted(conflicts, key=str),
            )

    def _reserve_artifact_paths(
        self,
        recording_path: Path,
        blueprint_path: Path,
    ) -> list[Path]:
        reserved: list[Path] = []
        try:
            for path in (recording_path, blueprint_path):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch(exist_ok=False)
                reserved.append(path)
        except Exception as exc:
            for path in reserved:
                path.unlink(missing_ok=True)
            if isinstance(exc, FileExistsError):
                conflicts = [
                    path
                    for path in (recording_path, blueprint_path)
                    if path.exists()
                ]
                raise ArtifactConflictError(
                    recording_path.stem,
                    conflicts,
                ) from exc
            raise
        return reserved

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

    def batch_import(
        self,
        project_id: str,
        patterns: list[str],
        template_id: str = "sensor_monitor",
        output_prefix: str = "batch_run",
        storage_mode: str = "copy",
        *,
        _job_id: str | None = None,
        _resume_batch_id: str | None = None,
    ) -> dict[str, Any]:
        self.get_project(project_id)
        if storage_mode not in {"copy", "reference"}:
            raise ValueError(f"Unsupported storage mode: {storage_mode}")
        paths = _resolve_patterns(patterns)
        if not paths:
            raise ValueError("Batch import did not match any source paths")

        if _resume_batch_id:
            batch_id = _resume_batch_id
            batch = self.get_batch(batch_id)
            if batch["project_id"] != project_id:
                raise ValueError("Batch retry project does not match")
            with self._connect() as conn:
                conn.execute(
                    """
                    update batch_jobs set status = 'running', job_id = ?, updated_at = ?
                    where id = ?
                    """,
                    (_job_id, _now(), batch_id),
                )
            path_indexes = {str(path): index for index, path in enumerate(paths, start=1)}
            work_items = []
            for item in batch["items"]:
                if item["status"] == "succeeded":
                    continue
                source_path = Path(item["source_path"])
                index = path_indexes.get(str(source_path))
                if index is None:
                    raise ValueError(
                        f"Batch retry source is missing from the original payload: {source_path}"
                    )
                work_items.append(
                    (item["id"], index, source_path, item.get("source_id"))
                )
            work_items.sort(key=lambda item: item[1])
        else:
            batch_id = f"batch_{uuid4().hex[:12]}"
            now = _now()
            with self._connect() as conn:
                conn.execute(
                    """
                    insert into batch_jobs
                      (id, project_id, job_id, status, total, succeeded, failed, created_at, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (batch_id, project_id, _job_id, "running", len(paths), 0, 0, now, now),
                )
                work_items = []
                for index, path in enumerate(paths, start=1):
                    item_id = f"batch_item_{uuid4().hex[:12]}"
                    conn.execute(
                        """
                        insert into batch_items
                          (id, batch_id, source_path, source_id, recording_id, status,
                           error_message, attempt, created_at, updated_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item_id,
                            batch_id,
                            str(path),
                            None,
                            None,
                            "pending",
                            None,
                            1,
                            now,
                            now,
                        ),
                    )
                    work_items.append((item_id, index, path, None))

        if _job_id is not None:
            self._set_job_resource(_job_id, "batch", batch_id)

        for completed, (item_id, index, path, existing_source_id) in enumerate(
            work_items,
            start=1,
        ):
            if _job_id is not None:
                self._check_job_cancelled(_job_id)
            with self._connect() as conn:
                conn.execute(
                    """
                    update batch_items
                    set status = 'running', error_message = null, attempt = attempt + ?,
                        updated_at = ?
                    where id = ?
                    """,
                    (1 if _resume_batch_id else 0, _now(), item_id),
                )
            source: dict[str, Any] | None = None
            created_source = existing_source_id is None

            def discard_failed_source() -> None:
                if created_source and source is not None:
                    try:
                        self._discard_uncommitted_source(source["id"])
                    except Exception:
                        pass

            try:
                source = (
                    self.get_source(existing_source_id)
                    if existing_source_id
                    else self.add_source(project_id, str(path), storage_mode=storage_mode)
                )
                self.inspect_source(source["id"])
                spec = self.suggest_mapping(source["id"], template_id=template_id)
                mapping = self.save_mapping(project_id, source["id"], spec)
                result = self.build_recording(
                    project_id,
                    source["id"],
                    mapping_id=mapping["id"],
                    template_id=template_id,
                    output_name=f"{output_prefix}_{index:03d}",
                    _manage_job=False,
                    _cancel_check=(
                        (lambda: self._check_job_cancelled(_job_id))
                        if _job_id is not None
                        else None
                    ),
                )
                with self._connect() as conn:
                    conn.execute(
                        """
                        update batch_items
                        set source_id = ?, recording_id = ?, status = ?, error_message = ?, updated_at = ?
                        where id = ?
                        """,
                        (source["id"], result["recording_id"], "succeeded", None, _now(), item_id),
                    )
            except JobCancelled:
                discard_failed_source()
                with self._connect() as conn:
                    conn.execute(
                        "update batch_items set status = 'pending', updated_at = ? where id = ?",
                        (_now(), item_id),
                    )
                raise
            except Exception as exc:
                discard_failed_source()
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
                counts = conn.execute(
                    """
                    select
                      sum(case when status = 'succeeded' then 1 else 0 end) as succeeded,
                      sum(case when status = 'failed' then 1 else 0 end) as failed
                    from batch_items where batch_id = ?
                    """,
                    (batch_id,),
                ).fetchone()
                succeeded = int(counts["succeeded"] or 0)
                failed = int(counts["failed"] or 0)
                conn.execute(
                    """
                    update batch_jobs
                    set succeeded = ?, failed = ?, status = ?, updated_at = ?
                    where id = ?
                    """,
                    (
                        succeeded,
                        failed,
                        "running"
                        if succeeded + failed < len(paths)
                        else ("failed" if failed else "succeeded"),
                        _now(),
                        batch_id,
                    ),
                )
            if _job_id is not None:
                self._update_job(
                    _job_id,
                    status="running",
                    progress=completed / max(len(work_items), 1),
                    stage="batch_import",
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
