from __future__ import annotations

import gc
import shutil
import sqlite3
from pathlib import Path
from time import perf_counter

from datascope_core.workspace import Workspace

from benchmarks.benchmark_memory import MemorySampler
from benchmarks.benchmark_models import DatasetConfig
from benchmarks.benchmark_pipeline import storage_stats
from benchmarks.benchmark_query import measure_query, query_calls, result_digest


def benchmark_indexes(workspace: Workspace, primary: dict, config: DatasetConfig,
                      root: Path, memory: MemorySampler, *, runs: int, warmups: int,
                      limit: int, max_samples: int = 10_000) -> dict:
    """Replay the same first/last samples in fresh catalogs with different index sets.

    INSERT SELECT excludes parsing/Python serialization and isolates SQL index maintenance.
    This is not a replacement for the real end-to-end query_index_ms measurement.
    """
    index_definitions = {item["name"]: item["sql"] for item in primary["storage"]["indexes"]}
    names = list(index_definitions)
    variants = {"all": names, "none": [], **{
        f"without_{name}": [other for other in names if other != name] for name in names
    }}
    measured_samples = min(max_samples, config.rows)
    first = measured_samples // 2
    last = measured_samples - first
    bounds = ((first - 1) / config.frequency_hz + 1e-10,
              (config.rows - last) / config.frequency_hz - 1e-10)
    results = {}
    golden: dict[str, str] = {}
    for variant, active in variants.items():
        scratch_root = root / variant
        print(f"  index experiment {variant} ({measured_samples} source samples)", flush=True)
        with memory.stage(f"indexes/{variant}"):
            scratch = Workspace(scratch_root)
            conn = scratch._connect()
            try:
                # A checkpointed source stays untouched. Paths are bound, not SQL interpolated.
                conn.execute("attach database ? as baseline", (str(workspace.db_path),))
                with conn:
                    for table in ("projects", "sources", "recordings"):
                        conn.execute(f"insert into {table} select * from baseline.{table}")
                    for name in names:
                        if name not in active:
                            conn.execute(f'drop index "{name}"')
                started = perf_counter()
                with conn:
                    conn.execute(
                        """insert into query_rows select * from baseline.query_rows
                        where recording_id = ? and (time <= ? or time >= ?)""",
                        (primary["recording"]["recording_id"], *bounds),
                    )
                insert_ms = (perf_counter() - started) * 1000
                conn.execute("detach database baseline")
            finally:
                conn.close()
            storage = storage_stats(scratch, primary["recording"]["recording_id"],
                                    primary["storage"]["query_rows"], measured_samples)
            if storage["query_rows"] != measured_samples * config.fields_per_sample:
                raise AssertionError("Index experiment did not replay the expected samples")
        calls = query_calls(scratch, primary["project_id"],
                            [primary["recording"]["recording_id"]], config, limit)
        # Compare requires a second indexed recording; measured in the production pipeline instead.
        calls.pop("compare")
        queries = {}
        plans = {}
        for name, call in calls.items():
            expected = result_digest(call())
            if variant == "all":
                golden[name] = expected
            elif expected != golden[name]:
                raise AssertionError(f"Index set changed query output: {variant}/{name}")
            def validate(result: dict, name: str = name) -> None:
                if result_digest(result) != golden[name]:
                    raise AssertionError(f"Incorrect replay result: {variant}/{name}")
            queries[name] = measure_query(call, validate, runs=runs, warmups=warmups,
                                          memory=memory, name=f"indexes/{variant}/{name}")
            plans[name] = explain_query(scratch, primary["project_id"],
                                       primary["recording"]["recording_id"], name)
        item = {"active_indexes": active, "insert_ms": insert_ms,
                "sqlite_size_mb": storage["sqlite_size_mb"],
                "object_size_bytes": storage["object_size_bytes"],
                "queries": queries, "query_plans": plans}
        if variant == "none":
            builds = {}
            conn = scratch._connect()
            try:
                for name, sql in index_definitions.items():
                    started = perf_counter()
                    with conn:
                        conn.execute(sql)
                    builds[name] = (perf_counter() - started) * 1000
            finally:
                conn.close()
            item["deferred_index_build_ms"] = builds
            item["insert_plus_deferred_build_ms"] = insert_ms + sum(builds.values())
        results[variant] = item
        del scratch, calls
        gc.collect()
        # Delete only this benchmark-owned scratch directory.
        if scratch_root.resolve().parent != root.resolve():
            raise RuntimeError("Scratch cleanup escaped the benchmark directory")
        shutil.rmtree(scratch_root)
    return {"source_samples": measured_samples,
            "query_rows": measured_samples * config.fields_per_sample,
            "sample_selection": "first half + last half; complete samples from the primary index",
            "method": "one committed INSERT SELECT in each fresh catalog, fixed variant order",
            "limitations": "warm source pages; bounded sample; one insert trial per variant; no parsing",
            "variants": results}


def explain_query(workspace: Workspace, project_id: str, recording_id: str, name: str) -> list[str]:
    conditions, values = workspace._query_conditions(
        project_id, template_id=None if name.startswith("custom_") else name,
        recording_ids=[recording_id],
        semantic_types=["scalar", "scalar_group"] if name in {
            "custom_scalar_key", "custom_numeric_threshold"} else None,
    )
    conn = workspace._connect()
    try:
        return [row[3] for row in conn.execute(
            "explain query plan select qr.* from query_rows qr "
            "join recordings r on r.id = qr.recording_id "
            f"where {' and '.join(conditions)} "
            "order by qr.recording_id, qr.time, qr.entity_path, qr.key", values)]
    finally:
        conn.close()
