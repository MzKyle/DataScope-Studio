"""C2b production storage comparison. No Rerun conversion or DuckDB dependency.

Smoke/Small reuse immutable old catalogs for the C2a EAV control. Medium reuses
the Phase C CSVs and published EAV storage evidence; it does not replay EAV load.
"""
from __future__ import annotations

import argparse
import gc
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(REPO))

from datascope_core.mapping import load_mapping_yaml
from datascope_core.models import MappingSpec
from datascope_core.query_sql import CustomQueryPlan, register_custom_query_functions
from datascope_core.query_typed import sample_table
from datascope_core.workspace import Workspace
import datascope_core.query as query_module
from benchmarks.benchmark_memory import MemorySampler
from benchmarks.benchmark_models import DatasetConfig, PRESETS
from benchmarks.benchmark_query import measure_query, query_calls, validate_query
from benchmarks.benchmark_report import environment
from benchmarks.custom_query_pushdown import ReadOnlyWorkspace, describe_input, sha256, write_json
from benchmarks.generate_dataset import generate_dataset

NAMES = ("find_errors", "low_battery", "state_duration", "custom_scalar_key",
         "custom_time_range", "custom_numeric_threshold", "compare")


class NoSampleIndexes(sqlite3.Connection):
    def execute(self, sql, parameters=()):
        # Benchmark-only ablation: production's entire writer still runs. Only
        # the two sample CREATE INDEX statements are suppressed; ANALYZE runs.
        if sql.startswith("CREATE INDEX typed_samples_"):
            return super().execute("SELECT 1")
        return super().execute(sql, parameters)


class MeasuredWorkspace(Workspace):
    traces = None
    no_sample_indexes = False

    def _connect(self):
        if self.no_sample_indexes:
            conn = sqlite3.connect(self.db_path, timeout=5, factory=NoSampleIndexes)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 5000")
        else:
            conn = super()._connect()
        if self.traces is not None:
            conn.set_trace_callback(self.traces.append)
        return conn


def copy_metadata(workspace, manifest):
    with workspace._connect() as conn:
        for table in ("projects", "sources", "recordings"):
            for row in manifest["metadata"][table]:
                columns = ",".join('"' + key.replace('"', '""') + '"' for key in row)
                conn.execute(f"INSERT INTO {table} ({columns}) VALUES ("
                             + ",".join("?" for _ in row) + ")", list(row.values()))


def storage(workspace):
    conn = workspace._connect()
    try:
        checkpoint = list(conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone())
        if checkpoint[0]:
            raise RuntimeError(f"Busy benchmark checkpoint: {checkpoint}")
        try:
            objects = {row[0]: row[1] for row in conn.execute("SELECT name,sum(pgsize) FROM dbstat GROUP BY name")}
        except sqlite3.OperationalError:
            objects = None  # Standard Windows Python builds may omit SQLITE_ENABLE_DBSTAT_VTAB.
        indexes = [dict(row) for row in conn.execute("SELECT name,sql FROM sqlite_master "
                   "WHERE type='index' AND tbl_name LIKE 'typed_samples_%'")]
        stats = [json.loads(row[0]) for row in conn.execute("SELECT stats_json FROM typed_indexes")]
        eav = conn.execute("SELECT count(*) FROM query_rows").fetchone()[0]
        physical = logical = 0
        for dataset in conn.execute("SELECT id,schema_id FROM typed_datasets").fetchall():
            bindings = conn.execute("SELECT column_no,count(*) FROM typed_bindings "
                                    "WHERE dataset_id = ? GROUP BY column_no", (dataset[0],)).fetchall()
            counts = conn.execute("SELECT count(*)" + "".join(f",count(c{row[0]})" for row in bindings)
                                  + f" FROM {sample_table(dataset[1])} WHERE dataset_id = ?", (dataset[0],)).fetchone()
            physical += counts[0]
            logical += sum(counts[i + 1] * binding[1] for i, binding in enumerate(bindings))
    finally:
        conn.close()
    return {"database_bytes": workspace.db_path.stat().st_size, "objects": objects,
            "sample_indexes": indexes, "builds": stats, "eav_rows": eav,
            "physical_sample_rows": physical, "typed_logical_rows": logical,
            "writer_counts_match_sql": physical == sum(row["physical_sample_rows"] for row in stats)
                and logical == sum(row["typed_logical_rows"] for row in stats),
            "scope": "checkpointed whole catalog; includes metadata, registry, dictionaries and all indexes; excludes CSV/RRD/RBL"}


