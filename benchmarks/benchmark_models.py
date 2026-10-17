from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any


# Approximate CSV sizes at 30 telemetry scalars, not guaranteed byte targets.
PRESETS = {"smoke": 30_000, "small": 300_000, "medium": 3_000_000, "large": 12_000_000}
MATRIX = {"A": (50, 10), "B": (200, 30), "C": (1000, 30), "D": (200, 100)}


@dataclass(frozen=True)
class DatasetConfig:
    rows: int = PRESETS["smoke"]
    frequency_hz: float = 200.0
    scalar_fields: int = 30
    state_fields: int = 1
    seed: int = 20261006

    def __post_init__(self) -> None:
        if self.rows < 2:
            raise ValueError("rows must be >= 2 (adjacent states and anomaly checks)")
        if not math.isfinite(self.frequency_hz) or self.frequency_hz <= 0:
            raise ValueError("frequency must be finite and > 0")
        if self.scalar_fields < 10:
            raise ValueError("scalar-fields must be >= 10 to retain the base telemetry fields")
        if self.state_fields < 1:
            raise ValueError("state-fields must be >= 1 to retain robot_state")

    @property
    def duration_seconds(self) -> float:
        return self.rows / self.frequency_hz

    @property
    def last_timestamp(self) -> float:
        return (self.rows - 1) / self.frequency_hz

    @property
    def fields_per_sample(self) -> int:
        # error_code is numeric, separate from the requested telemetry scalar count.
        return self.scalar_fields + self.state_fields + 1

    def report(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "duration_seconds": self.duration_seconds,
            "last_timestamp_seconds": self.last_timestamp,
            "total_columns": self.fields_per_sample + 1,
            "expected_query_rows": self.rows * self.fields_per_sample,
        }


def add_dataset_arguments(parser: Any, *, presets: bool = False) -> None:
    if presets:
        parser.add_argument("--preset", choices=PRESETS, default="smoke")
    size = parser.add_mutually_exclusive_group()
    size.add_argument("--rows", type=int)
    size.add_argument("--duration", type=float, help="seconds; rows = floor(frequency * duration)")
    parser.add_argument("--frequency", type=float, default=200.0)
    parser.add_argument("--scalar-fields", type=int, default=30,
                        help="total telemetry scalars, including the ten base fields; excludes error_code")
    parser.add_argument("--state-fields", type=int, default=1, help="includes robot_state")
    parser.add_argument("--seed", type=int, default=20261006)


def config_from_args(args: Any) -> DatasetConfig:
    rows = args.rows
    if args.duration is not None:
        if not math.isfinite(args.duration) or args.duration <= 0:
            raise ValueError("duration must be finite and > 0")
        if not math.isfinite(args.frequency) or args.frequency <= 0:
            raise ValueError("frequency must be finite and > 0")
        rows = math.floor(args.frequency * args.duration)
    if rows is None:
        rows = PRESETS[getattr(args, "preset", "smoke")]
    return DatasetConfig(rows, args.frequency, args.scalar_fields, args.state_fields, args.seed)
