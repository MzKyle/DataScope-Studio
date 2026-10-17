from __future__ import annotations

import gc
import sqlite3
from pathlib import Path
from time import perf_counter
from typing import Any, Callable
from unittest.mock import patch

import datascope_core.workspace as workspace_module
import datascope_core.workspace_query as query_module
from datascope_core.workspace import Workspace

from benchmarks.benchmark_memory import MemorySampler
from benchmarks.benchmark_models import DatasetConfig


def timed_call(timings: dict, key: str, function: Callable, *args: Any, **kwargs: Any) -> Any:
    started = perf_counter()
    try:
        return function(*args, **kwargs)
    finally:
        timings[key] = timings.get(key, 0.0) + (perf_counter() - started) * 1000


class TimedAdapter:
    def __init__(self, adapter: Any, timings: dict) -> None:
        self.adapter, self.timings = adapter, timings

    def __getattr__(self, name: str) -> Any:
        return getattr(self.adapter, name)

    def convert(self, *args: Any, **kwargs: Any) -> Any:
        result = timed_call(self.timings, "rerun_convert_ms", self.adapter.convert, *args, **kwargs)
        print(f"    Rerun conversion: {self.timings['rerun_convert_ms'] / 1000:.2f} s", flush=True)
        return result


class BenchmarkWorkspace(Workspace):
    """Instrumentation confined to an opt-in benchmark process."""

    def __init__(self, root: Path) -> None:
        self.timings: dict[str, float] = {}
        super().__init__(root)

    def _adapter_for_path(self, *args: Any, **kwargs: Any) -> Any:
        return TimedAdapter(super()._adapter_for_path(*args, **kwargs), self.timings)

    def _index_recording(self, *args: Any, **kwargs: Any) -> None:
        print("    Query Index build", flush=True)
        insert = query_module._insert_query_rows
        # A Mock with side_effect records all batch arguments and inflates index RSS.
        # Replace the callable directly so completed batches can be released normally.
        with patch.object(query_module, "_insert_query_rows", new=lambda *a, **kw:
                          timed_call(self.timings, "query_insert_ms", insert, *a, **kw)):
            timed_call(self.timings, "query_index_ms", super()._index_recording, *args, **kwargs)
        print(f"    Query Index: {self.timings['query_index_ms'] / 1000:.2f} s", flush=True)


