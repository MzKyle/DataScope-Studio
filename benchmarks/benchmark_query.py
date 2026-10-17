from __future__ import annotations

import hashlib
import json
import math
import statistics
from time import perf_counter
from typing import Callable

from datascope_core.query import QUERY_COLUMNS
from datascope_core.workspace import Workspace

from benchmarks.benchmark_memory import MemorySampler
from benchmarks.benchmark_models import DatasetConfig
from benchmarks.generate_dataset import battery_value, robot_state


def latency_stats(samples: list[float]) -> dict:
    ordered = sorted(samples)
    # Nearest-rank p95, so five measured runs yield the maximum. Retain all raw samples.
    return {"runs": len(samples), "min_ms": min(samples), "mean_ms": statistics.mean(samples),
            "median_ms": statistics.median(samples),
            "p95_ms": ordered[math.ceil(0.95 * len(ordered)) - 1], "max_ms": max(samples),
            "samples_ms": samples, "percentile_method": "nearest-rank"}


def result_digest(result: dict) -> str:
    return hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def measure_query(function: Callable[[], dict], validate: Callable[[dict], None], *,
                  runs: int, warmups: int, memory: MemorySampler, name: str,
                  strict_digest: bool = True) -> dict:
    digest = None
    seen_digests = set()
    count = 0
    samples = []
    with memory.stage(f"query/{name}"):
        for index in range(warmups + runs):
            started = perf_counter()
            result = function()
            elapsed = (perf_counter() - started) * 1000
            # Correctness checks and hashing are deliberately outside the latency interval.
            validate(result)
            current_digest = result_digest(result)
            if strict_digest and digest is not None and current_digest != digest:
                raise AssertionError(f"Non-deterministic query result: {name}")
            seen_digests.add(current_digest)
            digest, count = current_digest, len(result.get("rows", result.get("findings", [])))
            if index >= warmups:
                samples.append(elapsed)
            if not name.startswith("indexes/"):
                phase = f"warm-up {index + 1}" if index < warmups else f"run {index - warmups + 1}/{runs}"
                print(f"      {name} {phase}: {elapsed:.2f} ms", flush=True)
            del result
    summary = {**latency_stats(samples), "warmups": warmups, "result_rows": count,
               "result_sha256": digest, "distinct_result_hashes": len(seen_digests),
               "repeat_check": "exact_sha256" if strict_digest else "validator_each_run"}
    if not name.startswith("indexes/"):
        print(f"    {name}: P50 {summary['median_ms']:.2f} ms, P95 {summary['p95_ms']:.2f} ms", flush=True)
    return summary


def query_calls(workspace: Workspace, project_id: str, recording_ids: list[str],
                config: DatasetConfig, limit: int) -> dict[str, Callable[[], dict]]:
    primary = recording_ids[:1]
    key = "scalar_000" if config.scalar_fields > 10 else "temperature"
    start_index = math.floor(0.9 * (config.rows - 1))
    end_index = min(config.rows - 1, start_index + 10)
    calls = {template: (lambda template=template: workspace.run_query(
        project_id, template, primary, limit=limit)) for template in (
        "find_errors", "low_battery", "state_duration", "time_sync")}
    calls.update({
        "custom_scalar_key": lambda: workspace.custom_query(
            project_id, {"key": key}, primary, ["scalar", "scalar_group"], limit),
        "custom_time_range": lambda: workspace.custom_query(
            project_id, {"time_start": start_index / config.frequency_hz,
                         "time_end": end_index / config.frequency_hz}, primary, limit=limit),
        "custom_numeric_threshold": lambda: workspace.custom_query(
            project_id, {"key": "battery", "operator": "lt", "value": 0.1}, primary,
            ["scalar", "scalar_group"], limit),
        "compare": lambda: workspace.compare(
            project_id, recording_ids, ["battery", "temperature"], limit=limit),
    })
    return calls


