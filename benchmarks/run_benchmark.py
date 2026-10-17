from __future__ import annotations

import argparse
import gc
import json
import shutil
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(REPO))

from benchmarks.benchmark_models import MATRIX, add_dataset_arguments, config_from_args
from benchmarks.generate_dataset import generate_dataset


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Opt-in DataScope Query Index benchmark")
    add_dataset_arguments(result, presets=True)
    result.add_argument("--output-dir", type=Path, default=REPO / "benchmarks" / "results")
    result.add_argument("--keep-dataset", action="store_true")
    result.add_argument("--keep-workspace", action="store_true")
    result.add_argument("--query-runs", type=int, default=5)
    result.add_argument("--warmups", type=int, default=1)
    result.add_argument("--query-limit", type=int, default=1000)
    result.add_argument("--skip-diagnostics", action="store_true")
    result.add_argument("--compare-all", action="store_true")
    result.add_argument("--skip-index-comparison", action="store_true")
    result.add_argument("--index-samples", type=int, default=10_000)
    result.add_argument("--pipeline", choices=("full", "index-only"), default="full")
    result.add_argument("--matrix", action="store_true", help="run A/B/C/D in fresh sequential processes")
    result.add_argument("--matrix-duration", type=float, default=60)
    result.add_argument("--label", default="run")
    return result


def run_one(args: argparse.Namespace) -> Path:
    from benchmarks.benchmark_indexes import benchmark_indexes, explain_query
    from benchmarks.benchmark_memory import MemorySampler
    from benchmarks.benchmark_pipeline import BenchmarkWorkspace, run_pipeline
    from benchmarks.benchmark_query import run_queries
    from benchmarks.benchmark_report import environment, markdown_summary
    from benchmarks.benchmark_time_sync import benchmark_time_sync

    config = config_from_args(args)
    started_at = datetime.now(timezone.utc)
    # Filenames use UTC for reproducibility on any host; reports record the offset explicitly.
    safe_label = "".join(char for char in args.label if char.isalnum() or char in "-_") or "run"
    run_id = f"benchmark_{started_at:%Y%m%d_%H%M%S}_{safe_label}_{uuid4().hex[:8]}"
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    run_environment = environment(REPO)
    work = output / ".work" / run_id
    work.mkdir(parents=True, exist_ok=False)
    dataset, workspace_path = work / "robot.csv", work / "workspace"
    report = {"format_version": 1, "run_id": run_id, "started_at": started_at.isoformat(),
              "mode": args.pipeline, "status": "running", "environment": run_environment,
              "settings": {"query_runs": args.query_runs, "warmups": args.warmups,
                           "query_limit": args.query_limit, "index_samples": args.index_samples,
                           "diagnostics": not args.skip_diagnostics, "compare_all": args.compare_all},
              "artifacts": {"dataset": str(dataset) if args.keep_dataset else None,
                            "workspace": str(workspace_path) if args.keep_workspace else None}}
    json_path = output / f"{run_id}.json"
    memory = MemorySampler()
    try:
        with memory:
            print(f"{run_id}: {config.rows:,} samples, {config.frequency_hz:g} Hz, "
                  f"{config.scalar_fields} scalars + error_code + {config.state_fields} states", flush=True)
            with memory.stage("dataset_generation"):
                report["dataset"] = generate_dataset(config, dataset)
            workspace = BenchmarkWorkspace(workspace_path)
            print("  primary pipeline", flush=True)
            primary = run_pipeline(workspace, config, dataset, memory, mode=args.pipeline)
            report.update({key: primary[key] for key in ("pipeline", "storage", "source_checksum")})
            print(f"    {primary['storage']['query_rows']:,} query rows; "
                  f"SQLite {primary['storage']['sqlite_size_mb']:.1f} MB; "
                  f"storage amplification {primary['storage']['storage_amplification_ratio']:.2f}x", flush=True)
            json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                                 encoding="utf-8")
            report["query_plans"] = {
                name: explain_query(workspace, primary["project_id"],
                                    primary["recording"]["recording_id"], name)
                for name in ("find_errors", "low_battery", "state_duration", "time_sync",
                             "custom_scalar_key", "custom_time_range", "custom_numeric_threshold")}
            # A bounded real second recording avoids doubling every GB-scale source/artifact.
            peer_config = replace(config, rows=min(config.rows, 1000))
            peer_path = work / "peer.csv"
            peer_dataset = generate_dataset(peer_config, peer_path)
            print("  bounded comparison peer", flush=True)
            peer = run_pipeline(workspace, peer_config, peer_path, memory, mode=args.pipeline,
                                label="peer", project_id=primary["project_id"])
            report["peer"] = {"dataset": peer_dataset, "pipeline": peer["pipeline"],
                              "storage": peer["storage"]}
            report["queries"] = run_queries(
                workspace, primary["project_id"],
                [primary["recording"]["recording_id"], peer["recording"]["recording_id"]],
                config, peer_config.rows, memory, runs=args.query_runs, warmups=args.warmups,
                limit=args.query_limit, diagnostics=not args.skip_diagnostics,
                compare_all=args.compare_all)
            report["time_sync_fixture"] = benchmark_time_sync(
                workspace, primary["project_id"], work, memory, runs=args.query_runs,
                warmups=args.warmups, limit=args.query_limit)
            report["queries"]["time_sync_csv"] = report["queries"].pop("time_sync")
            report["queries"]["time_sync"] = report["time_sync_fixture"]["query"]
            if not args.skip_index_comparison:
                report["index_comparison"] = benchmark_indexes(
                    workspace, primary, config, work / "indexes", memory,
                    runs=args.query_runs, warmups=args.warmups,
                    limit=args.query_limit, max_samples=args.index_samples)
            report["status"] = "succeeded"
            del workspace
        report["memory"] = memory.report()
        json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                             encoding="utf-8")
        md_path = json_path.with_suffix(".md")
        md_path.write_text(markdown_summary(report), encoding="utf-8")
        print(f"  JSON: {json_path}\n  Markdown: {md_path}", flush=True)
        return json_path
    except BaseException as exc:
        report["status"] = "failed"
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        report["memory"] = memory.report()
        json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                             encoding="utf-8")
        json_path.with_suffix(".md").write_text(
            f"# Failed benchmark: {run_id}\n\n{type(exc).__name__}: {exc}\n"
            "\nPartial measurements are in JSON; this run is not decision evidence.\n", encoding="utf-8")
        raise
    finally:
        gc.collect()
        # Only delete paths within the unique directory created by this invocation.
        if work.resolve().parent != (output / ".work").resolve():
            raise RuntimeError("Cleanup escaped the benchmark directory")
        for target in (workspace_path, work / "indexes"):
            if not target.resolve().is_relative_to(work.resolve()):
                raise RuntimeError(f"Cleanup target escaped the benchmark directory: {target}")
        if not args.keep_workspace and workspace_path.exists():
            shutil.rmtree(workspace_path)
        if not args.keep_dataset:
            dataset.unlink(missing_ok=True)
        for extra in (work / "peer.csv", work / "topic_ranges.mcap"):
            extra.unlink(missing_ok=True)
        if (work / "indexes").exists():
            shutil.rmtree(work / "indexes")
        if not args.keep_dataset and not args.keep_workspace:
            work.rmdir()


