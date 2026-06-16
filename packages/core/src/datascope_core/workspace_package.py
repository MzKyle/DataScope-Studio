from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from datascope_core.version import __version__
from datascope_core.workspace_utils import (
    archive_name,
    artifact_paths,
    json_array_text,
    json_object,
    json_object_text,
    relocated_artifact_path,
    row_to_dict,
    safe_extract_zip,
    safe_output_name,
    source_checksum,
    utc_now,
)


class WorkspacePackageMixin:
    root: Path

    def export_project(
        self,
        project_id: str,
        output_path: str | None = None,
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        project_path = Path(project["workspace_path"])
        export_id = f"project_export_{uuid4().hex[:12]}"
        output = self._project_export_path(project, project_path, export_id, output_path)
        self._ensure_disk(self.estimate_project_export(project_id, str(output)))
        output.parent.mkdir(parents=True, exist_ok=True)
        manifest = self._project_manifest(project_id)
        source_archives: dict[str, str] = {}
        for source in manifest["sources"]:
            if source.get("storage_mode") != "reference":
                continue
            current = self.get_source(source["id"])
            self._assert_source_available(current)
            path = Path(current["uri"])
            archive_root = f"raw/{source['id']}/{path.name}"
            source_archives[source["id"]] = archive_root
            source["uri"] = str(project_path / archive_root)
            source["storage_mode"] = "copy"
            source["original_uri"] = current.get("original_uri") or current["uri"]

        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )
            reference_paths = {
                source["id"]: Path(self.get_source(source["id"])["uri"])
                for source in manifest["sources"]
                if source["id"] in source_archives
            }
            for source_id, path in reference_paths.items():
                _write_path(archive, path, source_archives[source_id])
            for path_value in artifact_paths(manifest):
                path = Path(path_value)
                if not path.exists() or path.resolve() == output.resolve():
                    continue
                if any(path == value for value in reference_paths.values()):
                    continue
                _write_path(archive, path, archive_name(project_path, path))
        return {
            "export_id": export_id,
            "path": str(output),
            "format": "zip",
            "project_id": project_id,
        }

    def import_project_package(
        self,
        package_path: str,
        project_name: str | None = None,
    ) -> dict[str, Any]:
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

        original_project_id = str(
            project_manifest.get("id") or f"project_{uuid4().hex[:12]}"
        )
        project_id = self._available_id("projects", original_project_id, "project")
        project_path = self.root / "projects" / project_id
        while project_path.exists() and any(project_path.iterdir()):
            project_id = f"project_{uuid4().hex[:12]}"
            project_path = self.root / "projects" / project_id

        self._ensure_project_dirs(project_path)
        with zipfile.ZipFile(package) as archive:
            safe_extract_zip(archive, project_path)

        original_project_path = Path(project_manifest.get("workspace_path") or "")
        now = utc_now()
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
                old_source_id = str(
                    source.get("id") or f"source_{uuid4().hex[:12]}"
                )
                source_id = self._available_id(
                    "sources",
                    old_source_id,
                    "source",
                    conn=conn,
                )
                source_id_map[old_source_id] = source_id
                uri = relocated_artifact_path(
                    source.get("uri"),
                    original_project_path,
                    project_path,
                )
                checksum = str(source.get("checksum") or "")
                if not checksum and uri and Path(uri).exists():
                    checksum = source_checksum(Path(uri))
                conn.execute(
                    """
                    insert into sources
                      (id, project_id, type, uri, checksum, size_bytes, status, metadata_json,
                       storage_mode, original_uri, created_at, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        project_id,
                        source.get("type") or "unknown",
                        uri or "",
                        checksum,
                        int(source.get("size_bytes") or 0),
                        source.get("status") or "imported",
                        source.get("metadata_json")
                        or json.dumps(source.get("metadata") or {}),
                        "copy",
                        source.get("original_uri") or source.get("uri"),
                        source.get("created_at") or now,
                        source.get("updated_at") or now,
                    ),
                )

            for mapping in manifest.get("mappings", []):
                old_mapping_id = str(
                    mapping.get("id") or f"mapping_{uuid4().hex[:12]}"
                )
                mapping_id = self._available_id(
                    "mappings",
                    old_mapping_id,
                    "mapping",
                    conn=conn,
                )
                config = json_object(
                    mapping.get("config_json"),
                    mapping.get("config") or {},
                )
                if isinstance(config.get("mapping"), dict):
                    config["mapping"]["id"] = mapping_id
                    old_source = config["mapping"].get("source")
                    if old_source in source_id_map:
                        config["mapping"]["source"] = source_id_map[old_source]
                source_id = source_id_map.get(mapping.get("source_id")) or next(
                    iter(source_id_map.values()),
                    None,
                )
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
                        relocated_artifact_path(
                            mapping.get("path"),
                            original_project_path,
                            project_path,
                        )
                        or "",
                        mapping.get("created_at") or now,
                        mapping.get("updated_at") or now,
                    ),
                )

            recording_id_map: dict[str, str] = {}
            imported_recording_ids: list[str] = []
            for recording in manifest.get("recordings", []):
                old_recording_id = str(
                    recording.get("id") or f"recording_{uuid4().hex[:12]}"
                )
                recording_id = self._available_id(
                    "recordings",
                    old_recording_id,
                    "recording",
                    conn=conn,
                )
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
                        relocated_artifact_path(
                            recording.get("path"),
                            original_project_path,
                            project_path,
                        )
                        or "",
                        recording.get("blueprint_id"),
                        relocated_artifact_path(
                            recording.get("blueprint_path"),
                            original_project_path,
                            project_path,
                        ),
                        recording.get("run_name")
                        or Path(str(recording.get("path") or "recording")).stem,
                        json_array_text(
                            recording.get("tags_json"),
                            recording.get("tags"),
                        ),
                        json_object_text(
                            recording.get("params_json"),
                            recording.get("params"),
                        ),
                        recording.get("created_at") or now,
                    ),
                )

            for export in manifest.get("query_exports", []):
                export_id = self._available_id(
                    "query_exports",
                    str(export.get("id") or f"export_{uuid4().hex[:12]}"),
                    "export",
                    conn=conn,
                )
                conn.execute(
                    """
                    insert into query_exports (id, project_id, recording_id, path, format, created_at)
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        export_id,
                        project_id,
                        recording_id_map.get(
                            export.get("recording_id"),
                            export.get("recording_id"),
                        ),
                        relocated_artifact_path(
                            export.get("path"),
                            original_project_path,
                            project_path,
                        )
                        or "",
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

    def _project_manifest(self, project_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        with self._connect() as conn:
            sources = [
                row_to_dict(row)
                for row in conn.execute(
                    "select * from sources where project_id = ?",
                    (project_id,),
                )
            ]
            mappings = [
                row_to_dict(row)
                for row in conn.execute(
                    "select * from mappings where project_id = ?",
                    (project_id,),
                )
            ]
            recordings = [
                self.get_recording(row["id"])
                for row in conn.execute(
                    "select id from recordings where project_id = ?",
                    (project_id,),
                )
            ]
            exports = [
                row_to_dict(row)
                for row in conn.execute(
                    "select * from query_exports where project_id = ?",
                    (project_id,),
                )
            ]
        return {
            "datascope_version": __version__,
            "project": project,
            "sources": sources,
            "mappings": mappings,
            "recordings": recordings,
            "query_exports": exports,
            "templates": self.list_templates(),
            "created_at": utc_now(),
        }

    def _project_export_path(
        self,
        project: dict[str, Any],
        project_path: Path,
        export_id: str,
        output_path: str | None,
    ) -> Path:
        filename = f"{safe_output_name(project['name'])}_{export_id}.zip"
        if output_path:
            requested = Path(output_path).expanduser()
            if requested.suffix.lower() == ".zip":
                return requested
            return requested / filename
        if self.root.expanduser().resolve() == (Path.home() / ".datascope-studio").resolve():
            return Path.home() / "DataScope Studio Exports" / filename
        return project_path / "exports" / filename


def _write_path(archive: zipfile.ZipFile, path: Path, archive_root: str) -> None:
    if path.is_dir():
        for child in sorted(item for item in path.rglob("*") if item.is_file()):
            relative = child.relative_to(path)
            archive.write(child, str(Path(archive_root) / relative))
    else:
        archive.write(path, archive_root)