def validate_query(result: dict, name: str, config: DatasetConfig, limit: int,
                   recording_ids: list[str], peer_rows: int) -> None:
    if result.get("columns") != QUERY_COLUMNS or not isinstance(result.get("rows"), list):
        raise AssertionError(f"Invalid query shape: {name}")
    rows = result["rows"]
    if len(rows) > limit:
        raise AssertionError(f"Query exceeded limit: {name}")
    if name == "time_sync":
        # CSV has no topic_summary rows. An empty result is the correct production behavior.
        if rows:
            raise AssertionError("CSV time_sync should be empty")
        return
    if not rows:
        raise AssertionError(f"Expected nonempty result: {name}")
    for row in rows:
        if set(row) != set(QUERY_COLUMNS) or row["recording_id"] not in recording_ids:
            raise AssertionError(f"Invalid result row: {name}")
        if name == "compare":
            count = config.rows if row["recording_id"] == recording_ids[0] else peer_rows
            if row["value"]["count"] != count:
                raise AssertionError("Compare must aggregate every source sample")
            if row["key"] == "battery" and not math.isclose(row["value"]["mean"], 0.5, abs_tol=1e-6):
                raise AssertionError("Incorrect battery aggregate")
            continue
        index = round(row["time"] * config.frequency_hz)
        if not 0 <= index < config.rows:
            raise AssertionError("Query timestamp outside recording")
        if name == "find_errors" and row["value"] != robot_state(index, config.rows):
            raise AssertionError("Unexpected error state")
        if name == "find_errors" and row["value"] not in {"error", "warning"}:
            raise AssertionError("find_errors returned a normal state")
        if name in {"low_battery", "custom_numeric_threshold"}:
            threshold = 0.2 if name == "low_battery" else 0.1
            if row["key"] != "battery" or not math.isclose(
                row["value"], battery_value(index, config.rows), abs_tol=1e-9
            ) or row["value"] >= threshold:
                raise AssertionError("Battery threshold query returned an incorrect value")
        if name == "state_duration":
            expected_duration = 0.0 if index == config.rows - 1 else 1 / config.frequency_hz
            if not math.isclose(row["value"]["duration"], expected_duration, abs_tol=1e-8):
                raise AssertionError("Incorrect adjacent state duration")
            if row["key"] == "robot_state":
                expected_state = robot_state(index, config.rows)
            else:
                field = int(row["key"].removeprefix("state_"))
                expected_state = "active" if int((index / config.frequency_hz) / (5 + field)) % 2 else "standby"
            if row["value"]["state"] != expected_state:
                raise AssertionError("Incorrect state-duration state value")
        if name == "custom_scalar_key":
            key = "scalar_000" if config.scalar_fields > 10 else "temperature"
            if row["key"] != key or not isinstance(row["value"], (int, float)):
                raise AssertionError("Scalar-key filter returned a different field")
        if name == "custom_time_range":
            start = math.floor(0.9 * (config.rows - 1))
            if not start <= index <= min(config.rows - 1, start + 10):
                raise AssertionError("Time-range query returned an out-of-range row")
    if name == "compare" and len(rows) != 2 * len(recording_ids):
        raise AssertionError("Compare must return both metrics for both recordings")
    if name == "state_duration" and len(rows) != min(limit, config.rows * config.state_fields):
        raise AssertionError("State-duration cardinality is incorrect")
    if name == "find_errors":
        warning_start = math.ceil(0.85 * (config.rows - 1))
        expected_count = config.rows - warning_start + (warning_start - 1) // 9973
        if len(rows) != min(limit, expected_count):
            raise AssertionError("Error-query cardinality is incorrect")
    if name in {"low_battery", "custom_numeric_threshold"}:
        threshold = 0.2 if name == "low_battery" else 0.1
        first_hit = math.floor((0.95 - threshold) / 0.9 * (config.rows - 1)) + 1
        while first_hit < config.rows and battery_value(first_hit, config.rows) >= threshold:
            first_hit += 1
        while first_hit > 0 and battery_value(first_hit - 1, config.rows) < threshold:
            first_hit -= 1
        if len(rows) != min(limit, config.rows - first_hit):
            raise AssertionError("Battery-query cardinality is incorrect")
    if name == "custom_scalar_key" and len(rows) != min(limit, config.rows):
        raise AssertionError("Scalar query cardinality is incorrect")
    if name == "custom_time_range":
        start = math.floor(0.9 * (config.rows - 1))
        end = min(config.rows - 1, start + 10)
        if len(rows) != min(limit, (end - start + 1) * config.fields_per_sample):
            raise AssertionError("Time-range query cardinality is incorrect")


def run_queries(workspace: Workspace, project_id: str, recording_ids: list[str],
                config: DatasetConfig, peer_rows: int, memory: MemorySampler, *,
                runs: int = 5, warmups: int = 1, limit: int = 1000,
                diagnostics: bool = True, compare_all: bool = False) -> dict:
    queries = {}
    for name, function in query_calls(workspace, project_id, recording_ids, config, limit).items():
        print(f"  query {name} ({warmups} warm-up + {runs} measured)", flush=True)
        queries[name] = measure_query(
            function, lambda result, name=name: validate_query(
                result, name, config, limit, recording_ids, peer_rows),
            runs=runs, warmups=warmups, memory=memory, name=name,
        )
    queries["time_sync"]["coverage"] = "empty CSV path; no topic summaries, not a sensor-sync workload"
    queries["compare"]["metric_keys"] = ["battery", "temperature"]
    queries["compare"]["recording_source_rows"] = [config.rows, peer_rows]
    if compare_all:
        queries["compare_all"] = measure_query(
            lambda: workspace.compare(project_id, recording_ids, limit=limit),
            lambda result: _validate_compare_all(result, config, recording_ids, peer_rows, limit),
            runs=runs, warmups=warmups, memory=memory, name="compare_all",
        )
    if diagnostics:
        print("  query diagnostics", flush=True)
        queries["diagnostics"] = measure_query(
            lambda: workspace.run_diagnostics(project_id, recording_ids[:1], limit=limit),
            lambda result: _validate_diagnostics(result, config),
            runs=runs, warmups=warmups, memory=memory, name="diagnostics",
        )
    return queries


def _validate_diagnostics(result: dict, config: DatasetConfig) -> None:
    if result["summary"]["recording_count"] != 1 or not isinstance(result["findings"], list):
        raise AssertionError("Invalid diagnostics report")
    checks = {check["id"]: check for check in result["checks"]}
    if "data_quality" not in checks:
        raise AssertionError("Missing data-quality diagnostics")
    if checks["data_quality"]["evidence"]["query_row_count"] != config.rows * config.fields_per_sample:
        raise AssertionError("Diagnostics did not consume the complete Query Index")


def _validate_compare_all(result: dict, config: DatasetConfig, recording_ids: list[str],
                          peer_rows: int, limit: int) -> None:
    if result["columns"] != QUERY_COLUMNS or len(result["rows"]) != min(
        limit, len(recording_ids) * config.fields_per_sample
    ):
        raise AssertionError("Incorrect full-field compare cardinality")
    for row in result["rows"]:
        expected = config.rows if row["recording_id"] == recording_ids[0] else peer_rows
        if row["value"]["count"] != expected:
            raise AssertionError("Incorrect full-field compare aggregation")
