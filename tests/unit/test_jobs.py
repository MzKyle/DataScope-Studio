from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from datascope_core.job_supervisor import JobSupervisor, _terminate_process_tree
from datascope_core.workspace import Workspace


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
TERMINAL = {"cancelled", "succeeded", "failed", "interrupted"}


def test_supervisor_executes_enqueued_conversion(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Jobs")
    source = workspace.add_source(project["id"], str(FIXTURES / "sample_sensor.csv"))
    workspace.inspect_source(source["id"])
    job = workspace.enqueue_build_recording(project["id"], source["id"])
    supervisor = JobSupervisor(workspace, poll_interval=0.02)
    supervisor.start()
    try:
        completed = _wait_for_job(workspace, job["id"])
    finally:
        supervisor.stop()

    assert completed["status"] == "succeeded"
    assert completed["result"]["recording_id"]
    assert completed["started_at"]
    assert completed["finished_at"]


def test_pending_job_cancel_and_retry_keep_audit_history(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Cancel")
    source = workspace.add_source(project["id"], str(FIXTURES / "sample_sensor.csv"))
    workspace.inspect_source(source["id"])
    original = workspace.enqueue_build_recording(project["id"], source["id"])

    cancelled = workspace.cancel_job(original["id"])
    retried = workspace.retry_job(original["id"])

    assert cancelled["status"] == "cancelled"
    assert retried["status"] == "pending"
    assert retried["attempt"] == 2
    assert retried["retry_of_job_id"] == original["id"]
    assert workspace.get_job(original["id"])["status"] == "cancelled"


def test_startup_marks_orphaned_running_job_interrupted(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Recovery")
    source = workspace.add_source(project["id"], str(FIXTURES / "sample_sensor.csv"))
    job = workspace.enqueue_build_recording(project["id"], source["id"])
    assert workspace.claim_job(job["id"], "orphan")

    workspace.interrupt_running_jobs()
    recovered = workspace.get_job(job["id"])

    assert recovered["status"] == "interrupted"
    assert recovered["result"] is None
    assert recovered["error"]["code"] == "worker_interrupted"


def test_supervisor_preserves_worker_with_fresh_heartbeat(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Recovery")
    source = workspace.add_source(project["id"], str(FIXTURES / "sample_sensor.csv"))
    job = workspace.enqueue_build_recording(project["id"], source["id"])
    assert workspace.claim_job(job["id"], "active")
    workspace.set_job_worker_pid(job["id"], "active", os.getpid())

    supervisor = JobSupervisor(workspace, poll_interval=0.02)
    supervisor.start()
    try:
        time.sleep(0.1)
        assert workspace.get_job(job["id"])["status"] == "running"
    finally:
        supervisor.stop()
        workspace.interrupt_running_jobs([job["id"]])


def test_batch_retry_preserves_successful_items(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Batch retry")
    good_path = tmp_path / "good.csv"
    bad_path = tmp_path / "recoverable.jsonl"
    good_path.write_text((FIXTURES / "sample_sensor.csv").read_text())
    bad_path.write_text('{"timestamp": 1, "value": 2}\nnot-json\n')

    original = workspace.enqueue_batch_import(
        project["id"],
        [str(good_path), str(bad_path)],
    )
    supervisor = JobSupervisor(workspace, poll_interval=0.02)
    supervisor.start()
    try:
        failed = _wait_for_job(workspace, original["id"])
        assert failed["status"] == "failed"
        assert failed["result"] is None
        assert failed["error"]["code"] == "batch_items_failed"
        assert failed["resource_id"]

        first_batch = workspace.get_batch(failed["resource_id"])
        succeeded_item = next(
            item for item in first_batch["items"] if item["status"] == "succeeded"
        )
        failed_item = next(
            item for item in first_batch["items"] if item["status"] == "failed"
        )
        original_recording_id = succeeded_item["recording_id"]
        assert failed_item["attempt"] == 1
        assert len(workspace.list_sources(project["id"])) == 1

        bad_path.write_text('{"timestamp": 1, "value": 2}\n')
        retried = workspace.retry_job(original["id"])
        completed = _wait_for_job(workspace, retried["id"])
    finally:
        supervisor.stop()

    assert completed["status"] == "succeeded"
    assert completed["result"]["id"] == first_batch["id"]
    items = completed["result"]["items"]
    assert len(items) == 2
    assert all(item["status"] == "succeeded" for item in items)
    assert next(item for item in items if item["id"] == succeeded_item["id"])[
        "recording_id"
    ] == original_recording_id
    assert next(item for item in items if item["id"] == failed_item["id"])[
        "attempt"
    ] == 2
    assert len(workspace.list_sources(project["id"])) == 2
    assert len(workspace.list_recordings(project["id"])) == 2


def test_batch_item_cancel_and_single_item_retry(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Batch item controls")

    now = "2026-06-29T00:00:00Z"
    with workspace._connect() as conn:
        conn.execute(
            """
            insert into batch_jobs
              (id, project_id, job_id, status, template_id, output_prefix,
               storage_mode, patterns_json, total, succeeded, failed,
               cancelled, created_at, updated_at)
            values ('batch_pending', ?, null, 'running', 'sensor_monitor',
                    'pending_batch', 'copy', '[]', 1, 0, 0, 0, ?, ?)
            """,
            (project["id"], now, now),
        )
        conn.execute(
            """
            insert into batch_items
              (id, batch_id, source_path, source_id, recording_id, status,
               error_message, attempt, created_at, updated_at)
            values ('item_pending', 'batch_pending', '/tmp/pending.csv', null,
                    null, 'pending', null, 1, ?, ?)
            """,
            (now, now),
        )

    cancelled = workspace.cancel_batch_item("batch_pending", "item_pending")
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancelled"] == 1
    assert cancelled["items"][0]["status"] == "cancelled"
    assert cancelled["items"][0]["cancel_requested_at"]

    good_path = tmp_path / "good.csv"
    bad_path = tmp_path / "recoverable.jsonl"
    good_path.write_text((FIXTURES / "sample_sensor.csv").read_text())
    bad_path.write_text('{"timestamp": 1, "value": 2}\nnot-json\n')
    original = workspace.enqueue_batch_import(project["id"], [str(good_path), str(bad_path)])

    supervisor = JobSupervisor(workspace, poll_interval=0.02)
    supervisor.start()
    try:
        failed_job = _wait_for_job(workspace, original["id"])
        assert failed_job["status"] == "failed"
        batch = workspace.get_batch(failed_job["resource_id"])
        failed_item = next(item for item in batch["items"] if item["status"] == "failed")

        bad_path.write_text('{"timestamp": 1, "value": 2}\n')
        retry_job = workspace.retry_batch_item(batch["id"], failed_item["id"])
        completed_retry = _wait_for_job(workspace, retry_job["id"])
    finally:
        supervisor.stop()

    assert completed_retry["status"] == "succeeded"
    retried_batch = workspace.get_batch(batch["id"])
    retried_item = next(item for item in retried_batch["items"] if item["id"] == failed_item["id"])
    assert retried_batch["status"] == "succeeded"
    assert retried_batch["succeeded"] == 2
    assert retried_item["status"] == "succeeded"
    assert retried_item["attempt"] == 2


@pytest.mark.skipif(os.name == "nt", reason="POSIX process group behavior")
def test_terminate_process_tree_kills_sigterm_ignoring_child(tmp_path: Path) -> None:
    ready_path = tmp_path / "child-ready"
    survived_path = tmp_path / "child-survived"
    child_code = (
        "import pathlib, signal, time;"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
        f"pathlib.Path({str(ready_path)!r}).write_text('ready');"
        "time.sleep(1);"
        f"pathlib.Path({str(survived_path)!r}).write_text('survived');"
        "time.sleep(60)"
    )
    parent_code = (
        "import subprocess, sys, time;"
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}]);"
        "time.sleep(60)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", parent_code],
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not ready_path.exists():
            time.sleep(0.02)
        assert ready_path.exists()

        _terminate_process_tree(process)
        time.sleep(1.1)
        assert process.poll() is not None
        assert not survived_path.exists()
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)


def _wait_for_job(workspace: Workspace, job_id: str, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = workspace.get_job(job_id)
        if job["status"] in TERMINAL:
            return job
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} did not finish")
