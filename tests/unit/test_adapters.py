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


def test_csv_headerless_source_uses_configured_column_names(tmp_path: Path) -> None:
    path = tmp_path / "pose.csv"
    path.write_text(
        "1781733042228,1.0,2.0,3.0,0.1,0.2,0.3\n"
        "1781733042271,4.0,5.0,6.0,0.4,0.5,0.6\n",
        encoding="utf-8",
    )
    adapter = CsvAdapter()
    source = adapter.inspect(
        str(path),
        options={
            "csv": {
                "header_mode": "no_header",
                "column_names": ["timestamp", "x", "y", "z", "rx", "ry", "rz"],
            }
        },
    )
    preview = adapter.preview(source, "stream_x", limit=1)

    assert source.metadata["rows"] == 2
    assert source.metadata["columns"] == ["timestamp", "x", "y", "z", "rx", "ry", "rz"]
    assert source.metadata["csv"]["resolved_header_mode"] == "no_header"
    assert preview["rows"][0]["timestamp"] == 1781733042228
    assert preview["rows"][0]["x"] == 1.0


def test_csv_headerless_source_is_auto_detected(tmp_path: Path) -> None:
    path = tmp_path / "headerless.csv"
    path.write_text("1,2,3\n4,5,6\n", encoding="utf-8")

    source = CsvAdapter().inspect(str(path))

    assert source.metadata["rows"] == 2
    assert source.metadata["columns"] == ["column_1", "column_2", "column_3"]
    assert source.metadata["csv"]["resolved_header_mode"] == "no_header"


def test_jsonl_inspect_flattens_one_level_nested_records() -> None:
    adapter = JsonlAdapter()
    source = adapter.inspect(str(FIXTURES / "sample_sensor.jsonl"), source_id="source_jsonl")
    streams = adapter.infer_streams(source)

    assert source.source_type == "jsonl"
    assert "robot.x" in source.metadata["columns"]
    assert any(stream.semantic_type == "scalar_group" for stream in streams)
    assert any(stream.name == "battery" for stream in streams)
    assert all(stream.time_key == "time" for stream in streams)