def count_and_explain(workspace, call):
    workspace._query_read_stats = {}
    workspace.traces = []
    decoded = 0
    original = query_module._db_value

    def decode(row):
        nonlocal decoded
        decoded += 1
        return original(row)

    with patch.object(query_module, "_db_value", new=decode):
        call()
    sql = list(dict.fromkeys(statement for statement in workspace.traces
                            if statement.lstrip().upper().startswith("SELECT")))
    workspace.traces = None
    counts = {**workspace._query_read_stats, "json_decodes": decoded}
    del workspace._query_read_stats
    plans = []
    candidates = {}
    conn = workspace._connect()
    try:
        register_custom_query_functions(conn, CustomQueryPlan(needs_unicode_lower=True))
        for statement in sql:
            plans.append({"sql": statement, "explain": [list(row) for row in conn.execute(
                "EXPLAIN QUERY PLAN " + statement)]})
            match = re.search(r"FROM (typed_samples_[0-9a-f]+) s", statement)
            dataset = re.search(r"s.dataset_id = (\d+)", statement)
            if match and dataset:
                bounds = re.findall(r"s.time (>=|<=) ([-+\deE.]+)", statement)
                key = (match[1], dataset[1], tuple(bounds))
                if key not in candidates:
                    where = "dataset_id = ?" + "".join(f" AND time {op} ?" for op, _ in bounds)
                    candidates[key] = conn.execute(f"SELECT count(*) FROM {match[1]} WHERE {where}",
                        [int(dataset[1]), *[float(value) for _, value in bounds]]).fetchone()[0]
    finally:
        conn.close()
    counts["distinct_time_candidate_samples"] = sum(candidates.values())
    counts["scope"] = ("untimed pass: cursor projection rows can repeat a physical sample across bindings; "
                       "distinct_time_candidate_samples counts dataset/time candidates, not SQLite pages or rows examined")
    return {"counts": counts, "statements": plans}


def worker(args):
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    config = DatasetConfig(**manifest["config"])
    memory = MemorySampler()
    result = {"backend": args.worker, "status": "running", "queries": {}, "environment": environment(REPO)}
    started = time.perf_counter()
    with memory:
        if args.worker == "eav" and manifest.get("control"):
            workspace = ReadOnlyWorkspace(manifest["control"]["workspace"])
            result["storage"] = {"database_bytes": manifest["control"]["database_bytes"],
                                  "scope": "unchanged historical whole production EAV catalog"}
        else:
            workspace = MeasuredWorkspace(Path(manifest["work"]) / args.worker)
            workspace.no_sample_indexes = args.worker == "typed_none"
            copy_metadata(workspace, manifest)
            last_progress = time.monotonic()

            def progress():
                nonlocal last_progress
                now = time.monotonic()
                if now - last_progress >= 15:
                    print(f"  {args.worker}: index build still running ({now - started:.0f}s)", flush=True)
                    last_progress = now

            with memory.stage("production_index_build"):
                for recording in manifest["records"]:
                    spec = MappingSpec(**recording["spec"])
                    workspace._index_recording(recording["recording_id"],
                        workspace.get_source(recording["source_id"]), spec,
                        query_storage="legacy" if args.worker == "eav" else "typed_sqlite",
                        cancel_check=progress)
            result["prepare_ms"] = (time.perf_counter() - started) * 1000
            result["storage"] = storage(workspace)
        if manifest["measure_queries"]:
            ids = [recording["recording_id"] for recording in manifest["records"]]
            calls = query_calls(workspace, manifest["project_id"], ids, config, manifest["limit"])
            for name in NAMES:
                result["queries"][name] = measure_query(calls[name],
                    lambda value, name=name: validate_query(value, name, config, manifest["limit"], ids,
                                                            manifest["records"][1]["rows"]),
                    runs=manifest["runs"], warmups=manifest["warmups"], memory=memory,
                    name=f"{args.worker}/{name}")
                result["queries"][name]["execution"] = count_and_explain(workspace, calls[name])
        conn = workspace._connect()
        try:
            result["connection_policy"] = {name: conn.execute("PRAGMA " + name).fetchone()[0]
                for name in ("journal_mode", "synchronous", "cache_size", "temp_store", "user_version", "busy_timeout")}
        finally:
            conn.close()
    result["memory"] = memory.report()
    result["status"] = "succeeded"
    write_json(args.worker_output, result)


