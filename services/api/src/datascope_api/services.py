from __future__ import annotations

import os
import threading
from pathlib import Path

from datascope_core.job_supervisor import JobSupervisor
from datascope_core.workspace import Workspace, default_workspace_path


class AppServices:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._root: Path | None = None
        self._workspace: Workspace | None = None
        self._supervisor: JobSupervisor | None = None
        self._max_workers = int(os.environ.get("DATASCOPE_MAX_WORKERS", "1"))

    def workspace(self) -> Workspace:
        root = Path(os.environ.get("DATASCOPE_WORKSPACE") or default_workspace_path())
        with self._lock:
            if self._workspace is None or self._root != root:
                self._stop_locked()
                self._root = root
                self._workspace = Workspace(root)
            return self._workspace

    def supervisor(self) -> JobSupervisor:
        workspace = self.workspace()
        with self._lock:
            if self._supervisor is None:
                self._supervisor = JobSupervisor(workspace, max_workers=self._max_workers)
                self._supervisor.start()
            return self._supervisor

    def job_settings(self) -> dict[str, int]:
        with self._lock:
            return {"max_workers": self._max_workers}

    def update_job_settings(self, *, max_workers: int) -> dict[str, int]:
        if max_workers < 1 or max_workers > 4:
            raise ValueError("max_workers must be between 1 and 4")
        with self._lock:
            self._max_workers = max_workers
            if self._supervisor is not None:
                self._supervisor.max_workers = max_workers
            return {"max_workers": self._max_workers}

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        if self._supervisor is not None:
            self._supervisor.stop()
        self._supervisor = None
        self._workspace = None


services = AppServices()
