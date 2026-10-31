from __future__ import annotations

import sys
import sqlite3

import pytest

import datascope_core.job_executor as job_executor


def test_job_executor_writes_traceback_for_unhandled_failure(
    monkeypatch,
    capsys,
) -> None:
    class FailingWorkspace:
        def __init__(self, _):
            pass

        def set_job_worker_pid(self, *_):
            pass

        def execute_job(self, *_):
            raise RuntimeError("point cloud conversion crashed")

        def heartbeat_job(self, *_):
            pass

    monkeypatch.setattr(job_executor, "Workspace", FailingWorkspace)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "job_executor",
            "--workspace",
            "/tmp/workspace",
            "--job",
            "job_failure",
            "--token",
            "worker_token",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        job_executor.main()

    assert exc_info.value.code == 1
    stderr = capsys.readouterr().err
    assert "Traceback" in stderr
    assert "RuntimeError: point cloud conversion crashed" in stderr


def test_heartbeat_retries_only_sqlite_lock_conflicts():
    class Stop:
        calls = 0
        def wait(self, _):
            self.calls += 1
            return self.calls > 2
    class Workspace:
        calls = 0
        def heartbeat_job(self, *_):
            self.calls += 1
            if self.calls == 1:
                raise sqlite3.OperationalError('database is locked')
    workspace = Workspace()
    job_executor._heartbeat_loop(workspace, 'job', 'token', Stop())
    assert workspace.calls == 2
    class Broken:
        def heartbeat_job(self, *_):
            raise sqlite3.OperationalError('database disk image is malformed')
    with pytest.raises(sqlite3.OperationalError, match='malformed'):
        job_executor._heartbeat_loop(Broken(), 'job', 'token', Stop())


def test_typed_worker_recovery_checks_job_command_when_heartbeat_is_blocked(monkeypatch):
    import datascope_core.job_supervisor as supervisor
    job = {'id': 'job_expected', 'worker_pid': 123,
           'heartbeat_at': '2020-01-01T00:00:00+00:00', 'payload': {'query_storage': 'typed_sqlite'}}
    monkeypatch.setattr(supervisor, '_pid_command_matches_job', lambda pid, key: (pid, key) == (123, 'job_expected'))
    assert supervisor._worker_is_live(job)
    monkeypatch.setattr(supervisor, '_pid_command_matches_job', lambda *_: False)
    assert not supervisor._worker_is_live(job)