def main() -> None:
    cli = parser()
    args = cli.parse_args()
    try:
        config_from_args(args)
        if args.query_runs < 1 or args.warmups < 0 or args.query_limit < 4 or args.index_samples < 2:
            raise ValueError("query-runs >= 1, warmups >= 0, query-limit >= 4, index-samples >= 2 required")
        if args.matrix and (args.rows is not None or args.duration is not None):
            raise ValueError("--matrix uses --matrix-duration; omit --rows/--duration")
    except ValueError as exc:
        cli.error(str(exc))
    if args.matrix:
        for name, (frequency, scalars) in MATRIX.items():
            command = [sys.executable, str(Path(__file__).resolve()), "--frequency", str(frequency),
                       "--scalar-fields", str(scalars), "--duration", str(args.matrix_duration),
                       "--state-fields", str(args.state_fields), "--seed", str(args.seed),
                       "--query-runs", str(args.query_runs), "--warmups", str(args.warmups),
                       "--query-limit", str(args.query_limit), "--index-samples", str(args.index_samples),
                       "--pipeline", args.pipeline, "--output-dir", str(args.output_dir),
                       "--label", f"{args.label}_case_{name}"]
            for option in ("keep_dataset", "keep_workspace", "skip_diagnostics", "compare_all",
                           "skip_index_comparison"):
                if getattr(args, option):
                    command.append("--" + option.replace("_", "-"))
            subprocess.run(command, check=True)
    else:
        run_one(args)


if __name__ == "__main__":
    main()
