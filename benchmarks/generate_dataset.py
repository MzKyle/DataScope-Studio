from __future__ import annotations

import argparse
import csv
import math
import random
import sys
import time
from pathlib import Path
from typing import Iterator

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.benchmark_models import DatasetConfig, add_dataset_arguments, config_from_args


BASE_SCALARS = [
    "position_x", "position_y", "position_z", "velocity_x", "velocity_y", "velocity_z",
    "temperature", "battery", "current", "voltage",
]


def scalar_names(config: DatasetConfig) -> list[str]:
    return BASE_SCALARS + [f"scalar_{index:03d}" for index in range(config.scalar_fields - 10)]


def state_names(config: DatasetConfig) -> list[str]:
    return ["robot_state"] + [f"state_{index:03d}" for index in range(config.state_fields - 1)]


def robot_state(index: int, rows: int) -> str:
    # A rare fault at the end guarantees an error even for a two-row self-check.
    if index == rows - 1 or (index > 0 and index % 9973 == 0):
        return "error"
    if index >= math.ceil(0.85 * (rows - 1)):
        return "warning"
    return "idle" if index < math.ceil(0.1 * (rows - 1)) else "running"


def battery_value(index: int, rows: int) -> float:
    return round(0.95 - 0.9 * index / (rows - 1), 6)


def iter_samples(config: DatasetConfig) -> Iterator[list[str | int]]:
    rng = random.Random(config.seed)
    extra = config.scalar_fields - 10
    for index in range(config.rows):
        t = index / config.frequency_hz
        phase = t * 0.2
        scalars = [
            2 * math.sin(phase), 2 * math.cos(phase), 0.2 * math.sin(phase / 2),
            0.4 * math.cos(phase), -0.4 * math.sin(phase), 0.02 * math.cos(phase / 2),
            35 + 2 * math.sin(t / 180) + rng.uniform(-0.05, 0.05),
            battery_value(index, config.rows),
            3 + 0.5 * math.sin(phase), 24 - 0.4 * index / (config.rows - 1),
        ]
        scalars.extend(
            10 + field * 0.1 + math.sin(t * (0.02 + field * 0.001) + field)
            for field in range(extra)
        )
        state = robot_state(index, config.rows)
        states = [state] + [
            "active" if (int(t / (5 + field)) % 2) else "standby"
            for field in range(config.state_fields - 1)
        ]
        yield [format(t, ".9f"), *[format(value, ".6f") for value in scalars],
               *states, 42 if state == "error" else 0]


def generate_dataset(config: DatasetConfig, output: Path) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    # Refuse to overwrite user data, including when the standalone CLI is used.
    with output.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["timestamp", *scalar_names(config), *state_names(config), "error_code"])
        writer.writerows(iter_samples(config))
    return {
        **config.report(),
        "generation_ms": (time.perf_counter() - started) * 1000,
        "source_size_bytes": output.stat().st_size,
        "source_size_mb": output.stat().st_size / 1_000_000,
        "source_path": str(output.resolve()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic robot telemetry CSV")
    add_dataset_arguments(parser)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        config = config_from_args(args)
    except ValueError as exc:
        parser.error(str(exc))
    import json
    print(json.dumps(generate_dataset(config, args.output), indent=2))


if __name__ == "__main__":
    main()
