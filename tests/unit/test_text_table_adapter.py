from pathlib import Path

from datascope_core.adapters.text_table_adapter import TextTableAdapter
from datascope_core.mapping import suggest_mapping
from datascope_core.models import detect_source_type
from datascope_core.schema_profile import build_schema_profile


def test_text_table_adapter_inspects_tsv_table(tmp_path: Path) -> None:
    path = tmp_path / "samples.tsv"
    path.write_text(
        "time\tvoltage\tstate\n"
        "0\t12.5\tok\n"
        "1\t11.9\twarn\n",
        encoding="utf-8",
    )
    adapter = TextTableAdapter()

    source = adapter.inspect(str(path), source_id="source_tsv")
    streams = adapter.infer_streams(source)
    preview = adapter.preview(source, "stream_voltage")
    profile = build_schema_profile(source, streams)
    spec = suggest_mapping(source, streams)

    assert detect_source_type(path) == "text_table"
    assert source.source_type == "text_table"
    assert source.metadata["text"]["mode"] == "table"
    assert source.metadata["text"]["resolved_delimiter"] == "tab"
    assert source.metadata["columns"] == ["time", "voltage", "state"]
    assert source.metadata["rows"] == 2
    assert preview["rows"][0]["voltage"] == 12.5
    assert {stream.semantic_type for stream in streams} >= {"scalar", "state"}
    assert all(stream.time_key == "time" for stream in streams)
    assert profile["source_family"] == "tabular"
    assert spec.template_id == "sensor_monitor"


def test_text_table_adapter_falls_back_to_text_log(tmp_path: Path) -> None:
    path = tmp_path / "run.log"
    path.write_text(
        "INFO boot complete\n"
        "WARN battery low\n"
        "\n"
        "ERROR motor stalled\n",
        encoding="utf-8",
    )
    adapter = TextTableAdapter()

    source = adapter.inspect(str(path), source_id="source_log")
    streams = adapter.infer_streams(source)
    preview = adapter.preview(source, "stream_system_log")

    assert source.metadata["text"]["mode"] == "log"
    assert source.metadata["columns"] == ["line_number", "message"]
    assert source.metadata["rows"] == 3
    assert preview["rows"][0] == {"line_number": 1, "message": "INFO boot complete"}
    assert any(stream.semantic_type == "text_log" for stream in streams)
    assert all(stream.time_key == "line_number" for stream in streams)


def test_text_table_adapter_supports_headerless_whitespace_text(tmp_path: Path) -> None:
    path = tmp_path / "pose.txt"
    path.write_text("1781733042228 1.0 2.0\n1781733042271 4.0 5.0\n", encoding="utf-8")
    adapter = TextTableAdapter()

    source = adapter.inspect(
        str(path),
        options={
            "text": {
                "delimiter": "whitespace",
                "header_mode": "no_header",
                "column_names": ["timestamp", "x", "y"],
            }
        },
    )
    preview = adapter.preview(source, "stream_x", limit=1)

    assert source.metadata["text"]["mode"] == "table"
    assert source.metadata["text"]["resolved_delimiter"] == "whitespace"
    assert source.metadata["columns"] == ["timestamp", "x", "y"]
    assert preview["rows"][0]["timestamp"] == 1781733042228
    assert preview["rows"][0]["x"] == 1.0
