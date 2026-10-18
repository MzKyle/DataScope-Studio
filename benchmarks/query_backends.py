"""C2c production query comparison, using one immutable typed catalog per run."""
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
from unittest.mock import patch
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(REPO))

import datascope_core.query as query_module
from datascope_core.models import MappingSpec
from datascope_core.query_backend import register_backend_functions
from datascope_core.query_sql import CustomQueryPlan, register_custom_query_functions
from datascope_core.workspace import Workspace
from benchmarks.benchmark_memory import MemorySampler
from benchmarks.benchmark_models import DatasetConfig, PRESETS
from benchmarks.benchmark_query import measure_query, query_calls, validate_query
from benchmarks.benchmark_report import environment
from benchmarks.c2b_query_reference import C2bQueryReference
from benchmarks.custom_query_pushdown import ReadOnlyWorkspace, describe_input, sha256, write_json
from benchmarks.typed_storage import copy_metadata, fresh_inputs, retained_inputs, storage

FILTERS = ("find_errors", "low_battery", "custom_scalar_key", "custom_time_range", "custom_numeric_threshold")
REGRESSIONS = ("state_duration", "compare")
CODE = ("packages/core/src/datascope_core/query_backend.py", "packages/core/src/datascope_core/query.py",
        "packages/core/src/datascope_core/query_sql.py", "packages/core/src/datascope_core/query_typed.py",
        "packages/core/src/datascope_core/workspace_query.py", "benchmarks/c2b_query_reference.py",
        "benchmarks/query_backends.py")


class CompatibilityWorkspace(C2bQueryReference, ReadOnlyWorkspace):
    pass


def execution(workspace, call):
    """Untimed instrumentation. Cursor rows are not SQLite rows examined."""
    workspace._query_read_stats = {}
    workspace.traces = []
    decodes = 0
    original = query_module._db_value
    def decode(row):
        nonlocal decodes
        decodes += 1
        return original(row)
    try:
        with patch.object(query_module, "_db_value", decode):
            call()
        statements = list(dict.fromkeys(s for s in workspace.traces if s.lstrip().upper().startswith("SELECT")))
        counts = {**workspace._query_read_stats, "business_json_decodes": decodes}
    finally:
        workspace.traces = None
        del workspace._query_read_stats
    plans, candidates = [], {}
    conn = workspace._connect()
    try:
        register_backend_functions(conn)
        register_custom_query_functions(conn, CustomQueryPlan(needs_unicode_lower=True))
        for sql in statements:
            item = {"sql": sql, "explain": [list(row) for row in conn.execute("EXPLAIN QUERY PLAN " + sql)]}
            if "FROM typed_samples_" in sql or "from query_rows qr" in sql.lower():
                unbounded = re.split(r"\s+order by\s+", sql, flags=re.I)[0]
                item["matching_candidates_without_limit"] = conn.execute(
                    "SELECT count(*) FROM (" + unbounded + ")").fetchone()[0]
            plans.append(item)
            table = re.search(r"FROM (typed_samples_[0-9a-f]+) s", sql)
            dataset = re.search(r"s.dataset_id = (\d+)", sql)
            if table and dataset:
                bounds = re.findall(r"s.time (>=|<=) ([-+\deE.]+)", sql)
                key = (table[1], dataset[1], tuple(bounds))
                if key not in candidates:
                    where = "dataset_id = ?" + "".join(f" AND time {op} ?" for op, _ in bounds)
                    candidates[key] = conn.execute(f"SELECT count(*) FROM {table[1]} WHERE {where}",
                        [int(dataset[1]), *[float(v) for _, v in bounds]]).fetchone()[0]
    finally:
        conn.close()
    counts["distinct_time_candidate_samples"] = sum(candidates.values())
    counts["sqlite_rows_examined"] = None
    counts["scope"] = "separate untimed pass; fetched projection rows can repeat samples across fields; SQLite rows/pages examined unavailable"
    return {"counts": counts, "statements": plans}


