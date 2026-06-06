import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from datascope_core.adapters.csv_adapter import CsvAdapter
from datascope_core.adapters.point_cloud_adapter import PointCloudAdapter
from datascope_core.mapping import mapping_from_yaml_dict, suggest_mapping
from datascope_core.mapping_templates import apply_mapping_template
from datascope_core.mapping_validation import validate_mapping
from datascope_core.models import MappingSpec
from datascope_core.rerun_writer import _log_mapping, _set_row_time
from datascope_core.schema_profile import build_schema_profile


def test_legacy_mapping_yaml_migrates_to_v2_auto_time() -> None:
    spec = mapping_from_yaml_dict(
        {
            "mapping": {
                "id": "legacy",
                "source": "source_legacy",
                "timelines": {
                    "primary": {
                        "source_field": "timestamp",
                        "unit": "seconds",
                    }
                },
                "streams": [
                    {
                        "stream_id": "stream_value",
                        "fields": ["value"],
                        "semantic_type": "scalar",
                        "entity_path": "/metrics/value",
                    }
                ],
            }
        }
    )

    assert spec.schema_version == 2
    assert spec.timeline_unit == "auto"
    assert spec.streams[0]["source_fields"] == ["value"]
    assert spec.streams[0]["archetype"] == "Scalars"
    assert spec.streams[0]["enabled"] is True


def test_mapping_template_alias_regex_and_ambiguity(tmp_path: Path) -> None:
    path = tmp_path / "sample.csv"
    path.write_text(
        "Timestamp,Battery-Voltage,temp_a,temp_b\n"
        "1,0.8,20,21\n"
        "2,0.7,22,23\n",
        encoding="utf-8",
    )
    adapter = CsvAdapter()
    source = adapter.inspect(str(path), source_id="source_template")
    streams = adapter.infer_streams(source)
    profile = build_schema_profile(source, streams)
    payload = {
        "mapping_template": {
            "schema_version": 1,
            "id": "template_test",
            "name": "Template Test",
            "version": "1.0.0",
            "source_family": "tabular",
            "visual_template_id": "sensor_monitor",
            "timeline": {"field": "timestamp", "unit": "auto"},
            "rules": [
                {
                    "key": "battery",
                    "semantic_type": "scalar",
                    "entity_path": "/metrics/battery",
                    "source_fields": ["battery"],
                    "aliases": {"battery": ["Battery-Voltage"]},
                    "patterns": {},
                    "required": True,
                    "enabled": True,
                },
                {
                    "key": "temperature",
                    "semantic_type": "scalar",
                    "entity_path": "/metrics/temperature",
                    "source_fields": ["temperature"],
                    "aliases": {},
                    "patterns": {"temperature": "^temp_"},
                    "required": True,
                    "enabled": True,
                },
            ],
        }
    }

    spec, issues = apply_mapping_template(payload, source, streams, profile)

    battery = next(stream for stream in spec.streams if stream["rule_key"] == "battery")
    temperature = next(
        stream for stream in spec.streams if stream["rule_key"] == "temperature"
    )
    assert spec.primary_timeline == "Timestamp"
    assert battery["source_fields"] == ["Battery-Voltage"]
    assert temperature["match_ambiguous"] is True
    assert any(issue["code"] == "ambiguous_field_match" for issue in issues)
    assert any(stream["origin"] == "inferred_extra" for stream in spec.streams)


def test_validation_reports_time_and_coordinate_problems(tmp_path: Path) -> None:
    path = tmp_path / "invalid.csv"
    path.write_text(
        "timestamp,position_x,position_y,value\n"
        "2,1,2,\n"
        "1,3,4,5\n"
        ",5,6,\n",
        encoding="utf-8",
    )
    adapter = CsvAdapter()
    source = adapter.inspect(str(path), source_id="source_invalid")
    streams = adapter.infer_streams(source)
    profile = build_schema_profile(source, streams)
    spec = MappingSpec(
        mapping_id="mapping_invalid",
        source_id=source.source_id,
        app_id="datascope.sensor_monitor.v1",
        recording_id="recording_invalid",
        primary_timeline="timestamp",
        timeline_unit="unix_ms",
        streams=[
            {
                "stream_id": "position",
                "source_fields": ["position_x", "position_y"],
                "semantic_type": "points3d",
                "entity_path": "/world/position",
                "enabled": True,
                "required": True,
                "rule_key": "position",
            },
            {
                "stream_id": "value",
                "source_fields": ["value"],
                "semantic_type": "scalar",
                "entity_path": "/world/position",
                "enabled": True,
                "required": False,
                "rule_key": "value",
            },
        ],
    )

    report = validate_mapping(source, spec, profile)
    codes = {issue["code"] for issue in report["issues"]}

    assert report["valid"] is False
    assert {"missing_coordinate_axes", "duplicate_entity_path"} <= codes
    assert {"non_monotonic_time", "time_nulls", "time_unit_mismatch"} <= codes


def test_invalid_time_disables_primary_timeline() -> None:
    rec = FakeRecording()

    _set_row_time(
        rec,
        pd.Series({"timestamp": "bad"}),
        4,
        [],
        time_key="timestamp",
        time_unit="datetime",
    )

    assert rec.calls == [
        ("set_time", "row", {"sequence": 4}),
        ("disable_timeline", "time", {}),
    ]


def test_tabular_geometry_logging(monkeypatch) -> None:
    fake_rerun = FakeRerun()
    monkeypatch.setitem(sys.modules, "rerun", fake_rerun)
    rec = FakeLogRecording()
    row = pd.Series({"pose_x": 1, "pose_y": 2, "pose_z": 3})

    _log_mapping(
        rec,
        row,
        {
            "enabled": True,
            "semantic_type": "points3d",
            "source_fields": ["pose_x", "pose_y", "pose_z"],
            "entity_path": "/world/point",
        },
    )

    assert rec.logs == [("/world/point", ("Points3D", [[1.0, 2.0, 3.0]]))]


def test_point_cloud_adapter_validation_reports_missing_xyz(tmp_path: Path) -> None:
    path = tmp_path / "invalid.ply"
    path.write_text(
        "ply\n"
        "format ascii 1.0\n"
        "element vertex 1\n"
        "property float x\n"
        "property float y\n"
        "end_header\n"
        "1 2\n",
        encoding="utf-8",
    )
    adapter = PointCloudAdapter()
    source = adapter.inspect(str(path), source_id="source_invalid_cloud")
    streams = adapter.infer_streams(source)
    spec = suggest_mapping(source, streams)

    issues = adapter.validate_mapping(source, spec, {})

    assert any(issue["code"] == "point_cloud_coordinates_missing" for issue in issues)


class FakeRecording:
    def __init__(self) -> None:
        self.calls = []

    def set_time(self, timeline: str, **kwargs) -> None:
        self.calls.append(("set_time", timeline, kwargs))

    def disable_timeline(self, timeline: str) -> None:
        self.calls.append(("disable_timeline", timeline, {}))


class FakeLogRecording:
    def __init__(self) -> None:
        self.logs = []

    def log(self, path: str, value) -> None:
        self.logs.append((path, value))


class FakeRerun(SimpleNamespace):
    def __init__(self) -> None:
        super().__init__(
            Points3D=lambda values: ("Points3D", values),
        )
