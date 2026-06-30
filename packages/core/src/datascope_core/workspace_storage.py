from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from datascope_core.models import detect_source_type
from datascope_core.workspace_utils import (
    artifact_paths,
    copy_parent_sidecars,
    disk_estimate,
    row_to_dict,
    source_checksum,
    source_size,
    utc_now,
)


class DiskSpaceError(RuntimeError):
    code = "insufficient_disk_space"

    def __init__(self, estimate: dict[str, Any]) -> None:
        self.estimate = estimate
        super().__init__(
            "Insufficient disk space: "
            f"{estimate['required']} bytes required, "
            f"{estimate.get('free')} bytes available"
        )


class SourceUnavailableError(RuntimeError):
    def __init__(self, code: str, message: str, source_id: str) -> None:
        self.code = code
        self.source_id = source_id
        super().__init__(message)


class WorkspaceStorageMixin:
    def add_source(
        self,
        project_id: str,
        path: str,
        storage_mode: str = "copy",
        import_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        if storage_mode not in {"copy", "reference"}:
            raise ValueError(f"Unsupported storage mode: {storage_mode}")
        source_id = f"source_{uuid4().hex[:12]}"
        source_path = Path(path).expanduser().resolve()
        if not source_path.exists():
            raise ValueError(f"Source path does not exist: {source_path}")
        try:
            source_type = detect_source_type(source_path)
        except ValueError:
            source_type = self._detect_plugin_source_type(source_path)

        estimate = self.estimate_source_import(
            project_id,
            str(source_path),
            storage_mode=storage_mode,
        )
        self._ensure_disk(estimate)

        stored_path = source_path
        if storage_mode == "copy":
            raw_dir = Path(project["workspace_path"]) / "raw" / source_id
            raw_dir.mkdir(parents=True, exist_ok=True)
            stored_path = raw_dir / source_path.name
            if source_path.is_dir():
                if stored_path.exists():
                    shutil.rmtree(stored_path)
                shutil.copytree(source_path, stored_path)
                copy_parent_sidecars(source_path, raw_dir)
            elif source_path != stored_path:
                shutil.copy2(source_path, stored_path)
            if source_path.suffix.lower() == ".db3":
                copy_parent_sidecars(source_path, raw_dir)

        now = utc_now()
        with self._connect() as conn:
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
                    source_type,
                    str(stored_path),
                    source_checksum(stored_path),
                    source_size(stored_path),
                    "imported",
                    json.dumps(
                        {"import_options": import_options or {}},
                        ensure_ascii=False,
                    ),
                    storage_mode,
                    str(source_path),
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
        result = row_to_dict(row)
        result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
        result["available"] = Path(result["uri"]).exists()
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
            result = row_to_dict(row)
            result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
            result["available"] = Path(result["uri"]).exists()
            results.append(result)
        return results

    def _discard_uncommitted_source(self, source_id: str) -> None:
        source = self.get_source(source_id)
        with self._connect() as conn:
            committed = conn.execute(
                "select 1 from recordings where source_id = ? limit 1",
                (source_id,),
            ).fetchone()
            if committed is not None:
                return
            mapping_rows = conn.execute(
                "select path from mappings where source_id = ?",
                (source_id,),
            ).fetchall()
            conn.execute("delete from mappings where source_id = ?", (source_id,))
            conn.execute("delete from streams where source_id = ?", (source_id,))
            conn.execute("delete from sources where id = ?", (source_id,))

        for row in mapping_rows:
            Path(row["path"]).unlink(missing_ok=True)
        if source["storage_mode"] == "copy":
            project = self.get_project(source["project_id"])
            raw_dir = Path(project["workspace_path"]) / "raw" / source_id
            shutil.rmtree(raw_dir, ignore_errors=True)

    def estimate_source_import(
        self,
        project_id: str,
        path: str,
        storage_mode: str = "copy",
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        source_path = Path(path).expanduser().resolve()
        if not source_path.exists():
            raise ValueError(f"Source path does not exist: {source_path}")
        if storage_mode not in {"copy", "reference"}:
            raise ValueError(f"Unsupported storage mode: {storage_mode}")
        estimated = source_size(source_path) if storage_mode == "copy" else 0
        warnings = (
            ["Reference mode does not reserve space for the external source."]
            if storage_mode == "reference"
            else []
        )
        return disk_estimate(
            "source_import",
            estimated,
            Path(project["workspace_path"]),
            confidence="high",
            warnings=warnings,
        )

    def estimate_build(
        self,
        project_id: str,
        source_id: str,
        output_dir: str | None = None,
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        source = self.get_source(source_id)
        self._assert_source_available(source)
        source_bytes = int(source.get("size_bytes") or 0)
        warnings: list[str] = []
        confidence = "medium"
        if source["type"] == "ros2_db3":
            estimated = source_bytes * 3
        elif source["type"] in {"csv", "jsonl", "text_table"}:
            estimated = source_bytes * 2
            with self._connect() as conn:
                row = conn.execute(
                    "select config_json from mappings where source_id = ? order by updated_at desc limit 1",
                    (source_id,),
                ).fetchone()
            if row is not None:
                config = json.loads(row["config_json"] or "{}")
                timeline = config.get("mapping", {}).get("timelines", {}).get("primary", {})
                if timeline.get("sort") == "ascending":
                    estimated += source_bytes * 2
        else:
            estimated = max(source_bytes * 2, 64 * 1024 * 1024)
            if self._plugin_adapter_for_type(source["type"]) is not None:
                confidence = "low"
                warnings.append("Plugin storage estimate is approximate.")
        return disk_estimate(
            "build",
            estimated,
            Path(output_dir).expanduser() if output_dir else Path(project["workspace_path"]),
            confidence=confidence,
            warnings=warnings,
        )

    def estimate_batch_import(
        self,
        project_id: str,
        patterns: list[str],
        storage_mode: str = "copy",
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        if storage_mode not in {"copy", "reference"}:
            raise ValueError(f"Unsupported storage mode: {storage_mode}")
        from datascope_core.workspace_utils import resolve_patterns

        paths = resolve_patterns(patterns)
        if not paths:
            raise ValueError("Batch import did not match any source paths")
        estimated = 0
        warnings: list[str] = []
        for path in paths:
            if storage_mode == "copy":
                estimated += source_size(path)
            estimated += max(source_size(path) * 2, 64 * 1024 * 1024)
        if storage_mode == "reference":
            warnings.append("Reference mode does not reserve space for external sources.")
        return disk_estimate(
            "batch_import",
            estimated,
            Path(project["workspace_path"]),
            confidence="medium",
            warnings=warnings,
        )

    def estimate_project_export(
        self,
        project_id: str,
        output_path: str | None = None,
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        project_path = Path(project["workspace_path"])
        output = self._project_export_path(project, project_path, "estimate", output_path)
        estimated = 0
        warnings: list[str] = []
        for path_value in artifact_paths(self._project_manifest(project_id)):
            path = Path(path_value)
            if not path.exists():
                warnings.append(f"Missing artifact: {path}")
                continue
            estimated += source_size(path)
        return disk_estimate(
            "project_export",
            estimated,
            output.parent,
            confidence="medium",
            warnings=warnings,
        )

    @staticmethod
    def _ensure_disk(estimate: dict[str, Any]) -> None:
        if estimate["sufficient"] is False:
            raise DiskSpaceError(estimate)

    def _assert_source_available(self, source: dict[str, Any]) -> None:
        path = Path(source["uri"])
        if not path.exists():
            raise SourceUnavailableError(
                "source_unavailable",
                f"Source path is unavailable: {path}",
                source["id"],
            )
        if source.get("storage_mode") != "reference":
            return
        if source_checksum(path) != source["checksum"]:
            raise SourceUnavailableError(
                "source_changed",
                f"Referenced source changed since import: {path}",
                source["id"],
            )