def worker(args):
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    memory = MemorySampler()
    result = {"backend": args.worker, "environment": environment(REPO), "queries": {}}
    with memory:
        if args.worker == "prepare":
            workspace = Workspace(Path(manifest["work"]) / "typed")
            copy_metadata(workspace, manifest)
            started = time.perf_counter()
            last = started
            def progress():
                nonlocal last
                if time.perf_counter() - last >= 15:
                    last = time.perf_counter()
                    print(f"typed catalog preparation: {last - started:.0f}s", flush=True)
            for recording in manifest["records"]:
                workspace._index_recording(recording["recording_id"], workspace.get_source(recording["source_id"]),
                    MappingSpec(**recording["spec"]), query_storage="typed_sqlite", cancel_check=progress)
            result["prepare_ms"] = (time.perf_counter() - started) * 1000
            result["storage"] = storage(workspace)
        else:
            workspace = (CompatibilityWorkspace if args.worker == "compat" else ReadOnlyWorkspace)(
                manifest["control"]["workspace"] if args.worker == "eav" else Path(manifest["work"]) / "typed")
            ids = [r["recording_id"] for r in manifest["records"]]
            config = DatasetConfig(**manifest["config"])
            calls = query_calls(workspace, manifest["project_id"], ids, config, manifest["limit"])
            for name in manifest["query_names"]:
                result["queries"][name] = measure_query(calls[name],
                    lambda value, name=name: validate_query(value, name, config, manifest["limit"], ids,
                                                           manifest["records"][1]["rows"]),
                    runs=manifest["runs"], warmups=manifest["warmups"], memory=memory, name=f"{args.worker}/{name}")
                result["queries"][name]["execution"] = execution(workspace, calls[name])
    result["memory"] = memory.report()
    write_json(args.worker_output, result)


