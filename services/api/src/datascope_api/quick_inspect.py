from __future__ import annotations

import gc
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from datascope_core.mapping import mapping_from_yaml_dict
from datascope_core.models import MappingSpec
from datascope_core.workspace import Workspace

from datascope_api.workflows import run_import_workflow


@dataclass
class QuickInspectSession:
    id: str
    root: Path
    workspace: Workspace
    project_id: str
    source_id: str
    mapping_id: str
    template_id: str


class QuickInspectSessionManager:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._active: QuickInspectSession | None = None

    def cleanup_stale(self) -> None:
        with self._lock:
            self._cleanup_stale_locked()

    def cleanup(self) -> None:
        with self._lock:
            self._cleanup_active_locked()
            self._cleanup_stale_locked()

    def start(
        self,
        *,
        path: str,
        storage_mode: str = "copy",
        import_options: dict[str, Any] | None = None,
        template_id: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._cleanup_active_locked()
            self._cleanup_stale_locked()
            session_id = f"session_{uuid4().hex[:12]}"
            session_root = self.root / session_id
            workspace = Workspace(session_root)
            project = workspace.create_project("Quick Inspect")
            result = run_import_workflow(
                workspace,
                project["id"],
                path=path,
                storage_mode=storage_mode,
                import_options=import_options,
                template_id=template_id,
            )
            self._active = QuickInspectSession(
                id=session_id,
                root=session_root,
                workspace=workspace,
                project_id=project["id"],
                source_id=result["source"]["id"],
                mapping_id=result["saved_mapping"]["id"],
                template_id=result["template_id"],
            )
            return {"session_id": session_id, **result}

    def save_mapping(
        self,
        session_id: str,
        *,
        mapping: dict[str, Any] | None,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            session = self._session_locked(session_id)
            spec = self._mapping_spec(session, mapping)
            saved = session.workspace.save_mapping(
                session.project_id,
                session.source_id,
                spec,
                confirmed=confirmed,
            )
            session.mapping_id = saved["id"]
            return saved

    def validate_mapping(
        self,
        session_id: str,
        *,
        mapping: dict[str, Any] | None,
    ) -> dict[str, Any]:
        with self._lock:
            session = self._session_locked(session_id)
            spec = self._mapping_spec(session, mapping)
            return session.workspace.validate_mapping_spec(session.source_id, spec)

    def confirm_mapping(
        self,
        session_id: str,
        *,
        mapping: dict[str, Any] | None,
    ) -> dict[str, Any]:
        with self._lock:
            session = self._session_locked(session_id)
            if mapping is not None:
                spec = self._mapping_spec(session, mapping)
                saved = session.workspace.save_mapping(
                    session.project_id,
                    session.source_id,
                    spec,
                )
                session.mapping_id = saved["id"]
            result = session.workspace.confirm_mapping(session.mapping_id)
            session.mapping_id = result["mapping"]["id"]
            return result

    def suggest_template_mapping(
        self,
        session_id: str,
        *,
        template_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            session = self._session_locked(session_id)
            spec = session.workspace.suggest_mapping(
                session.source_id,
                template_id=template_id,
            )
            saved_mapping = session.workspace.save_mapping(
                session.project_id,
                session.source_id,
                spec,
            )
            mapping_preview = session.workspace.mapping_preview(session.source_id, spec)
            session.mapping_id = saved_mapping["id"]
            session.template_id = template_id
            return {
                "template_id": template_id,
                "mapping": {"mapping": mapping_preview["mapping"]},
                "saved_mapping": saved_mapping,
                "preview": mapping_preview["preview"],
                "schema_profile": mapping_preview["schema_profile"],
                "validation": mapping_preview["validation"],
            }

    def build(
        self,
        session_id: str,
        *,
        output_name: str | None = None,
        template_id: str = "sensor_monitor",
        output_dir: str | None = None,
        mcap_decoders: list[str] | None = None,
        rrd_optimize_profile: str = "none",
        artifact_validation: str = "basic",
        catalog_registration: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            session = self._session_locked(session_id)
            return session.workspace.build_recording(
                session.project_id,
                session.source_id,
                mapping_id=session.mapping_id,
                output_name=output_name,
                template_id=template_id,
                output_dir=output_dir,
                mcap_decoders=mcap_decoders,
                rrd_optimize_profile=rrd_optimize_profile,
                artifact_validation=artifact_validation,
                catalog_registration=catalog_registration,
                _manage_job=False,
            )

    def clear(self, session_id: str) -> dict[str, str]:
        with self._lock:
            session = self._session_locked(session_id)
            root = session.root
            self._active = None
            del session
            gc.collect()
            self._remove_session_root(root)
            return {"deleted": session_id}

    def _session_locked(self, session_id: str) -> QuickInspectSession:
        if self._active is None or self._active.id != session_id:
            raise KeyError(f"Quick Inspect session not found: {session_id}")
        return self._active

    def _mapping_spec(
        self,
        session: QuickInspectSession,
        mapping: dict[str, Any] | None,
    ) -> MappingSpec:
        if mapping is not None:
            return mapping_from_yaml_dict({"mapping": mapping})
        saved = session.workspace.get_mapping(session.mapping_id)
        return mapping_from_yaml_dict(saved["config"])

    def _cleanup_active_locked(self) -> None:
        if self._active is not None:
            session = self._active
            root = session.root
            self._active = None
            del session
            gc.collect()
            self._remove_session_root(root)

    def _cleanup_stale_locked(self) -> None:
        if not self.root.exists():
            return
        for child in self.root.iterdir():
            if child.is_dir() and child.name.startswith("session_"):
                if self._active is not None and child == self._active.root:
                    continue
                self._remove_session_root(child)

    def _remove_session_root(self, path: Path) -> None:
        resolved = path.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            message = f"Refusing to remove path outside Quick Inspect root: {resolved}"
            raise ValueError(message) from exc
        if not resolved.name.startswith("session_"):
            raise ValueError(f"Refusing to remove non-session path: {resolved}")
        shutil.rmtree(resolved, ignore_errors=True)
