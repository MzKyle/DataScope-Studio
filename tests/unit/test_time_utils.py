from datetime import timezone

import pandas as pd

from datascope_core.models import MappingSpec, SourceInfo
from datascope_core.query import build_query_rows
from datascope_core.rerun_writer import _set_row_time
from datascope_core.time_utils import (
    normalize_time_value,
    prepare_tabular_frame,
    query_time_seconds,
)


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

    assert rec.calls[0] == ("row", {"sequence": 0})
    assert rec.calls[1][0] == "time"
    assert rec.calls[1][1]["timestamp"].isoformat() == "2026-06-03T21:58:58.361000+00:00"
    assert "duration" not in rec.calls[1][1]


def test_prepare_tabular_frame_stably_sorts_invalid_times_last() -> None:
    frame = pd.DataFrame(
        {
            "time": [2, None, 1, "bad", 1],
            "value": ["later", "empty", "first", "invalid", "second"],
        }
    )

    sorted_frame = prepare_tabular_frame(
        frame,
        time_key="time",
        time_unit="relative_s",
        timeline_sort="ascending",
    )

    assert sorted_frame["value"].tolist() == [
        "first",
        "second",
        "later",
        "empty",
        "invalid",
    ]
    assert sorted_frame.index.tolist() == [0, 1, 2, 3, 4]


def test_query_index_uses_the_same_time_sort_as_conversion(tmp_path) -> None:
    path = tmp_path / "sorted.csv"
    path.write_text("time,value\n2,20\n1,10\n", encoding="utf-8")
    source = SourceInfo(source_id="source_sorted", source_type="csv", path=str(path))
    spec = MappingSpec(
        mapping_id="mapping_sorted",
        source_id=source.source_id,
        app_id="app",
        recording_id="recording",
        primary_timeline="time",
        timeline_unit="relative_s",
        timeline_sort="ascending",
        streams=[
            {
                "stream_id": "value",
                "source_fields": ["value"],
                "semantic_type": "scalar",
                "entity_path": "/metrics/value",
                "enabled": True,
            }
        ],
    )

    rows = build_query_rows("recording", source, spec)

    assert [row.time for row in rows] == [1.0, 2.0]
    assert [row.value for row in rows] == [10, 20]


class FakeRecording:
    def __init__(self) -> None:
        self.calls = []

    def set_time(self, timeline: str, **kwargs) -> None:
        self.calls.append((timeline, kwargs))

    def disable_timeline(self, timeline: str) -> None:
        self.calls.append((timeline, {"disabled": True}))
