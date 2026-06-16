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
                self._supervisor = JobSupervisor(workspace)
                self._supervisor.start()
            return self._supervisor

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        if self._supervisor is not None:
            self._supervisor.stop()
        self._supervisor = None
        self._workspace = None


services = AppServices()
