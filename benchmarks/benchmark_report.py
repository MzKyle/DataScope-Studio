from __future__ import annotations

import hashlib
import importlib.metadata
import platform
import sqlite3
import subprocess
import sys
from pathlib import Path

import psutil


def environment(repo: Path) -> dict:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()
    versions = {}
    for name in ("datascope-core", "pandas", "numpy", "rerun-sdk", "psutil", "pyarrow"):
        versions[name] = importlib.metadata.version(name)
    digest = hashlib.sha256()
    for path in sorted((repo / "benchmarks").glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    cpu = platform.processor()
    if sys.platform == "win32":
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            cpu = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    elif Path("/proc/cpuinfo").is_file():
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    return {
        "platform": platform.platform(), "python": sys.version, "cpu": cpu,
        "logical_cpus": psutil.cpu_count(), "physical_cpus": psutil.cpu_count(logical=False),
        "memory_gb": psutil.virtual_memory().total / 1_000_000_000,
        "available_memory_gb_at_start": psutil.virtual_memory().available / 1_000_000_000,
        "datascope_version": versions["datascope-core"], "git_commit": git("rev-parse", "HEAD"),
        "git_dirty": bool(git("status", "--porcelain")), "benchmark_code_sha256": digest.hexdigest(),
        "packages": versions, "sqlite_version": sqlite3.sqlite_version,
    }


def markdown_summary(report: dict) -> str:
    def number(value: object) -> str:
        return "not measured" if value is None else f"{value:,.3f}"
    dataset, storage, pipeline = report["dataset"], report["storage"], report["pipeline"]
    lines = [f"# Query storage benchmark: {report['run_id']}", "",
             f"Date: {report['started_at']}. Mode: **{report['mode']}**. Status: {report['status']}.",
             "", "## Environment", "",
             f"- Platform: {report['environment']['platform']}",
             f"- CPU: {report['environment']['cpu']}",
             f"- Python: {report['environment']['python']}",
             f"- RAM: {number(report['environment']['memory_gb'])} GB",
             f"- Commit: `{report['environment']['git_commit']}`; dirty: {report['environment']['git_dirty']}",
             f"- Benchmark code SHA256: `{report['environment']['benchmark_code_sha256']}`", "",
             "## Dataset and storage", "", "| Metric | Value |", "| --- | ---: |"]
    for name, value in (
        ("Source rows", dataset["rows"]), ("Frequency (Hz)", dataset["frequency_hz"]),
        ("Duration (s)", dataset["duration_seconds"]),
        ("Telemetry scalars / states", f"{dataset['scalar_fields']} / {dataset['state_fields']}"),
        ("Primary query rows", storage["query_rows"]),
        ("Row amplification", storage["row_amplification_ratio"]),
        ("Source size (MB)", dataset["source_size_mb"]),
        ("SQLite size before peer (MB)", storage["sqlite_size_mb"]),
        ("Storage amplification", storage["storage_amplification_ratio"]),
        ("RRD size (MB)", storage["rrd_size_mb"]), ("RBL size (MB)", storage["rbl_size_mb"]),
        ("Sampled peak RSS (MB)", report["memory"]["peak_rss_mb"]),
        ("OS lifetime peak RSS (MB)", report["memory"]["os_peak_rss_mb"]),
        ("RSS before / after (MB)", f"{number(report['memory']['rss_before_mb'])} / "
         f"{number(report['memory']['rss_after_mb'])}"),
    ):
        lines.append(f"| {name} | {number(value) if isinstance(value, (int, float)) or value is None else value} |")
    lines += ["", "The SQLite/source ratio includes metadata and three indexes for the primary recording;",
              "it is measured before adding the bounded comparison peer. MB/GB use decimal units.",
              "`scalar_fields` includes the ten base telemetry fields, excludes numeric `error_code`.",
              "", "## Pipeline", "", "| Stage | ms |", "| --- | ---: |",
              f"| Dataset generation | {number(dataset['generation_ms'])} |"]
    for name, value in pipeline.items():
        lines.append(f"| {name} | {number(value)} |")
    lines += ["", "`inspect_ms` excludes the nested schema-profile call; `inspect_total_ms` includes it.",
              "`query_insert_ms` times executemany only; `query_index_ms` also includes CSV parsing,",
              "row expansion, JSON serialization, delete and transaction commit.",
              "", "## Query performance", "",
              "| Query | Result rows | min | mean | P50 | P95 | max (ms) |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name, query in report["queries"].items():
        values = [number(query[key]) for key in ("min_ms", "mean_ms", "median_ms", "p95_ms", "max_ms")]
        lines.append(f"| {name} | {query['result_rows']} | {' | '.join(values)} |")
    lines += ["", f"Warm-ups: {report['settings']['warmups']}; measured repetitions: "
              f"{report['settings']['query_runs']}; result limit: {report['settings']['query_limit']}.",
              "P95 uses nearest rank; with five runs it is the maximum, not a robust tail estimate.",
              "Query timing includes production SQLite reads/sorts and Python processing; validation is excluded.",
              "time_sync uses two real inspected MCAP topics (four metadata query rows); no auxiliary RRD build.",
              "Current MCAP inspection supplies shared file-wide ranges, so the generated 20 ms topic offset",
              "produces zero reported deltas. This is metadata-query latency, not sensor-sync accuracy.",
              "time_sync_csv is the expected empty CSV path. Neither measures synchronization of scalar samples.",
              f"Compare uses battery/temperature across {report['dataset']['rows']} + "
              f"{report['peer']['dataset']['rows']} source samples.",
              "Queries run after ingestion and warm-up with a warm OS cache; no cold-cache claim.",
              "", "## Memory by phase", "",
              "| Phase | RSS before | RSS after | Sampled peak (MB) |", "| --- | ---: | ---: | ---: |"]
    for name, stage in report["memory"]["stages"].items():
        lines.append(f"| {name} | {number(stage['rss_before_mb'])} | {number(stage['rss_after_mb'])} | "
                     f"{number(stage['peak_rss_mb'])} |")
    if report.get("index_comparison"):
        experiment = report["index_comparison"]
        lines += ["", "## Isolated index experiment", "",
                  f"Same {experiment['source_samples']:,} complete first/last source samples "
                  f"({experiment['query_rows']:,} query rows) replayed into each fresh catalog.",
                  "INSERT SELECT excludes parsing; this is separate from the end-to-end index build.",
                  "One insert trial per variant; query min/mean/P50/P95/max and EXPLAIN plans are in JSON.",
                  "", "| Index set | INSERT ms | SQLite MB | low_battery P95 ms | custom range P95 ms |",
                  "| --- | ---: | ---: | ---: | ---: |"]
        for name, variant in experiment["variants"].items():
            lines.append(f"| {name} | {number(variant['insert_ms'])} | {number(variant['sqlite_size_mb'])} | "
                         f"{number(variant['queries']['low_battery']['p95_ms'])} | "
                         f"{number(variant['queries']['custom_time_range']['p95_ms'])} |")
        builds = experiment["variants"]["none"]["deferred_index_build_ms"]
        lines += ["", "Deferred index construction after unindexed INSERT:"]
        lines.extend(f"- `{name}`: {number(value)} ms" for name, value in builds.items())
    lines += ["", "## Correctness and retained artifacts", "",
              "Exact primary/peer index cardinalities, recording success and nonempty artifacts (full mode),",
              "error/state/battery values, adjacent durations, numeric/key/time filters, compare aggregates",
              "and stable result hashes are checked. Isolated index variants must return identical results.",
              "", f"- Retained dataset: {report['artifacts'].get('dataset') or 'none'}",
              f"- Retained workspace: {report['artifacts'].get('workspace') or 'none'}", ""]
    return "\n".join(lines)
