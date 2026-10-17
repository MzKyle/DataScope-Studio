"""Read-only, separate-process production Custom Query comparison (no DuckDB)."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(REPO))

from datascope_core.query import run_custom_query
from datascope_core.query_sql import CustomQueryPlan, register_custom_query_functions
from datascope_core.workspace import Workspace
import datascope_core.query as query_module
import datascope_core.workspace_query as workspace_query
from benchmarks.benchmark_memory import MemorySampler
from benchmarks.benchmark_models import DatasetConfig
from benchmarks.benchmark_query import measure_query, query_calls, validate_query
from benchmarks.benchmark_report import environment

NAMES = ("custom_scalar_key", "custom_time_range", "custom_numeric_threshold")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def runtime() -> dict:
    result = environment(REPO)
    result["production_files_sha256"] = {name: sha256(REPO / "packages/core/src/datascope_core" / name)
        for name in ("query.py", "query_sql.py", "workspace_query.py")}
    return result


class ReadOnlyWorkspace(Workspace):
    def __init__(self, root):
        self.root = Path(root)
        self.db_path = self.root / "metadata.sqlite"
        self.traces = None

    def _connect(self):
        conn = sqlite3.connect(self.db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = ON")
        conn.execute("pragma busy_timeout = 5000")
        if self.traces is not None:
            conn.set_trace_callback(self.traces.append)
        return conn


class LegacyWorkspace(ReadOnlyWorkspace):
    def custom_query(self, project_id, filters=None, recording_ids=None, semantic_types=None, limit=1000):
        self.get_project(project_id)
        # Explicitly bypass the new plan. Original Python value/filter code is unchanged.
        return run_custom_query(self._iter_query_rows(project_id, recording_ids=recording_ids,
                                semantic_types=semantic_types), filters, limit)


def describe_input(path: Path) -> dict:
    baseline = json.loads(path.read_text(encoding="utf-8"))
    if baseline["status"] != "succeeded":
        raise ValueError("Baseline must have succeeded")
    root = baseline["artifacts"]["workspace"]
    source = Path(baseline["artifacts"]["dataset"])
    if sha256(source) != baseline["source_checksum"]:
        raise ValueError("Source checksum differs from baseline")
    workspace = ReadOnlyWorkspace(root)
    with workspace._connect() as conn:
        recording = conn.execute("SELECT id,project_id,source_id FROM recordings WHERE run_name = 'primary'").fetchone()
        if recording is None:
            raise ValueError("Primary recording not found")
        samples = conn.execute("SELECT count(*) FROM query_rows WHERE recording_id = ?", (recording["id"],)).fetchone()[0]
        schema = [tuple(row) for row in conn.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name")]
        version = conn.execute("pragma user_version").fetchone()[0]
    config = DatasetConfig(**{key: baseline["dataset"][key] for key in
                            ("rows", "frequency_hz", "scalar_fields", "state_fields", "seed")})
    if samples != config.rows * config.fields_per_sample:
        raise ValueError("Retained catalog cardinality differs from source")
    return {"baseline": str(path.resolve()), "baseline_sha256": sha256(path), "workspace": str(workspace.root),
            "database": str(workspace.db_path.resolve()), "database_sha256": sha256(workspace.db_path),
            "database_bytes": workspace.db_path.stat().st_size, "schema": schema, "schema_version": version,
            "source": str(source.resolve()), "source_sha256": baseline["source_checksum"],
            "source_bytes": source.stat().st_size, "dataset": config.report(),
            "primary_query_rows": samples, "recording_id": recording["id"], "project_id": recording["project_id"]}


def worker(args) -> None:
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    config = DatasetConfig(**{key: manifest["dataset"][key] for key in
                            ("rows", "frequency_hz", "scalar_fields", "state_fields", "seed")})
    workspace = (LegacyWorkspace if args.worker == "legacy" else ReadOnlyWorkspace)(manifest["workspace"])
    ids = [manifest["recording_id"]]
    calls = query_calls(workspace, manifest["project_id"], ids, config, args.query_limit)
    memory = MemorySampler()
    report = {"status": "running", "environment": runtime(), "queries": {}, "diagnostics": {}}
    with memory:
        for name in NAMES:
            report["queries"][name] = measure_query(calls[name],
                lambda actual, name=name: validate_query(actual, name, config, args.query_limit, ids, 0),
                runs=args.query_runs, warmups=args.warmups, memory=memory, name=f"{args.worker}/{name}")
            write_json(args.worker_output, report)
    report["memory"] = memory.report()
    # Instrumentation runs after formal latency/RSS sampling, never inside timers.
    for name in NAMES:
        counts = {"fetched_rows": 0, "json_decodes": 0}
        convert, decode = workspace_query.row_to_dict, query_module._db_value
        def counted_row(row):
            counts["fetched_rows"] += 1
            return convert(row)
        def counted_decode(row):
            counts["json_decodes"] += 1
            return decode(row)
        workspace.traces = []
        with patch.object(workspace_query, "row_to_dict", counted_row), patch.object(query_module, "_db_value", counted_decode):
            actual = calls[name]()
        validate_query(actual, name, config, args.query_limit, ids, 0)
        from benchmarks.benchmark_query import result_digest
        if result_digest(actual) != report["queries"][name]["result_sha256"]:
            raise AssertionError("Instrumented query differs from timed query")
        sql = next(text for text in reversed(workspace.traces) if "select qr.*" in text)
        workspace.traces = None
        with workspace._connect() as conn:
            register_custom_query_functions(conn, CustomQueryPlan(needs_unicode_lower=True))
            plan = [tuple(row) for row in conn.execute("EXPLAIN QUERY PLAN " + sql)]
        report["diagnostics"][name] = {**counts, "sql": sql, "query_plan": plan,
            "scope": "separate untimed pass; fetched rows are Python-consumed rows, not SQLite scanned rows"}
        print(f"  {args.worker}/{name}: fetched {counts['fetched_rows']:,}, decoded {counts['json_decodes']:,}", flush=True)
    report["status"] = "succeeded"
    write_json(args.worker_output, report)


def markdown(report) -> str:
    lines = [f"# Production Custom Query pushdown: {report['run_id']}", "", f"Status: {report['status']}.", "",
        "One warm-up/five runs by default; nearest-rank P95. Separate sequential workers and untimed counters.",
        "Production connections/caches/indexes unchanged; no ANALYZE, migration, new index or Rerun build.", "",
        "| Query | Legacy P50/P95 ms | Pushdown P50/P95 ms | P95 speedup | Fetched old/new | Decoded old/new |",
        "| --- | ---: | ---: | ---: | ---: | ---: |"]
    if len(report["backends"]) == 2:
        for name, comparison in report.get("comparison", {}).items():
            old, new = (report["backends"][mode] for mode in ("legacy", "pushdown"))
            a, b = old["queries"][name], new["queries"][name]
            c, d = old["diagnostics"][name], new["diagnostics"][name]
            lines.append(f'| {name} | {a["median_ms"]:.2f} / {a["p95_ms"]:.2f} | '
                         f'{b["median_ms"]:.2f} / {b["p95_ms"]:.2f} | {comparison["p95_speedup"]:.2f}× | '
                         f'{c["fetched_rows"]} / {d["fetched_rows"]} | {c["json_decodes"]} / {d["json_decodes"]} |')
        lines += ["", f'Gate passed: **{report.get("acceptance", {}).get("passed", "not evaluated")}**.', "",
                  "Peak RSS excludes the additional instrumented pass; full SQL, plans, SHA256 and raw samples are in JSON."]
    return "\n".join(lines) + "\n"


def run(args) -> Path:
    if args.query_runs < 1 or args.warmups < 0 or args.query_limit < 1:
        raise ValueError("Positive query runs/limit and nonnegative warmups required")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    run_id = f"benchmark_c2a_{started:%Y%m%d_%H%M%S}_{uuid4().hex[:8]}"
    work = output / ".work" / run_id
    work.mkdir(parents=True, exist_ok=False)
    path = output / (run_id + ".json")
    report = {"run_id": run_id, "started_at": started.isoformat(), "status": "running", "environment": runtime(),
              "settings": {"query_runs": args.query_runs, "warmups": args.warmups, "query_limit": args.query_limit},
              "backends": {}}
    try:
        manifest = describe_input(args.baseline)
        report["input"] = manifest
        write_json(work / "manifest.json", manifest)
        for mode in ("legacy", "pushdown"):
            target = work / (mode + ".json")
            print(f'{mode}: {manifest["dataset"]["rows"]:,} primary samples', flush=True)
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", mode,
                "--manifest", str(work / "manifest.json"), "--worker-output", str(target),
                "--query-runs", str(args.query_runs), "--warmups", str(args.warmups),
                "--query-limit", str(args.query_limit)], check=True, cwd=REPO)
            report["backends"][mode] = json.loads(target.read_text(encoding="utf-8"))
            write_json(path, report)
        report["comparison"] = {}
        for name in NAMES:
            old, new = (report["backends"][mode]["queries"][name] for mode in ("legacy", "pushdown"))
            if old["result_sha256"] != new["result_sha256"] or old["result_rows"] != new["result_rows"]:
                raise AssertionError("Legacy/pushdown result mismatch: " + name)
            report["comparison"][name] = {"p95_speedup": old["p95_ms"] / new["p95_ms"], "exact_parity": True}
        rows = manifest["dataset"]["rows"]
        gate = "all three P95 <= 1000 ms" if rows == 30000 else "all three P95 speedup >= 2" if rows == 300000 else "development only"
        passed = all(data["p95_ms"] <= 1000 for data in report["backends"]["pushdown"]["queries"].values()) if rows == 30000 else (
            all(data["p95_speedup"] >= 2 for data in report["comparison"].values()) if rows == 300000 else True)
        report["acceptance"] = {"gate": gate, "passed": passed, "scope": "Custom Query only; not typed storage or diagnostics gates"}
        late = report["backends"]["pushdown"]["diagnostics"]["custom_time_range"]
        if late["fetched_rows"] != report["backends"]["pushdown"]["queries"]["custom_time_range"]["result_rows"]:
            raise AssertionError("Time-window query fetched rows outside its output window")
        if describe_input(args.baseline) != manifest:
            raise AssertionError("Retained source/catalog/schema changed during comparison")
        report["read_only_verification"] = "source/catalog SHA256, bytes, schema, version and cardinality unchanged"
        report["status"] = "succeeded"
    except Exception as error:
        report.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        # Only this newly created, direct child of the output's .work is owned.
        if work.resolve().parent != (output / ".work").resolve() or work.name != run_id:
            raise RuntimeError("Refusing cleanup outside owned run")
        try:
            shutil.rmtree(work)
            report["cleanup"] = {"status": "removed_owned_run_directory", "path": str(work)}
        except OSError as error:
            report["cleanup"] = {"status": "manual_cleanup_required", "path": str(work), "error": str(error)}
        write_json(path, report)
        path.with_suffix(".md").write_text(markdown(report), encoding="utf-8")
    return path


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--baseline", type=Path)
    result.add_argument("--output-dir", type=Path, default=REPO / "benchmarks/results")
    result.add_argument("--query-runs", type=int, default=5)
    result.add_argument("--warmups", type=int, default=1)
    result.add_argument("--query-limit", type=int, default=1000)
    result.add_argument("--worker", choices=("legacy", "pushdown"), help=argparse.SUPPRESS)
    result.add_argument("--manifest", type=Path, help=argparse.SUPPRESS)
    result.add_argument("--worker-output", type=Path, help=argparse.SUPPRESS)
    return result


if __name__ == "__main__":
    args = parser().parse_args()
    if args.worker:
        worker(args)
    else:
        if args.baseline is None:
            raise SystemExit("--baseline <retained Phase A report.json> is required")
        report_path = run(args)
        print(report_path)
        if not json.loads(report_path.read_text(encoding="utf-8"))["acceptance"]["passed"]:
            raise SystemExit(2)
