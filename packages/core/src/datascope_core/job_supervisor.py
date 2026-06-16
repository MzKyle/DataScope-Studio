from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from datascope_core.workspace import Workspace


@dataclass
class Worker:
    job_id: str
    token: str
    process: subprocess.Popen[bytes]
    cancel_seen_at: float | None = None


class JobSupervisor:
    def __init__(
        self,
        workspace: Workspace,
        *,
        max_workers: int | None = None,
        poll_interval: float = 0.2,
        cancel_grace_seconds: float = 2.0,
    ) -> None:
        configured = max_workers or int(os.environ.get("DATASCOPE_MAX_WORKERS", "1"))
        self.workspace = workspace
        self.max_workers = max(configured, 1)
        self.poll_interval = poll_interval
        self.cancel_grace_seconds = cancel_grace_seconds
        self._workers: dict[str, Worker] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._recover_workers()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="datascope-job-supervisor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        with self._lock:
            workers = list(self._workers.values())
        for worker in workers:
            _terminate_process_tree(worker.process)
            self.workspace.mark_job_worker_exit(
                worker.job_id,
                return_code=worker.process.poll() or -1,
                cancelled=True,
            )
        with self._lock:
            self._workers.clear()

    def wake(self) -> None:
        self.start()

    def _run(self) -> None:
        while not self._stop.wait(self.poll_interval):
            self._reap_workers()
            self._handle_cancellations()
            self._start_pending_workers()

    def _recover_workers(self) -> None:
        stale_job_ids = []
        for job in self.workspace.active_jobs():
            pid = job.get("worker_pid")
            if _worker_is_live(job):
                continue
            stale_job_ids.append(job["id"])
            if (
                isinstance(pid, int)
                and pid > 0
                and _pid_command_matches_job(pid, job["id"])
            ):
                _terminate_pid_tree(pid)
        self.workspace.interrupt_running_jobs(stale_job_ids)

    def _start_pending_workers(self) -> None:
        with self._lock:
            owned_job_ids = set(self._workers)
        external_active = sum(
            1
            for job in self.workspace.active_jobs()
            if job["id"] not in owned_job_ids
        )
        with self._lock:
            capacity = self.max_workers - len(self._workers) - external_active
        if capacity <= 0:
            return
        for job in self.workspace.pending_jobs(capacity):
            token = uuid4().hex
            if not self.workspace.claim_job(job["id"], token):
                continue
            try:
                worker = self._spawn(job["id"], token, job.get("log_path"))
            except Exception:
                self.workspace.mark_job_worker_exit(
                    job["id"],
                    return_code=-1,
                    cancelled=False,
                )
                continue
            self.workspace.set_job_worker_pid(job["id"], token, worker.process.pid)
            with self._lock:
                self._workers[job["id"]] = worker

    def _spawn(self, job_id: str, token: str, log_path: str | None) -> Worker:
        log_file = None
        stdout: int | object = subprocess.DEVNULL
        if log_path:
            path = Path(log_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            log_file = open(path, "ab")
            stdout = log_file
        kwargs: dict[str, object] = {
            "stdout": stdout,
            "stderr": subprocess.STDOUT,
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "datascope_core.job_executor",
                    "--workspace",
                    str(self.workspace.root),
                    "--job",
                    job_id,
                    "--token",
                    token,
                ],
                **kwargs,
            )
        finally:
            if log_file is not None:
                log_file.close()
        return Worker(job_id=job_id, token=token, process=process)

    def _reap_workers(self) -> None:
        with self._lock:
            workers = list(self._workers.values())
        for worker in workers:
            return_code = worker.process.poll()
            if return_code is None:
                continue
            self.workspace.mark_job_worker_exit(
                worker.job_id,
                return_code=return_code,
                cancelled=return_code == 2,
            )
            with self._lock:
                self._workers.pop(worker.job_id, None)

    def _handle_cancellations(self) -> None:
        now = time.monotonic()
        with self._lock:
            workers = list(self._workers.values())
        for worker in workers:
            job = self.workspace.get_job(worker.job_id)
            if job["status"] != "cancel_requested":
                worker.cancel_seen_at = None
                continue
            if worker.cancel_seen_at is None:
                worker.cancel_seen_at = now
                continue
            if now - worker.cancel_seen_at < self.cancel_grace_seconds:
                continue
            _terminate_process_tree(worker.process)
            self.workspace.mark_job_worker_exit(
                worker.job_id,
                return_code=worker.process.poll() or -1,
                cancelled=True,
            )
            with self._lock:
                self._workers.pop(worker.job_id, None)


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()


def _terminate_pid_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    time.sleep(0.1)
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _worker_is_live(job: dict[str, object], stale_seconds: float = 5.0) -> bool:
    pid = job.get("worker_pid")
    heartbeat = job.get("heartbeat_at")
    if not isinstance(pid, int) or pid <= 0 or not isinstance(heartbeat, str):
        return False
    try:
        heartbeat_at = datetime.fromisoformat(heartbeat)
    except ValueError:
        return False
    if heartbeat_at.tzinfo is None:
        heartbeat_at = heartbeat_at.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - heartbeat_at).total_seconds()
    return age <= stale_seconds and _pid_exists(pid)


def _pid_exists(pid: int) -> bool:
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _pid_command_matches_job(pid: int, job_id: str) -> bool:
    if os.name == "nt":
        command = [
            "powershell",
            "-NoProfile",
            "-Command",
            f"(Get-CimInstance Win32_Process -Filter \"ProcessId = {pid}\").CommandLine",
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        return job_id in result.stdout and "datascope_core.job_executor" in result.stdout
    try:
        command_line = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
    except OSError:
        return False
    decoded = command_line.decode(errors="replace")
    return job_id in decoded and "datascope_core.job_executor" in decoded