def retained_inputs(preset, control_path):
    archived = json.loads(control_path.read_text(encoding="utf-8"))
    control = describe_input(Path(archived["input"]["baseline"]))
    expected = DatasetConfig(rows=PRESETS[preset])
    if any(control["dataset"][name] != value for name, value in asdict(expected).items()):
        raise ValueError("Retained control dataset does not match the selected standard preset")
    old = ReadOnlyWorkspace(control["workspace"])
    conn = old._connect()
    try:
        recordings = [dict(row) for row in conn.execute(
            "SELECT * FROM recordings WHERE project_id = ? AND run_name IN ('primary','peer') "
            "ORDER BY CASE run_name WHEN 'primary' THEN 0 ELSE 1 END", (control["project_id"],))]
        sources = [dict(conn.execute("SELECT * FROM sources WHERE id = ?", (row["source_id"],)).fetchone())
                   for row in recordings]
        project = dict(conn.execute("SELECT * FROM projects WHERE id = ?", (control["project_id"],)).fetchone())
        records = []
        for i, recording in enumerate(recordings):
            mapping = conn.execute("SELECT path FROM mappings WHERE source_id = ? ORDER BY updated_at DESC LIMIT 1",
                                    (recording["source_id"],)).fetchone()
            spec = load_mapping_yaml(mapping[0])
            records.append({"recording_id": recording["id"], "source_id": recording["source_id"],
                            "spec": asdict(spec), "rows": PRESETS[preset] if i == 0 else 1000})
    finally:
        conn.close()
    return {"control": control, "project_id": project["id"], "records": records,
            "metadata": {"projects": [project], "sources": sources, "recordings": recordings}}


def fresh_inputs(work, config, phase_c=None):
    setup = Workspace(work / "setup")
    project = setup.create_project("Typed storage benchmark")
    records = []
    source_rows, recording_rows = [], []
    for i, rows in enumerate((config.rows, min(1000, config.rows))):
        if phase_c:
            input_record = phase_c["recordings"][i]
            path = Path(input_record["csv_path"])
            if sha256(path) != input_record["checksum"]:
                raise ValueError("Retained Phase C CSV checksum changed")
        else:
            path = work / f"input_{i}.csv"
            generate_dataset(DatasetConfig(rows=rows, frequency_hz=config.frequency_hz,
                scalar_fields=config.scalar_fields, state_fields=config.state_fields, seed=config.seed), path)
        source = setup.add_source(project["id"], str(path), storage_mode="reference")
        setup.inspect_source(source["id"])
        spec = setup.suggest_mapping(source["id"])
        spec.timeline_unit = spec.effective_timeline_unit = "relative_s"
        recording_id = f"recording_{i}"
        with setup._connect() as conn:
            conn.execute("""INSERT INTO recordings
                (id,project_id,source_id,app_id,path,run_name,created_at)
                VALUES (?,?,?,'benchmark','','benchmark','index-only')""",
                (recording_id, project["id"], source["id"]))
            source_rows.append(dict(conn.execute("SELECT * FROM sources WHERE id = ?", (source["id"],)).fetchone()))
            recording_rows.append(dict(conn.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,)).fetchone()))
        records.append({"recording_id": recording_id, "source_id": source["id"], "spec": asdict(spec), "rows": rows})
    with setup._connect() as conn:
        project_row = dict(conn.execute("SELECT * FROM projects WHERE id = ?", (project["id"],)).fetchone())
    return {"project_id": project["id"], "records": records,
            "metadata": {"projects": [project_row], "sources": source_rows, "recordings": recording_rows}}