def run_pipeline(
    workspace: BenchmarkWorkspace, config: DatasetConfig, dataset: Path,
    memory: MemorySampler, *, mode: str = "full", label: str = "primary",
    project_id: str | None = None,
) -> dict:
    workspace.timings = {}
    timings = workspace.timings
    project = workspace.get_project(project_id) if project_id else workspace.create_project("Benchmark")
    project_id = project["id"]
    with memory.stage(f"{label}/import"):
        source = timed_call(timings, "import_ms", workspace.add_source, project_id, str(dataset),
                            import_options={"csv": {"header_mode": "header"}})
    profile_builder = workspace_module.build_schema_profile
    with memory.stage(f"{label}/inspect"), patch.object(
        workspace_module, "build_schema_profile", new=lambda *a, **kw:
        timed_call(timings, "schema_profile_ms", profile_builder, *a, **kw),
    ):
        inspection = timed_call(timings, "inspect_total_ms", workspace.inspect_source, source["id"])
    timings["inspect_ms"] = timings["inspect_total_ms"] - timings["schema_profile_ms"]
    if inspection["source"]["metadata"]["rows"] != config.rows:
        raise AssertionError("CSV inspect row count disagrees with generated dataset")
    with memory.stage(f"{label}/mapping"):
        spec = timed_call(timings, "mapping_suggest_ms", workspace.suggest_mapping, source["id"],
                          template_id="sensor_monitor")
        # Explicit seconds avoid auto-inference turning long relative recordings into Unix ms.
        spec.timeline_unit = "relative_s"
        spec.effective_timeline_unit = "relative_s"
        validation = timed_call(timings, "mapping_validate_ms", workspace.validate_mapping_spec,
                                source["id"], spec)
        if not validation["valid"]:
            raise AssertionError(f"Invalid benchmark mapping: {validation['issues']}")
        mapped = [field for stream in spec.streams if stream.get("enabled", True)
                  for field in stream["source_fields"]]
        if len(mapped) != config.fields_per_sample or len(set(mapped)) != len(mapped):
            raise AssertionError("Mapping must cover every non-timestamp field exactly once")
        mapping = timed_call(timings, "mapping_save_ms", workspace.save_mapping,
                             project_id, source["id"], spec, confirmed=True)
    with memory.stage(f"{label}/recording_build"):
        if mode == "full":
            blueprint = workspace_module.save_blueprint
            cleanup = workspace_module.cleanup_recording_streams
            with patch.object(workspace_module, "save_blueprint", new=lambda *a, **kw:
                              timed_call(timings, "blueprint_ms", blueprint, *a, **kw)), patch.object(
                workspace_module, "cleanup_recording_streams", new=lambda *a, **kw:
                timed_call(timings, "rerun_cleanup_ms", cleanup, *a, **kw),
            ):
                recording = timed_call(timings, "recording_build_ms", workspace.build_recording,
                                       project_id, source["id"], mapping_id=mapping["id"],
                                       output_name=label)
            if recording["status"] != "succeeded":
                raise AssertionError("Recording build did not succeed")
            for name in ("recording_path", "blueprint_path"):
                if not Path(recording[name]).is_file() or Path(recording[name]).stat().st_size <= 0:
                    raise AssertionError(f"Missing or empty artifact: {name}")
            timings["rerun_artifact_ms"] = sum(timings.get(name, 0.0) for name in (
                "rerun_convert_ms", "rerun_cleanup_ms", "blueprint_ms"))
            timings["recording_other_ms"] = (timings["recording_build_ms"]
                                            - timings["rerun_artifact_ms"]
                                            - timings["query_index_ms"])
        else:
            # Explicit catalog fixture for an index-only workload; never claim an RRD build.
            recording_id = spec.recording_id
            with workspace._connect() as conn:
                conn.execute(
                    """insert into recordings
                    (id, project_id, source_id, app_id, path, run_name, created_at)
                    values (?, ?, ?, ?, '', ?, 'benchmark-index-only')""",
                    (recording_id, project_id, source["id"], spec.app_id, label),
                )
            workspace._index_recording(recording_id, workspace.get_source(source["id"]), spec)
            recording = {"recording_id": recording_id, "status": "index_only",
                         "recording_path": None, "blueprint_path": None}
            for key in ("recording_build_ms", "rerun_artifact_ms", "recording_other_ms"):
                timings[key] = None
    recording_id = recording["recording_id"]
    storage = storage_stats(workspace, recording_id, dataset.stat().st_size, config.rows)
    if storage["query_rows"] != config.rows * config.fields_per_sample:
        raise AssertionError(f"Incorrect Query Index cardinality: {storage['query_rows']}")
    storage["rrd_size_mb"] = (
        Path(recording["recording_path"]).stat().st_size / 1_000_000
        if recording["recording_path"] else None)
    storage["rbl_size_mb"] = (
        Path(recording["blueprint_path"]).stat().st_size / 1_000_000
        if recording["blueprint_path"] else None)
    return {"project_id": project_id, "source_id": source["id"], "recording": recording,
            "mapping_path": mapping["path"], "pipeline": dict(timings), "storage": storage,
            "source_checksum": source["checksum"], "mode": mode}


def storage_stats(workspace: Workspace, recording_id: str, source_bytes: int, rows: int) -> dict:
    # Checkpoint WAL explicitly; measuring only the main file before checkpoint undercounts storage.
    gc.collect()
    conn = workspace._connect()
    try:
        checkpoint = list(conn.execute("pragma wal_checkpoint(truncate)").fetchone())
        if checkpoint[0] != 0:
            raise RuntimeError(f"WAL checkpoint was busy: {checkpoint}")
        count = conn.execute("select count(*) from query_rows where recording_id = ?",
                             (recording_id,)).fetchone()[0]
        total = conn.execute("select count(*) from query_rows").fetchone()[0]
        pragmas = {name: conn.execute(f"pragma {name}").fetchone()[0] for name in (
            "journal_mode", "synchronous", "page_size", "cache_size", "temp_store", "user_version")}
        indexes = [dict(row) for row in conn.execute(
            "select name, sql from sqlite_master where type = 'index' and tbl_name = 'query_rows'")]
        try:
            sizes = {row[0]: row[1] for row in conn.execute(
                "select name, sum(pgsize) from dbstat group by name")}
        except sqlite3.OperationalError:
            sizes = None
    finally:
        conn.close()
    database_bytes = workspace.db_path.stat().st_size
    wal_bytes = sum(Path(str(workspace.db_path) + suffix).stat().st_size
                    for suffix in ("-wal", "-shm") if Path(str(workspace.db_path) + suffix).exists())
    return {
        "query_rows": count, "total_query_rows": total,
        "row_amplification_ratio": count / rows,
        "sqlite_size_bytes": database_bytes, "sqlite_size_mb": database_bytes / 1_000_000,
        "sqlite_sidecars_size_mb": wal_bytes / 1_000_000,
        "storage_amplification_ratio": database_bytes / source_bytes,
        "checkpoint": checkpoint, "sqlite_pragmas": pragmas, "indexes": indexes,
        "object_size_bytes": sizes,
        "size_scope": "checkpointed whole catalog, including metadata and all three indexes",
    }
