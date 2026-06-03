from pathlib import Path

from datascope_core.adapters.csv_adapter import CsvAdapter
from datascope_core.adapters.jsonl_adapter import JsonlAdapter


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_csv_inspect_and_infer_streams() -> None:
    adapter = CsvAdapter()
    source = adapter.inspect(str(FIXTURES / "sample_sensor.csv"), source_id="source_csv")
    streams = adapter.infer_streams(source)

    assert source.source_type == "csv"
    assert source.metadata["rows"] == 4
    assert source.metadata["columns"][0] == "timestamp"
    assert {stream.semantic_type for stream in streams} >= {"scalar", "scalar_group", "state", "text_log"}
    assert all(stream.time_key == "timestamp" for stream in streams)


def test_jsonl_inspect_flattens_one_level_nested_records() -> None:
    adapter = JsonlAdapter()
    source = adapter.inspect(str(FIXTURES / "sample_sensor.jsonl"), source_id="source_jsonl")
    streams = adapter.infer_streams(source)

    assert source.source_type == "jsonl"
    assert "robot.x" in source.metadata["columns"]
    assert any(stream.semantic_type == "scalar_group" for stream in streams)
    assert any(stream.name == "battery" for stream in streams)
    assert all(stream.time_key == "time" for stream in streams)

