from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient


TERMINAL_JOB_STATUSES = {"cancelled", "succeeded", "failed", "interrupted"}


def wait_for_job(
    client: TestClient,
    job_id: str,
    *,
    timeout: float = 15.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["status"] in TERMINAL_JOB_STATUSES:
            return job
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} did not finish within {timeout} seconds")


def install_fake_rerun(tmp_path: Path, monkeypatch) -> Path:
    script = tmp_path / "fake_rerun.py"
    script.write_text(
        """#!/usr/bin/env python3
import sys
from pathlib import Path

output = Path(sys.argv[sys.argv.index("--output") + 1])
output.parent.mkdir(parents=True, exist_ok=True)
output.write_bytes(b"mock rrd")
""",
        encoding="utf-8",
    )
    if os.name == "nt":
        command = tmp_path / "fake_rerun.cmd"
        command.write_text(
            f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n',
            encoding="utf-8",
        )
    else:
        script.chmod(0o755)
        command = script
    monkeypatch.setenv("DATASCOPE_RERUN_BIN", str(command))
    return command