def run(args):
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    work = args.output_dir.resolve() / ".work" / ("typed_storage_" + run_id)
    work.mkdir(parents=True, exist_ok=False)
    owner = work / "owner.json"
    write_json(owner, {"run_id": run_id})
    output = args.output_dir / ("typed_storage_" + run_id + ".json")
    report = {"format_version": 1, "run_id": run_id,
              "started_at": datetime.now(timezone.utc).isoformat(),
              "preset": args.preset, "status": "running", "mode": "production-index-only",
              "environment": environment(REPO), "backends": {}, "work": str(work)}
    try:
        config = DatasetConfig(rows=args.rows or PRESETS[args.preset])
        phase_c = None
        if args.preset == "medium" and args.rows is None:
            phase_c = json.loads(args.phase_c_input.read_text(encoding="utf-8"))
            inputs = fresh_inputs(work, config, phase_c)
            report["historical_eav_storage"] = {"report": str(args.phase_c_input.resolve()),
                "sha256": sha256(args.phase_c_input), "bytes": phase_c["backends"]["legacy_sqlite_eav"]["preparation"]["storage_bytes"],
                "scope": "historical same-input EAV physical layout; no same-round Medium EAV timing"}
        elif args.rows is not None:
            inputs = fresh_inputs(work, config)
        else:
            control_path = args.control or (REPO / "benchmarks/results/baselines/2026-10-17-phase-c2a" / (args.preset + ".json"))
            inputs = retained_inputs(args.preset, control_path)
        source_info = [{"path": row["uri"], "bytes": Path(row["uri"]).stat().st_size,
                        "sha256": sha256(Path(row["uri"]))} for row in inputs["metadata"]["sources"]]
        manifest = {**inputs, "work": str(work), "config": asdict(config), "limit": 1000,
                    "runs": args.query_runs, "warmups": args.warmups,
                    "measure_queries": args.preset != "medium" or args.rows is not None}
        manifest_path = work / "manifest.json"
        write_json(manifest_path, manifest)
        report["input"] = {"sources": source_info, "config": asdict(config),
                           "records": inputs["records"],
                           "logical_samples": sum(row["rows"] for row in inputs["records"]),
                           "control": inputs.get("control")}
        report["settings"] = {"runs": args.query_runs, "warmups": args.warmups, "limit": 1000,
            "timing_scope": "public production query; validation, SQL tracing and counting excluded",
            "none_ablation": "same production writer; suppress only sample CREATE INDEX in owned scratch catalog",
            "production_files_sha256": {name: sha256(REPO / "packages/core/src/datascope_core" / name)
                for name in ("query.py", "query_sql.py", "query_typed.py", "workspace_query.py", "workspace_database.py")}}
        backends = ("typed_time",) if not manifest["measure_queries"] else ("eav", "typed_time", "typed_none")
        for backend in backends:
            worker_output = work / (backend + ".json")
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", backend,
                            "--manifest", str(manifest_path), "--worker-output", str(worker_output)], check=True)
            report["backends"][backend] = json.loads(worker_output.read_text(encoding="utf-8"))
            write_json(output, report)
        if manifest["measure_queries"]:
            for name in NAMES:
                digests = {backend["queries"][name]["result_sha256"] for backend in report["backends"].values()}
                if len(digests) != 1:
                    raise AssertionError(f"Production result mismatch: {name}")
        source_bytes = sum(row["bytes"] for row in source_info)
        typed_storage = report["backends"]["typed_time"]["storage"]
        eav_bytes = (report["backends"]["eav"]["storage"]["database_bytes"] if "eav" in report["backends"]
                     else report["historical_eav_storage"]["bytes"])
        amplification = typed_storage["database_bytes"] / source_bytes
        reduction = 1 - typed_storage["database_bytes"] / eav_bytes
        gates = {"typed_rows_at_most_two_per_sample": typed_storage["physical_sample_rows"] <= 2 * report["input"]["logical_samples"],
                 "writer_counts_match_sql": typed_storage["writer_counts_match_sql"],
                 "all_values_retained": typed_storage["typed_logical_rows"] == config.fields_per_sample * report["input"]["logical_samples"],
                 "no_eav_fallback": typed_storage["eav_rows"] == 0,
                 "storage_at_most_2x_csv": amplification <= 2,
                 "storage_reduced_at_least_80_percent": reduction >= 0.8}
        report["acceptance"] = {"gates": gates, "storage_amplification": amplification,
                                 "storage_reduction": reduction,
                                 "query_latency_gates": "not a C2b storage acceptance condition"}
        if inputs.get("control"):
            before = inputs["control"]
            after = describe_input(Path(before["baseline"]))
            report["read_only_verification"] = before == after
            if before != after:
                raise AssertionError("Historical control changed")
        if any(sha256(Path(row["path"])) != row["sha256"] for row in source_info):
            raise AssertionError("Benchmark source changed")
        # Tiny self-checks have catalog fixed costs; storage ratio gates apply to
        # the published standard scales, while parity/cardinality always apply.
        required = gates if args.rows is None else {key: value for key, value in gates.items() if key not in {
            "storage_at_most_2x_csv", "storage_reduced_at_least_80_percent"}}
        if not all(required.values()):
            raise AssertionError(f"Storage acceptance failed: {gates}")
        report["status"] = "succeeded"
    except BaseException as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        if "settings" in report:
            report["final_production_files_sha256"] = {
                name: sha256(REPO / "packages/core/src/datascope_core" / name)
                for name in report["settings"]["production_files_sha256"]
            }
            report["production_code_changed_during_run"] = (
                report["final_production_files_sha256"] != report["settings"]["production_files_sha256"]
            )
        if not args.keep_artifacts:
            if work.resolve().parent != (args.output_dir.resolve() / ".work") or json.loads(owner.read_text())["run_id"] != run_id:
                raise RuntimeError("Benchmark cleanup ownership mismatch")
            gc.collect()
            try:
                shutil.rmtree(work)
                report["cleanup"] = "removed only this run's owned work directory"
            except OSError as error:
                report["cleanup"] = {"retained_owned_directory": str(work), "error": str(error)}
        else:
            report["cleanup"] = "kept this run's artifacts by explicit option"
        write_json(output, report)
        write_markdown(output.with_suffix(".md"), report)
        print(f"Report: {output}", flush=True)


