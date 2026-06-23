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
    assert spec.timeline_sort == "source"
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
            "timeline": {"field": "timestamp", "unit": "auto", "sort": "ascending"},
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
    assert spec.timeline_sort == "ascending"
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


def test_validation_suggestions_can_repair_core_mapping_issues(tmp_path: Path) -> None:
    path = tmp_path / "repair.csv"
    path.write_text(
        "event_time,actual_field\n"
        "1,10\n"
        "2,20\n",
        encoding="utf-8",
    )
    adapter = CsvAdapter()
    source = adapter.inspect(str(path), source_id="source_repair")
    streams = adapter.infer_streams(source)
    profile = build_schema_profile(source, streams)
    spec = MappingSpec(
        mapping_id="mapping_repair",
        source_id=source.source_id,
        app_id="app",
        recording_id="recording",
        primary_timeline="missing_time",
        streams=[
            {
                "stream_id": "first",
                "source_fields": ["actual_feld"],
                "semantic_type": "scalar",
                "entity_path": "/metrics/value",
                "enabled": True,
                "required": False,
                "rule_key": "first",
            },
            {
                "stream_id": "second",
                "source_fields": ["actual_field"],
                "semantic_type": "image",
                "entity_path": "/metrics/value",
                "enabled": True,
                "required": False,
                "rule_key": "second",
            },
            {
                "stream_id": "third",
                "source_fields": ["actual_field"],
                "semantic_type": "scalar",
                "entity_path": "/metrics/value",
                "enabled": True,
                "required": False,
                "rule_key": "third",
            },
        ],
    )

    report = validate_mapping(source, spec, profile)

    assert report["source_family"] == "tabular"
    assert "scalar" in report["supported_semantic_types"]
    assert all(issue["recommendation"] for issue in report["issues"])
    assert all("suggestions" in issue for issue in report["issues"])

    missing = next(issue for issue in report["issues"] if issue["code"] == "field_missing")
    replacement = next(
        suggestion
        for suggestion in missing["suggestions"]
        if suggestion["action"] == "replace_source_field"
    )
    assert replacement["params"]["new_field"] == "actual_field"

    duplicate_paths = [
        next(
            suggestion
            for suggestion in issue["suggestions"]
            if suggestion["action"] == "set_entity_path"
        )["params"]["entity_path"]
        for issue in report["issues"]
        if issue["code"] == "duplicate_entity_path"
    ]
    assert duplicate_paths == ["/metrics/value_2", "/metrics/value_3"]

    spec.primary_timeline = ""
    spec.streams[0]["source_fields"] = ["actual_field"]
    spec.streams[1]["semantic_type"] = "scalar"
    for stream, path_value in zip(spec.streams[1:], duplicate_paths):
        stream["entity_path"] = path_value

    repaired = validate_mapping(source, spec, profile)

    assert repaired["valid"] is True
    assert not repaired["issues"]


def test_time_suggestions_cover_sort_units_and_row_sequence(tmp_path: Path) -> None:
    path = tmp_path / "time_repairs.csv"
    path.write_text(
        "time,value\n"
        "2,10\n"
        "1,20\n",
        encoding="utf-8",
    )
    adapter = CsvAdapter()
    source = adapter.inspect(str(path), source_id="source_time_repairs")
    streams = adapter.infer_streams(source)
    profile = build_schema_profile(source, streams)
    spec = suggest_mapping(source, streams)

    report = validate_mapping(source, spec, profile)
    non_monotonic = next(
        issue for issue in report["issues"] if issue["code"] == "non_monotonic_time"
    )
    assert non_monotonic["suggestions"] == [
        {
            "action": "set_timeline_sort",
            "label": "Sort by time ascending",
            "params": {"sort": "ascending"},
        }
    ]

    spec.timeline_sort = "ascending"
    sorted_report = validate_mapping(source, spec, profile)
    assert "non_monotonic_time" not in {
        issue["code"] for issue in sorted_report["issues"]
    }

    spec.primary_timeline = ""
    row_report = validate_mapping(source, spec, profile)
    assert "missing_time_column" not in {
        issue["code"] for issue in row_report["issues"]
    }

    mixed_path = tmp_path / "mixed_units.csv"
    mixed_path.write_text(
        "time,value\n"
        "1,10\n"
        "1700000000000,20\n",
        encoding="utf-8",
    )
    mixed_source = adapter.inspect(str(mixed_path), source_id="source_mixed_units")
    mixed_streams = adapter.infer_streams(mixed_source)
    mixed_profile = build_schema_profile(mixed_source, mixed_streams)
    mixed_report = validate_mapping(
        mixed_source,
        suggest_mapping(mixed_source, mixed_streams),
        mixed_profile,
    )
    mixed_issue = next(
        issue for issue in mixed_report["issues"] if issue["code"] == "mixed_time_units"
    )
    assert {
        suggestion["params"]["unit"] for suggestion in mixed_issue["suggestions"]
    } >= {"relative_s", "unix_ms", "unix_ns"}


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


def test_state_logging_falls_back_for_rerun_without_state_change(monkeypatch) -> None:
    fake_rerun = SimpleNamespace(TextLog=lambda value: ("TextLog", value))
    monkeypatch.setitem(sys.modules, "rerun", fake_rerun)
    rec = FakeLogRecording()

    _log_mapping(
        rec,
        pd.Series({"status": "RUNNING"}),
        {
            "enabled": True,
            "semantic_type": "state",
            "source_fields": ["status"],
            "entity_path": "/states/status",
        },
    )

    assert rec.logs == [("/states/status", ("TextLog", "RUNNING"))]


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


def test_point_cloud_adapter_profile_does_not_report_unknown_field_as_empty(
    tmp_path: Path,
) -> None:
    path = tmp_path / "valid.ply"
    path.write_text(
        "ply\n"
        "format ascii 1.0\n"
        "element vertex 1\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "end_header\n"
        "1 2 3\n",
        encoding="utf-8",
    )
    adapter = PointCloudAdapter()
    source = adapter.inspect(str(path), source_id="source_valid_cloud")
    streams = adapter.infer_streams(source)
    spec = suggest_mapping(source, streams)
    profile = build_schema_profile(source, streams)

    report = validate_mapping(source, spec, profile)

    assert not any(issue["code"] == "fields_empty" for issue in report["issues"])


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
