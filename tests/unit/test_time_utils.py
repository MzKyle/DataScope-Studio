from datetime import timezone

import pandas as pd

from datascope_core.rerun_writer import _set_row_time
from datascope_core.time_utils import normalize_time_value, query_time_seconds


def test_unix_millisecond_timestamp_is_absolute_time() -> None:
    normalized = normalize_time_value(1780523938361)

    assert normalized is not None
    assert normalized.kind == "timestamp"
    assert normalized.unit == "unix_ms"
    assert normalized.timestamp is not None
    assert normalized.timestamp.tzinfo == timezone.utc
    assert normalized.timestamp.isoformat() == "2026-06-03T21:58:58.361000+00:00"
    assert query_time_seconds(1780523938361, 99) == normalized.seconds


def test_numeric_time_unit_detection() -> None:
    assert normalize_time_value(1780523938).unit == "unix_s"
    assert normalize_time_value(1780523938361000).unit == "unix_us"
    assert normalize_time_value(1780523938361000000).unit == "unix_ns"

    relative = normalize_time_value(0.25)
    assert relative is not None
    assert relative.kind == "duration"
    assert relative.seconds == 0.25


def test_invalid_or_empty_time_falls_back_to_row_index() -> None:
    assert normalize_time_value(float("nan")) is None
    assert query_time_seconds("not-a-time", 7) == 7.0


def test_set_row_time_uses_timestamp_for_large_unix_values() -> None:
    rec = FakeRecording()
    row = pd.Series({"timestamp": 1780523938361})

    _set_row_time(
        rec,
        row,
        0,
        [{"time_key": "timestamp", "timeline_source_field": "timestamp"}],
    )

    assert rec.calls[0][0] == "time"
    assert rec.calls[0][1]["timestamp"].isoformat() == "2026-06-03T21:58:58.361000+00:00"
    assert "duration" not in rec.calls[0][1]


class FakeRecording:
    def __init__(self) -> None:
        self.calls = []

    def set_time(self, timeline: str, **kwargs) -> None:
        self.calls.append((timeline, kwargs))
