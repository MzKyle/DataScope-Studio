from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

import pandas as pd


TimeKind = Literal["duration", "timestamp"]
TIME_UNITS = {"auto", "seconds", "relative_s", "unix_s", "unix_ms", "unix_us", "unix_ns", "datetime"}


@dataclass(frozen=True)
class NormalizedTime:
    kind: TimeKind
    seconds: float
    timestamp: datetime | None = None
    unit: str = "seconds"


def normalize_time_value(value: Any, unit: str = "auto") -> NormalizedTime | None:
    """Normalize a scalar timeline value for Rerun and query indexing.

    Small numeric values are treated as relative seconds. Large numeric values
    are treated as Unix epoch timestamps and scaled by their apparent unit.
    """
    if _is_missing(value):
        return None

    if unit not in TIME_UNITS:
        raise ValueError(f"Unsupported time unit: {unit}")

    if unit == "datetime":
        return _parse_datetime(value)

    numeric = _coerce_numeric(value)
    if numeric is not None:
        if unit in {"seconds", "relative_s"}:
            return NormalizedTime(kind="duration", seconds=numeric, unit="relative_s")
        if unit == "unix_s":
            return _epoch_time(numeric, unit)
        if unit == "unix_ms":
            return _epoch_time(numeric / 1_000, unit)
        if unit == "unix_us":
            return _epoch_time(numeric / 1_000_000, unit)
        if unit == "unix_ns":
            return _epoch_time(numeric / 1_000_000_000, unit)
        return _normalize_numeric_time(numeric)

    return _parse_datetime(value)


def infer_time_unit(values: Any) -> str | None:
    series = pd.Series(values).dropna()
    if series.empty:
        return None
    units = {
        normalized.unit
        for value in series.head(1000)
        if (normalized := normalize_time_value(value)) is not None
    }
    if not units:
        return None
    if len(units) == 1:
        return next(iter(units))
    return "mixed"


def time_seconds_or_none(value: Any, unit: str = "auto") -> float | None:
    normalized = normalize_time_value(value, unit=unit)
    return normalized.seconds if normalized is not None else None


def _parse_datetime(value: Any) -> NormalizedTime | None:
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.notna(parsed):
        timestamp = parsed.to_pydatetime()
        return NormalizedTime(
            kind="timestamp",
            seconds=timestamp.timestamp(),
            timestamp=timestamp,
            unit="datetime",
        )
    return None


def query_time_seconds(value: Any, row_index: int, unit: str = "auto") -> float:
    normalized = normalize_time_value(value, unit=unit)
    if normalized is None:
        return float(row_index)
    return normalized.seconds


def _normalize_numeric_time(value: float) -> NormalizedTime | None:
    magnitude = abs(value)
    if magnitude >= 1_000_000_000_000_000_000:
        return _epoch_time(value / 1_000_000_000, "unix_ns")
    if magnitude >= 1_000_000_000_000_000:
        return _epoch_time(value / 1_000_000, "unix_us")
    if magnitude >= 1_000_000_000_000:
        return _epoch_time(value / 1_000, "unix_ms")
    if magnitude >= 1_000_000_000:
        return _epoch_time(value, "unix_s")
    return NormalizedTime(kind="duration", seconds=float(value), unit="seconds")


def _epoch_time(seconds: float, unit: str) -> NormalizedTime | None:
    try:
        timestamp = datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return NormalizedTime(
        kind="timestamp",
        seconds=float(seconds),
        timestamp=timestamp,
        unit=unit,
    )


def _coerce_numeric(value: Any) -> float | None:
    try:
        numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    except Exception:
        return None
    if pd.isna(numeric):
        return None
    try:
        as_float = float(numeric)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(as_float):
        return None
    return as_float


def _is_missing(value: Any) -> bool:
    try:
        missing = pd.isna(value)
    except Exception:
        return False
    try:
        return bool(missing)
    except ValueError:
        return False