def write_markdown(path, report):
    lines = ["# C2b production typed storage", "", f"Status: {report['status']}", "",
             "| Backend | Catalog MB | Peak RSS MB | Prepare s |", "| --- | ---: | ---: | ---: |"]
    for name, item in report["backends"].items():
        prepare = f"{item['prepare_ms']/1000:.3f}" if "prepare_ms" in item else "n/a"
        lines.append(f"| {name} | {item['storage']['database_bytes']/1e6:.3f} | {item['memory']['peak_rss_mb']:.3f} | {prepare} |")
    lines += ["", "| Query | EAV P50/P95 ms | Typed time P50/P95 ms | Typed none P50/P95 ms |",
              "| --- | ---: | ---: | ---: |"]
    for name in NAMES:
        values = []
        for backend in ("eav", "typed_time", "typed_none"):
            query = report["backends"].get(backend, {}).get("queries", {}).get(name)
            values.append(f"{query['median_ms']:.2f} / {query['p95_ms']:.2f}" if query else "n/a")
        lines.append("| " + " | ".join((name, *values)) + " |")
    lines += ["", "Acceptance: `" + json.dumps(report.get("acceptance", {})) + "`", "",
              "Raw JSON includes every timing sample, SQL/EXPLAIN, untimed counts, source/code hashes and storage objects.",
              "This measures index construction and compatibility queries, not Rerun build or Diagnostics performance."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preset", choices=("smoke", "small", "medium"), default="smoke")
    parser.add_argument("--rows", type=int, help="Tiny generated self-check; not a formal scale")
    parser.add_argument("--control", type=Path, help="C2a archived report for retained Smoke/Small inputs")
    parser.add_argument("--phase-c-input", type=Path, default=REPO / "benchmarks/results/baselines/2026-10-17-phase-c/medium.json")
    parser.add_argument("--output-dir", type=Path, default=REPO / "benchmarks/results")
    parser.add_argument("--query-runs", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--keep-artifacts", action="store_true")
    parser.add_argument("--worker", choices=("eav", "typed_time", "typed_none"), help=argparse.SUPPRESS)
    parser.add_argument("--manifest", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker-output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.query_runs < 1 or args.warmups < 0 or (args.rows is not None and args.rows < 2):
        parser.error("runs >= 1, warmups >= 0, rows >= 2 required")
    if args.control and (args.rows is not None or args.preset == "medium"):
        parser.error("--control is only for retained standard Smoke/Small inputs")
    worker(args) if args.worker else run(args)


if __name__ == "__main__":
    main()
