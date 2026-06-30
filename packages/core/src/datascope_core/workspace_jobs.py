from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from datascope_core.workspace_utils import (
    build_artifact_paths,
    job_from_row,
    resolve_patterns,
    safe_output_name,
    source_output_name,
    structured_error,
    utc_now,
)


TERMINAL_JOB_STATUSES = {"cancelled", "succeeded", "failed", "interrupted"}


class JobCancelled(RuntimeError):
    pass


class WorkspaceJobsMixin:
    def enqueue_build_recording(
        self,
        project_id: str,
        source_id: str,
        mapping_id: str | None = None,
        output_name: str | None = None,
        template_id: str = "sensor_monitor",
        output_dir: str | None = None,
    ) -> dict[str, Any]:
        self.get_project(project_id)
        source = self.get_source(source_id)
        self._assert_source_available(source)
        self._ensure_disk(self.estimate_build(project_id, source_id, output_dir=output_dir))
        if mapping_id is not None:
            self.get_mapping(mapping_id)
        return self._create_job(
            project_id,
            "conversion",
            {
                "project_id": project_id,
                "source_id": source_id,
                "mapping_id": mapping_id,
                "output_name": output_name,
                "template_id": template_id,
                "output_dir": output_dir,
            },
            resource_type="source",
            resource_id=source_id,
        )

    def enqueue_batch_import(
        self,
        project_id: str,
        patterns: list[str],
        template_id: str = "sensor_monitor",
        output_prefix: str = "batch_run",
        storage_mode: str = "copy",
    ) -> dict[str, Any]:
        self.get_project(project_id)
        paths = resolve_patterns(patterns)
        if not paths:
            raise ValueError("Batch import did not match any source paths")
        if storage_mode not in {"copy", "reference"}:
            raise ValueError(f"Unsupported storage mode: {storage_mode}")
        self._ensure_disk(self.estimate_batch_import(project_id, patterns, storage_mode=storage_mode))
        return self._create_job(
            project_id,
            "batch_import",
            {
                "project_id": project_id,
                "patterns": [str(path) for path in paths],
                "template_id": template_id,
                "output_prefix": output_prefix,
                "storage_mode": storage_mode,
            },
            resource_type="batch",
        )

    def enqueue_batch_item_retry(
        self,
        project_id: str,
        batch_id: str,
        item_id: str,
    ) -> dict[str, Any]:
        self.get_project(project_id)
        batch = self.get_batch(batch_id)
        if batch["project_id"] != project_id:
            raise ValueError("Batch does not belong to project")
        item = next((row for row in batch["items"] if row["id"] == item_id), None)
        if item is None:
            raise KeyError(f"Batch item not found: {item_id}")
        if item["status"] not in {"failed", "cancelled"}:
            raise ValueError(f"Only failed or cancelled batch items can be retried: {item_id}")
        return self._create_job(
            project_id,
            "batch_item_retry",
            {
                "project_id": project_id,
                "batch_id": batch_id,
                "item_id": item_id,
            },
            resource_type="batch_item",
            resource_id=item_id,
        )

    def _create_job(
        self,
        project_id: str,
        job_type: str,
        payload: dict[str, Any],
        *,
        attempt: int = 1,
        retry_of_job_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        job_id = f"job_{uuid4().hex[:12]}"
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                insert into jobs
                  (id, project_id, type, status, progress, stage, log_path, error_message,
                   payload_json, result_json, error_json, attempt, retry_of_job_id,
                   resource_type, resource_id, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    project_id,
                    job_type,
                    "pending",
                    0.0,
                    "queued",
                    str(Path(project["workspace_path"]) / "logs" / f"{job_id}.log"),
                    None,
                    json.dumps(payload, ensure_ascii=False),
                    None,
                    None,
                    attempt,
                    retry_of_job_id,
                    resource_type,
                    resource_id,
                    now,
                    now,
                ),
            )
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("select * from jobs where id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"Job not found: {job_id}")
        return job_from_row(row)

    def list_jobs(self, project_id: str) -> list[dict[str, Any]]:
        self.get_project(project_id)
        with self._connect() as conn:
            rows = conn.execute(
                "select * from jobs where project_id = ? order by created_at desc",
                (project_id,),
            ).fetchall()
        return [job_from_row(row) for row in rows]

    def pending_jobs(self, limit: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "select * from jobs where status = 'pending' order by created_at limit ?",
                (limit,),
            ).fetchall()
        return [job_from_row(row) for row in rows]

    def active_jobs(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from jobs
                where status in ('running', 'cancel_requested')
                order by created_at
                """
            ).fetchall()
        return [job_from_row(row) for row in rows]

    def claim_job(self, job_id: str, worker_token: str) -> bool:
        now = utc_now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                update jobs
                set status = 'running', stage = 'starting', worker_token = ?,
                    started_at = coalesce(started_at, ?), heartbeat_at = ?, updated_at = ?
                where id = ? and status = 'pending'
                """,
                (worker_token, now, now, now, job_id),
            )
        return cursor.rowcount == 1

    def set_job_worker_pid(self, job_id: str, worker_token: str, pid: int) -> None:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                update jobs set worker_pid = ?, heartbeat_at = ?, updated_at = ?
                where id = ? and worker_token = ?
                """,
                (pid, now, now, job_id, worker_token),
            )

    def heartbeat_job(self, job_id: str, worker_token: str) -> None:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                update jobs set heartbeat_at = ?, updated_at = ?
                where id = ? and worker_token = ? and status in ('running', 'cancel_requested')
                """,
                (now, now, job_id, worker_token),
            )

    def execute_job(self, job_id: str, worker_token: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job["worker_token"] != worker_token:
            raise RuntimeError(f"Worker token does not own job: {job_id}")
        payload = job["payload"]
        project = self.get_project(job["project_id"])
        cache_dir = Path(project["workspace_path"]) / "cache" / "jobs" / job_id
        try:
            if job["type"] == "conversion":
                return self.build_recording(
                    payload["project_id"],
                    payload["source_id"],
                    mapping_id=payload.get("mapping_id"),
                    output_name=payload.get("output_name"),
                    template_id=payload.get("template_id", "sensor_monitor"),
                    output_dir=payload.get("output_dir"),
                    _job_id=job_id,
                    _cache_dir=cache_dir,
                    _background_job=True,
                )
            if job["type"] == "batch_import":
                result = self.batch_import(
                    payload["project_id"],
                    payload["patterns"],
                    template_id=payload.get("template_id", "sensor_monitor"),
                    output_prefix=payload.get("output_prefix", "batch_run"),
                    storage_mode=payload.get("storage_mode", "copy"),
                    _job_id=job_id,
                    _resume_batch_id=payload.get("resume_batch_id"),
                )
                failed = int(result.get("failed") or 0)
                if failed:
                    message = f"Batch import completed with {failed} failed item(s)"
                    self._update_job(
                        job_id,
                        status="failed",
                        progress=1.0,
                        stage="failed",
                        error={
                            "code": "batch_items_failed",
                            "message": message,
                            "batch_id": result["id"],
                            "failed": failed,
                        },
                        error_message=message,
                        finished=True,
                    )
                    return result
                self._update_job(
                    job_id,
                    status="succeeded",
                    progress=1.0,
                    stage="completed",
                    result=result,
                    finished=True,
                )
                return result
            if job["type"] == "batch_item_retry":
                result = self._execute_batch_item_retry(
                    payload["project_id"],
                    payload["batch_id"],
                    payload["item_id"],
                    _job_id=job_id,
                )
                item = next(
                    row for row in result["items"] if row["id"] == payload["item_id"]
                )
                if item["status"] == "failed":
                    message = item.get("error_message") or "Batch item retry failed"
                    self._update_job(
                        job_id,
                        status="failed",
                        progress=1.0,
                        stage="failed",
                        error={
                            "code": "batch_item_failed",
                            "message": message,
                            "batch_id": result["id"],
                            "item_id": item["id"],
                        },
                        error_message=message,
                        finished=True,
                    )
                    return result
                if item["status"] == "cancelled":
                    self._update_job(
                        job_id,
                        status="cancelled",
                        progress=1.0,
                        stage="cancelled",
                        finished=True,
                    )
                    return result
                self._update_job(
                    job_id,
                    status="succeeded",
                    progress=1.0,
                    stage="completed",
                    result=result,
                    finished=True,
                )
                return result
            raise ValueError(f"Unsupported job type: {job['type']}")
        except JobCancelled:
            self._update_job(
                job_id,
                status="cancelled",
                progress=1.0,
                stage="cancelled",
                finished=True,
            )
            raise
        except Exception as exc:
            current = self.get_job(job_id)
            if current["status"] not in TERMINAL_JOB_STATUSES:
                self._update_job(
                    job_id,
                    status="failed",
                    progress=1.0,
                    stage="failed",
                    error=structured_error(exc),
                    error_message=str(exc),
                    finished=True,
                )
            raise
        finally:
            shutil.rmtree(cache_dir, ignore_errors=True)

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job["status"] in TERMINAL_JOB_STATUSES:
            return job
        now = utc_now()
        next_status = "cancelled" if job["status"] == "pending" else "cancel_requested"
        with self._connect() as conn:
            conn.execute(
                """
                update jobs
                set status = ?, stage = ?, cancel_requested_at = ?,
                    finished_at = case when ? = 'cancelled' then ? else finished_at end,
                    updated_at = ?
                where id = ?
                """,
                (next_status, next_status, now, next_status, now, now, job_id),
            )
        if next_status == "cancelled":
            self.cleanup_job_resources(job_id)
        return self.get_job(job_id)

    def retry_job(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job["status"] not in {"failed", "cancelled", "interrupted"}:
            raise ValueError(f"Only terminal unsuccessful jobs can be retried: {job_id}")
        payload = dict(job["payload"])
        if job["type"] == "batch_import" and job.get("resource_id"):
            payload["resume_batch_id"] = job["resource_id"]
        return self._create_job(
            job["project_id"],
            job["type"],
            payload,
            attempt=int(job.get("attempt") or 1) + 1,
            retry_of_job_id=job_id,
            resource_type=job.get("resource_type"),
            resource_id=job.get("resource_id"),
        )

    def _set_job_resource(
        self,
        job_id: str,
        resource_type: str,
        resource_id: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                update jobs
                set resource_type = ?, resource_id = ?, updated_at = ?
                where id = ?
                """,
                (resource_type, resource_id, utc_now(), job_id),
            )

    def interrupt_running_jobs(self, job_ids: list[str] | None = None) -> list[str]:
        with self._connect() as conn:
            if job_ids is None:
                rows = conn.execute(
                    "select id from jobs where status in ('running', 'cancel_requested')"
                ).fetchall()
            elif job_ids:
                placeholders = ",".join("?" for _ in job_ids)
                rows = conn.execute(
                    f"""
                    select id from jobs
                    where id in ({placeholders})
                      and status in ('running', 'cancel_requested')
                    """,
                    job_ids,
                ).fetchall()
            else:
                rows = []
            ids = [row["id"] for row in rows]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                now = utc_now()
                conn.execute(
                    f"""
                    update jobs
                    set status = 'interrupted', stage = 'interrupted',
                        error_json = ?, error_message = ?, finished_at = ?, updated_at = ?,
                        worker_pid = null, worker_token = null
                    where id in ({placeholders})
                    """,
                    (
                        json.dumps(
                            {
                                "code": "worker_interrupted",
                                "message": "The worker was not running when the application started.",
                            }
                        ),
                        "The worker was not running when the application started.",
                        now,
                        now,
                        *ids,
                    ),
                )
        for job_id in ids:
            self.cleanup_job_resources(job_id)
        return ids

    def mark_job_worker_exit(
        self,
        job_id: str,
        *,
        return_code: int,
        cancelled: bool = False,
    ) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job["status"] in TERMINAL_JOB_STATUSES:
            return job
        if cancelled or job["status"] == "cancel_requested":
            self._update_job(
                job_id,
                status="cancelled",
                progress=1.0,
                stage="cancelled",
                finished=True,
            )
        else:
            message = f"Worker process exited unexpectedly with code {return_code}"
            self._update_job(
                job_id,
                status="failed",
                progress=1.0,
                stage="failed",
                error={
                    "code": "worker_exit",
                    "message": message,
                    "return_code": return_code,
                },
                error_message=message,
                finished=True,
            )
        self.cleanup_job_resources(job_id)
        return self.get_job(job_id)

    def cleanup_job_resources(self, job_id: str) -> None:
        job = self.get_job(job_id)
        project = self.get_project(job["project_id"])
        shutil.rmtree(
            Path(project["workspace_path"]) / "cache" / "jobs" / job_id,
            ignore_errors=True,
        )
        if job["type"] != "conversion":
            return
        payload = job["payload"]
        source = self.get_source(payload["source_id"])
        output_base = safe_output_name(
            (payload.get("output_name") or "").strip()
            or source_output_name(source["uri"])
        ) or "run"
        paths = build_artifact_paths(
            project["workspace_path"],
            output_base,
            payload.get("output_dir"),
        )
        with self._connect() as conn:
            committed = conn.execute(
                "select 1 from recordings where project_id = ? and path = ?",
                (job["project_id"], str(paths[0])),
            ).fetchone()
        if committed is None:
            for path in paths:
                path.unlink(missing_ok=True)

    def _check_job_cancelled(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if job["status"] in {"cancel_requested", "cancelled"}:
            raise JobCancelled(f"Job cancellation requested: {job_id}")

    def _update_job(
        self,
        job_id: str,
        *,
        status: str,
        progress: float,
        stage: str | None = None,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        error_message: str | None = None,
        started: bool = False,
        finished: bool = False,
    ) -> None:
        now = utc_now()
        assignments = [
            "status = ?",
            "progress = ?",
            "error_message = ?",
            "heartbeat_at = ?",
            "updated_at = ?",
        ]
        values: list[Any] = [status, progress, error_message, now, now]
        if stage is not None:
            assignments.append("stage = ?")
            values.append(stage)
        if result is not None:
            assignments.append("result_json = ?")
            values.append(json.dumps(result, ensure_ascii=False))
        if error is not None:
            assignments.append("error_json = ?")
            values.append(json.dumps(error, ensure_ascii=False))
        if started:
            assignments.append("started_at = coalesce(started_at, ?)")
            values.append(now)
        if finished:
            assignments.extend(
                ["finished_at = ?", "worker_pid = null", "worker_token = null"]
            )
            values.append(now)
        values.append(job_id)
        with self._connect() as conn:
            conn.execute(
                f"update jobs set {', '.join(assignments)} where id = ?",
                values,
            )
