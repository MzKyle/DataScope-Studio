"""Independent typed-sample PoC; never used by production Query/API/CLI paths."""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(REPO))

import duckdb

from datascope_core.mapping import load_mapping_yaml
from datascope_core.query import QUERY_COLUMNS
from datascope_core.workspace import Workspace

from benchmarks.benchmark_memory import MemorySampler
from benchmarks.benchmark_models import DatasetConfig
from benchmarks.benchmark_query import measure_query, query_calls
from benchmarks.benchmark_report import environment
from benchmarks.generate_dataset import scalar_names, state_names


class ReadOnlyWorkspace(Workspace):
    """Reuse production query methods without initializing or writing the retained catalog."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.db_path = self.root / "metadata.sqlite"

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn


def literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def equivalent(actual: object, expected: object) -> None:
    """CSV numeric readers/SQL aggregation may differ in the last floating-point bits."""
    if isinstance(actual, dict) and isinstance(expected, dict):
        if actual.keys() != expected.keys():
            raise AssertionError("PoC result keys differ from SQLite")
        for key in actual:
            equivalent(actual[key], expected[key])
    elif isinstance(actual, list) and isinstance(expected, list):
        if len(actual) != len(expected):
            raise AssertionError("PoC result cardinality differs from SQLite")
        for left, right in zip(actual, expected):
            equivalent(left, right)
    elif isinstance(actual, (float, int)) and isinstance(expected, (float, int)):
        if not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-8):
            raise AssertionError(f"PoC numeric mismatch: {actual} != {expected}")
    elif actual != expected:
        raise AssertionError(f"PoC value mismatch: {actual!r} != {expected!r}")


def eav_select(table: str, recording: dict, mapping_path: str) -> str:
    """Expand only at query time; SQL can prune unused union branches and sample columns."""
    spec = load_mapping_yaml(mapping_path)
    selections = []
    for stream in spec.streams:
        if not stream.get("enabled", True):
            continue
        for field in stream["source_fields"]:
            path = stream["entity_path"]
            if stream["semantic_type"] == "scalar_group":
                path += "/" + field
            selections.append(
                f"select {literal(recording['id'])} recording_id, \"timestamp\" as \"time\", "
                f"{literal(path)} entity_path, {literal(stream['semantic_type'])} semantic_type, "
                f"{literal(field)} as \"key\", cast(to_json({identifier(field)}) as varchar) value_json "
                f"from {table}"
            )
    return " union all ".join(selections)


def sql_queries(table: str, recording_ids: list[str], config: DatasetConfig, limit: int) -> dict[str, str]:
    primary = "recording_id = " + literal(recording_ids[0])
    numeric = "semantic_type in ('scalar', 'scalar_group')"
    key = "scalar_000" if config.scalar_fields > 10 else "temperature"
    start = math.floor(0.9 * (config.rows - 1))
    end = min(config.rows - 1, start + 10)
    conditions = {
        "find_errors": "semantic_type = 'state' and (lower(value_json) like '%error%' "
        "or lower(value_json) like '%warn%' or lower(value_json) like '%fault%')",
        "low_battery": numeric + " and (lower(key) like '%battery%' or "
        "lower(entity_path) like '%battery%') and cast(value_json as double) < 0.2",
        "custom_scalar_key": numeric + f" and lower(key) like {literal('%' + key + '%')}",
        "custom_time_range": f'"time" >= {start / config.frequency_hz!r} and "time" <= {end / config.frequency_hz!r}',
        "custom_numeric_threshold": numeric + " and lower(key) like '%battery%' "
        "and cast(value_json as double) < 0.1",
    }
    queries = {
        name: f'select recording_id, "time", entity_path, key, value_json from {table} '
        f'where {primary} and {condition} order by recording_id, "time", entity_path, key limit {limit}'
        for name, condition in conditions.items()
    }
    queries["state_duration"] = (
        'with states as (select *, coalesce(lead("time") over '
        '(partition by recording_id, entity_path, key order by "time"), "time") - "time" duration '
        f"from {table} where {primary} and semantic_type = 'state') "
        'select recording_id, "time", entity_path, key, value_json, duration from states '
        f'order by recording_id, entity_path, key, "time" limit {limit}'
    )
    selected = ", ".join(literal(value) for value in recording_ids)
    queries["compare"] = (
        "with metrics as (select *, cast(value_json as double) number, "
        "first_value(value_json) over (partition by recording_id, entity_path, key "
        f'order by "time" desc) latest from {table} where recording_id in ({selected}) '
        f"and {numeric} and key in ('battery', 'temperature')) "
        "select recording_id, null, entity_path, key, count(*), min(number), max(number), "
        "avg(number), cast(max(latest) as double) from metrics "
        f"group by recording_id, entity_path, key order by recording_id, entity_path, key limit {limit}"
    )
    return queries


def decode_result(rows: list[tuple], name: str) -> dict:
    output = []
    for row in rows:
        if name == "compare":
            value = {"count": row[4], "min": row[5], "max": row[6], "mean": row[7], "latest": row[8]}
        else:
            value = json.loads(row[4])
            if name == "state_duration":
                value = {"state": value, "duration": row[5]}
        output.append(dict(zip(QUERY_COLUMNS, (*row[:4], value))))
    return {"columns": QUERY_COLUMNS, "rows": output}


def sqlite_call(db_path: Path, sql: str, name: str) -> dict:
    # Read-only, new connection per call, matching production's connection lifecycle.
    conn = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        return decode_result(conn.execute(sql).fetchall(), name)
    finally:
        conn.close()


def run_poc(args: argparse.Namespace) -> Path:
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    if baseline["status"] != "succeeded":
        raise ValueError("PoC requires a successful baseline")
    workspace_path = baseline["artifacts"].get("workspace")
    dataset_path = baseline["artifacts"].get("dataset")
    if not workspace_path or not dataset_path:
        raise ValueError("Baseline must retain --keep-dataset --keep-workspace")
    dataset = Path(dataset_path)
    db_path = Path(workspace_path) / "metadata.sqlite"
    if not dataset.is_file() or not db_path.is_file():
        raise ValueError("Retained baseline artifacts no longer exist")
    digest = hashlib.sha256()
    with dataset.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != baseline["source_checksum"]:
        raise ValueError("PoC source checksum differs from the measured SQLite input")
    config = DatasetConfig(**{key: baseline["dataset"][key] for key in (
        "rows", "frequency_hz", "scalar_fields", "state_fields", "seed")})
    conn = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        recordings = [dict(conn.execute(
            "select r.*, s.uri from recordings r join sources s on s.id = r.source_id "
            "where r.run_name = ?", (name,)).fetchone()) for name in ("primary", "peer")]
        mapping_paths = [conn.execute("select path from mappings where source_id = ?",
                                     (recording["source_id"],)).fetchone()[0] for recording in recordings]
    finally:
        conn.close()
    ids = [recording["id"] for recording in recordings]
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    run_environment = {**environment(REPO), "duckdb_version": duckdb.__version__}
    run_id = f"duckdb_poc_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{uuid4().hex[:8]}"
    work = output / ".work" / run_id
    work.mkdir(parents=True, exist_ok=False)
    report_path = output / (run_id + ".json")
    memory = MemorySampler()
    duck = None
    report = {"format_version": 1, "run_id": run_id, "status": "running",
              "environment": run_environment,
              "baseline_json": str(args.baseline.resolve()), "source_checksum": digest.hexdigest(),
              "dataset": config.report(), "query_runs": args.query_runs, "warmups": args.warmups,
              "query_limit": baseline["settings"]["query_limit"],
              "implementation_scope": "deterministic non-null CSV scalar/state samples; two recordings",
              "not_covered": ["diagnostics parity", "time_sync", "CV/ROS sample normalization",
                              "stream deletion", "concurrent writers", "schema evolution"],
              "artifacts": str(work) if args.keep_artifacts else None}
    try:
        with memory:
            # Production SQLite results are the independent correctness reference.
            workspace = ReadOnlyWorkspace(workspace_path)
            calls = query_calls(workspace, recordings[0]["project_id"], ids, config,
                                report["query_limit"])
            calls.pop("time_sync")
            golden = {}
            with memory.stage("sqlite_correctness_reference"):
                for name, function in calls.items():
                    print(f"SQLite reference: {name}", flush=True)
                    golden[name] = function()
            duck_path = work / "samples.duckdb"
            duck = duckdb.connect(str(duck_path))
            duck.execute(f"set threads = {args.threads}")
            duck.execute("set memory_limit = '1GB'")
            duck.execute(f"set temp_directory = {literal(work / 'spill')}")
            report["duckdb_settings"] = {"threads": args.threads, "memory_limit": "1GB"}
            types = {"timestamp": "DOUBLE", **{name: "DOUBLE" for name in scalar_names(config)},
                     **{name: "VARCHAR" for name in state_names(config)}, "error_code": "BIGINT"}
            ingest_started = perf_counter()
            with memory.stage("duckdb_csv_ingest"):
                for index, recording in enumerate(recordings):
                    duck.execute(f"create table samples_{index} as select * from read_csv(?, columns=?, header=true)",
                                 [recording["uri"], types])
                duck.execute("checkpoint")
            report["duckdb_ingest_ms"] = (perf_counter() - ingest_started) * 1000
            report["duckdb_size_mb"] = duck_path.stat().st_size / 1_000_000
            paths = []
            export_started = perf_counter()
            with memory.stage("parquet_export"):
                for index in range(2):
                    path = work / f"recording_{index}.parquet"
                    duck.execute(f"copy samples_{index} to {literal(path)} (format parquet, compression zstd)")
                    paths.append(path)
            report["parquet_export_ms"] = (perf_counter() - export_started) * 1000
            report["parquet_size_mb"] = sum(path.stat().st_size for path in paths) / 1_000_000
            report["csv_to_parquet_via_duckdb_ms"] = report["duckdb_ingest_ms"] + report["parquet_export_ms"]
            counts = [duck.execute(f"select count(*) from samples_{index}").fetchone()[0] for index in range(2)]
            if counts != [config.rows, baseline["peer"]["dataset"]["rows"]]:
                raise AssertionError("Typed dataset row count differs from baseline")
            report["normalized_sample_rows"] = counts
            report["sqlite_primary_query_rows"] = baseline["storage"]["query_rows"]
            report["sqlite_primary_size_mb"] = baseline["storage"]["sqlite_size_mb"]
            report["sqlite_primary_and_peer_live_size_mb"] = db_path.stat().st_size / 1_000_000
            report["sqlite_index_build_ms"] = baseline["pipeline"]["query_index_ms"]
            report["sqlite_production_queries"] = {name: baseline["queries"][name] for name in golden}
            engines = {"sqlite_sql_pushdown": "query_rows", "duckdb_table": "duck_eav",
                       "duckdb_parquet": "parquet_eav"}
            view_started = perf_counter()
            for name, relation in (('duck_eav', 'samples_{index}'),
                                   ('parquet_eav', 'read_parquet({path})')):
                bodies = []
                for index, recording in enumerate(recordings):
                    table = relation.format(index=index, path=literal(paths[index]))
                    bodies.append(eav_select(table, recording, mapping_paths[index]))
                duck.execute(f"create view {name} as " + " union all ".join(bodies))
            duck.execute("checkpoint")
            report["duckdb_view_setup_ms"] = (perf_counter() - view_started) * 1000
            report["duckdb_size_mb"] = duck_path.stat().st_size / 1_000_000
            logical_count = duck.execute("select count(*) from duck_eav").fetchone()[0]
            if logical_count != sum(counts) * config.fields_per_sample:
                raise AssertionError("Query-time field expansion cardinality differs from SQLite")
            report["logical_query_rows"] = logical_count
            report["queries"] = {}
            for engine, table in engines.items():
                print(engine, flush=True)
                timings = {}
                for name, sql in sql_queries(table, ids, config, report["query_limit"]).items():
                    if engine == "sqlite_sql_pushdown":
                        function = lambda sql=sql, name=name: sqlite_call(db_path, sql, name)
                    else:
                        function = lambda sql=sql, name=name: decode_result(duck.execute(sql).fetchall(), name)
                    timings[name] = measure_query(
                        function, lambda actual, name=name: equivalent(actual, golden[name]),
                        runs=args.query_runs, warmups=args.warmups, memory=memory, name=f"{engine}/{name}",
                        strict_digest=name != "compare")
                report["queries"][engine] = timings
            report["status"] = "succeeded"
            duck.close()
            duck = None
            del workspace, calls
        report["memory"] = memory.report()
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                               encoding="utf-8")
        report_path.with_suffix(".md").write_text(poc_markdown(report), encoding="utf-8")
        print(report_path, flush=True)
        return report_path
    except BaseException as exc:
        report.update(status="failed", error={"type": type(exc).__name__, "message": str(exc)})
        report["memory"] = memory.report()
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                               encoding="utf-8")
        report_path.with_suffix(".md").write_text(f"# Failed PoC\n\n{exc}\n", encoding="utf-8")
        raise
    finally:
        if duck is not None:
            duck.close()
        gc.collect()
        if not args.keep_artifacts:
            if work.resolve().parent != (output / ".work").resolve():
                raise RuntimeError("PoC cleanup escaped its working directory")
            shutil.rmtree(work)


def poc_markdown(report: dict) -> str:
    lines = [f"# DuckDB / Parquet PoC: {report['run_id']}", "",
             f"Baseline: `{report['baseline_json']}`; checksum: `{report['source_checksum']}`.",
             "", "| Metric | Value |", "| --- | ---: |",
             f"| SQLite Query Index build (primary, ms) | {report['sqlite_index_build_ms']:.3f} |",
             f"| DuckDB CSV ingest + checkpoint (primary + peer, ms) | {report['duckdb_ingest_ms']:.3f} |",
             f"| Parquet export (primary + peer, ms) | {report['parquet_export_ms']:.3f} |",
             f"| SQLite primary catalog MB | {report['sqlite_primary_size_mb']:.3f} |",
             f"| SQLite primary + peer live catalog MB | {report['sqlite_primary_and_peer_live_size_mb']:.3f} |",
             f"| DuckDB primary + peer MB | {report['duckdb_size_mb']:.3f} |",
             f"| Parquet primary + peer MB | {report['parquet_size_mb']:.3f} |",
             f"| Process sampled peak RSS MB | {report['memory']['peak_rss_mb']:.3f} |", "",
             "## Query latency", "",
             "| Query | Production SQLite P50/P95 | SQL pushdown SQLite P50/P95 | DuckDB table P50/P95 | Parquet P50/P95 (ms) |",
             "| --- | ---: | ---: | ---: | ---: |"]
    for name in report["queries"]["duckdb_table"]:
        queries = [report["sqlite_production_queries"][name]] + [
            report["queries"][engine][name] for engine in (
                "sqlite_sql_pushdown", "duckdb_table", "duckdb_parquet")]
        lines.append(f"| {name} | " + " | ".join(
            f"{query['median_ms']:.3f}/{query['p95_ms']:.3f}" for query in queries) + " |")
    lines += ["", "## Interpretation and limits", "",
              "All PoC results are checked against the production SQLite outputs, including ordering,",
              "types, state durations and two-recording aggregates (floating tolerance 1e-8 absolute).",
              "Each aggregate repeat is compared with the production reference (also relative tolerance",
              "1e-10); parallel floating-point means may have different raw hashes at the last bits.",
              "The input source SHA256 must match the baseline. All mapped sample columns are retained.",
              "SQL pushdown uses the current SQLite EAV data and indexes. DuckDB/Parquet use typed wide",
              "samples and expand fields at query time. Gains combine data layout and query pushdown;",
              "they are not a comparison of identical physical models or engines alone.",
              "SQLite size includes catalog metadata/indexes; DuckDB/Parquet sizes contain sample data and",
              "minimal query views. The peer is bounded; two equally large recordings are not tested.",
              "Ingest stages differ: SQLite reparses, expands, JSON-encodes and inserts rows; DuckDB reads",
              "typed CSV columns. Neither PoC path builds Rerun artifacts or changes production routing.",
              "SQL engines run sequentially in fixed order with warm-ups and a warm filesystem cache.",
              "Production SQLite latency comes from the original baseline; background load may differ.",
              "Peak RSS includes the production correctness reference; inspect per-phase RSS in JSON",
              "before attributing the overall peak to DuckDB. DuckDB memory_limit does not cap all process RSS.",
              "The 1 GB DuckDB limit and configurable thread count apply to this experiment only.",
              "Diagnostics, time_sync, null/mixed schemas, deletion/lifecycle and concurrent writers need",
              "a future compatibility prototype. This PoC is not a QueryStore implementation.", ""]
    return "\n".join(lines)


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--baseline", type=Path, required=True)
    cli.add_argument("--output-dir", type=Path, default=REPO / "benchmarks" / "results")
    cli.add_argument("--query-runs", type=int, default=5)
    cli.add_argument("--warmups", type=int, default=1)
    cli.add_argument("--threads", type=int, default=4)
    cli.add_argument("--keep-artifacts", action="store_true")
    args = cli.parse_args()
    if args.query_runs < 1 or args.warmups < 0 or args.threads < 1:
        cli.error("query-runs >= 1, warmups >= 0 and threads >= 1 required")
    run_poc(args)


if __name__ == "__main__":
    main()
