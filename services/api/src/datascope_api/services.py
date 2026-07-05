from __future__ import annotations

import os
import logging
import subprocess
import threading
from pathlib import Path

from datascope_core.job_supervisor import JobSupervisor
from datascope_core.rerun_artifacts import LOCAL_CATALOG_URL
from datascope_core.rerun_cli import rerun_command, rerun_subprocess_env
from datascope_core.workspace import Workspace, default_workspace_path


logger = logging.getLogger("uvicorn.error.datascope.services")


class AppServices:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._root: Path | None = None
        self._workspace: Workspace | None = None
        self._supervisor: JobSupervisor | None = None
        self._catalog_process: subprocess.Popen[bytes] | None = None
        self._max_workers = int(os.environ.get("DATASCOPE_MAX_WORKERS", "1"))
        self._warmup_thread: threading.Thread | None = None

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

    def warm_workspace(self) -> None:
        with self._lock:
            if self._warmup_thread is not None and self._warmup_thread.is_alive():
                return
            self._warmup_thread = threading.Thread(
                target=self._warm_workspace,
                name="datascope-workspace-warmup",
                daemon=True,
            )
            self._warmup_thread.start()

    def _warm_workspace(self) -> None:
        try:
            self.workspace()
        except Exception:
            logger.exception("workspace_warmup_failed")

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

    def ensure_local_catalog_server(self) -> str:
        with self._lock:
            if self._catalog_process is not None and self._catalog_process.poll() is None:
                return LOCAL_CATALOG_URL
            self._catalog_process = subprocess.Popen(
                [
                    *rerun_command(),
                    "server",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "51234",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=rerun_subprocess_env(),
            )
            return LOCAL_CATALOG_URL

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        if self._supervisor is not None:
            self._supervisor.stop()
        if self._catalog_process is not None and self._catalog_process.poll() is None:
            self._catalog_process.terminate()
            try:
                self._catalog_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._catalog_process.kill()
                self._catalog_process.wait(timeout=3)
        self._supervisor = None
        self._catalog_process = None
        self._workspace = None


services = AppServices()