def write_markdown(path, report):
    lines = ["# C2c production query backends", "", f"Status: {report['status']}", "",
             "| Query | EAV P50/P95 ms | C2b compatibility P50/P95 ms | Typed SQL P50/P95 ms |",
             "| --- | ---: | ---: | ---: |"]
    for name in report.get("query_names", FILTERS):
        values = []
        for backend in ("eav", "compat", "typed_sql"):
            item = report["backends"].get(backend, {}).get("queries", {}).get(name)
            values.append(f"{item['median_ms']:.2f} / {item['p95_ms']:.2f}" if item else "n/a")
        lines.append("| " + " | ".join((name, *values)) + " |")
    lines += ["", "Acceptance: `" + json.dumps(report.get("acceptance", {})) + "`", "",
              "One catalog, separate sequential read-only query processes; 1 warm-up and 5 samples by default.",
              "Raw JSON contains SQL/EXPLAIN, untimed cursor/candidate/decode counts, RSS, source and code hashes.",
              "Medium latency is report-only. This is not full seven-query or Diagnostics acceptance."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args):
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    work = args.output_dir.resolve() / ".work" / ("query_backends_" + run_id)
    work.mkdir(parents=True, exist_ok=False)
    write_json(work / "owner.json", {"run_id": run_id})
    output = args.output_dir / ("query_backends_" + run_id + ".json")
    report = {"format_version": 1, "run_id": run_id, "preset": args.preset, "status": "running",
              "environment": environment(REPO), "work": str(work), "backends": {},
              "production_files_sha256": {p: sha256(REPO / p) for p in CODE}}
    try:
        config = DatasetConfig(rows=args.rows or PRESETS[args.preset])
        if args.rows is not None:
            inputs = fresh_inputs(work, config)
        elif args.preset == "medium":
            inputs = fresh_inputs(work, config, json.loads(args.phase_c_input.read_text(encoding="utf-8")))
        else:
            control = args.control or REPO / "benchmarks/results/baselines/2026-10-17-phase-c2a" / (args.preset + ".json")
            inputs = retained_inputs(args.preset, control)
        sources = [{"path": r["uri"], "bytes": Path(r["uri"]).stat().st_size,
                    "sha256": sha256(Path(r["uri"]))} for r in inputs["metadata"]["sources"]]
        names = FILTERS + (() if args.preset == "medium" and args.rows is None else REGRESSIONS)
        manifest = {**inputs, "work": str(work), "config": asdict(config), "limit": 1000,
                    "runs": args.query_runs, "warmups": args.warmups, "query_names": names}
        manifest_path = work / "manifest.json"
        write_json(manifest_path, manifest)
        report.update({"input": {"sources": sources, "config": asdict(config), "control": inputs.get("control")},
                       "query_names": names, "settings": {"runs": args.query_runs, "warmups": args.warmups, "limit": 1000}})
        workers = ("prepare",) + (("eav",) if inputs.get("control") else ()) + ("compat", "typed_sql")
        for name in workers:
            worker_output = work / (name + ".json")
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", name,
                            "--manifest", str(manifest_path), "--worker-output", str(worker_output)], check=True)
            report["backends"][name] = json.loads(worker_output.read_text(encoding="utf-8"))
            if name == "prepare":
                catalog = work / "typed/metadata.sqlite"
                report["catalog_before"] = {"sha256": sha256(catalog), "bytes": catalog.stat().st_size}
            write_json(output, report)
        for name in names:
            assert len({v["queries"][name]["result_sha256"] for k, v in report["backends"].items()
                        if k != "prepare"}) == 1, f"Parity failed: {name}"
        after = {"sha256": sha256(catalog), "bytes": catalog.stat().st_size}
        assert after == report["catalog_before"], "Typed catalog changed during queries"
        report["typed_catalog_read_only"] = True
        if inputs.get("control"):
            assert describe_input(Path(inputs["control"]["baseline"])) == inputs["control"], "Historical EAV control changed"
            report["historical_control_read_only"] = True
        assert all(sha256(Path(r["path"])) == r["sha256"] for r in sources), "Source changed"
        formal = args.rows is None and args.preset in {"smoke", "small"}
        gates = {name: report["backends"]["typed_sql"]["queries"][name]["p95_ms"] <= 1000 for name in FILTERS}
        layout = report["backends"]["prepare"]["storage"]
        assert layout["eav_rows"] == 0 and layout["writer_counts_match_sql"]
        assert layout["typed_logical_rows"] == sum(r["rows"] for r in inputs["records"]) * config.fields_per_sample
        report["acceptance"] = {"parity": True, "latency_gates": gates, "latency_required": formal,
                                "all_fields_retained": True, "no_eav_fallback": True}
        if formal and not all(gates.values()):
            raise AssertionError(f"Latency acceptance failed: {gates}")
        assert {p: sha256(REPO / p) for p in CODE} == report["production_files_sha256"], "Code changed during measurement"
        report["status"] = "succeeded"
    except BaseException as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        report["final_files_sha256"] = {p: sha256(REPO / p) for p in CODE}
        report["production_code_changed_during_run"] = report["final_files_sha256"] != report["production_files_sha256"]
        if not args.keep_artifacts:
            if (work.resolve().parent != args.output_dir.resolve() / ".work"
                    or json.loads((work / "owner.json").read_text())["run_id"] != run_id):
                raise RuntimeError("Cleanup ownership mismatch")
            gc.collect()
            try:
                shutil.rmtree(work)
                report["cleanup"] = "removed only this run's owned scratch directory"
            except OSError as error:
                report["cleanup"] = {"retained": str(work), "error": str(error)}
        else:
            report["cleanup"] = "retained by explicit option"
        write_json(output, report)
        write_markdown(output.with_suffix(".md"), report)
        print(f"Report: {output}", flush=True)
    return output


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--preset", choices=("smoke", "small", "medium"), default="smoke")
    result.add_argument("--rows", type=int, help="Generated self-check, not formal performance acceptance")
    result.add_argument("--control", type=Path)
    result.add_argument("--phase-c-input", type=Path, default=REPO / "benchmarks/results/baselines/2026-10-17-phase-c/medium.json")
    result.add_argument("--output-dir", type=Path, default=REPO / "benchmarks/results")
    result.add_argument("--query-runs", type=int, default=5)
    result.add_argument("--warmups", type=int, default=1)
    result.add_argument("--keep-artifacts", action="store_true")
    result.add_argument("--worker", choices=("prepare", "eav", "compat", "typed_sql"), help=argparse.SUPPRESS)
    result.add_argument("--manifest", type=Path, help=argparse.SUPPRESS)
    result.add_argument("--worker-output", type=Path, help=argparse.SUPPRESS)
    return result


def main():
    command = parser()
    args = command.parse_args()
    if args.query_runs < 1 or args.warmups < 0 or (args.rows is not None and args.rows < 2):
        command.error("runs >= 1, warmups >= 0, rows >= 2 required")
    if args.control and (args.rows is not None or args.preset == "medium"):
        command.error("--control applies only to standard Smoke/Small")
    if not args.worker and args.rows is None and (args.query_runs != 5 or args.warmups != 1):
        command.error("standard presets require one warm-up and five measurements; use --rows for self-checks")
    worker(args) if args.worker else run(args)


if __name__ == "__main__":
    main()
