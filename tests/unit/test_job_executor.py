from __future__ import annotations

import sys

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
