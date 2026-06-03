from pathlib import Path

from datascope_core.adapters.csv_adapter import CsvAdapter
from datascope_core.mapping import load_mapping_yaml, save_mapping_yaml, suggest_mapping
from datascope_core.templates import match_templates


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_mapping_yaml_roundtrip(tmp_path: Path) -> None:
    adapter = CsvAdapter()
    source = adapter.inspect(str(FIXTURES / "sample_sensor.csv"), source_id="source_csv")
    streams = adapter.infer_streams(source)
    spec = suggest_mapping(source, streams, mapping_id="mapping_test", recording_id="run_test")
    path = tmp_path / "mapping.yaml"

    save_mapping_yaml(spec, path)
    loaded = load_mapping_yaml(path)

    assert loaded.mapping_id == "mapping_test"
    assert loaded.source_id == "source_csv"
    assert loaded.primary_timeline == "timestamp"
    assert any(stream["entity_path"].startswith("/metrics/") for stream in loaded.streams)


def test_sensor_monitor_template_scores_tabular_streams() -> None:
    adapter = CsvAdapter()
    source = adapter.inspect(str(FIXTURES / "sample_sensor.csv"), source_id="source_csv")
    streams = adapter.infer_streams(source)

    matches = match_templates(streams)

    assert matches[0]["template_id"] == "sensor_monitor"
    assert matches[0]["score"] > 0.8

