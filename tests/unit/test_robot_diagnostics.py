from __future__ import annotations

import json

from datascope_core.robot_diagnostics import (
    build_diagnostic_report,
    normalize_time_seconds,
)


def test_diagnostic_score_and_severity_weights() -> None:
    report = build_diagnostic_report(
        project_id="project",
        recordings=[_recording()],
        sources=[],
        topic_rows=[
            _topic_row("/odom", "trajectory", 1),
            _topic_row("/camera/image", "camera_image", 1),
        ],
        error_rows=[
            {
                "recording_id": "rec",
                "time": 1.0,
                "entity_path": "/logs/diagnostics",
                "key": "message",
                "value": "ERROR motor fault",
            }
        ],
        battery_rows=[
            {
                "recording_id": "rec",
                "time": 2.0,
                "entity_path": "/metrics/battery",
                "key": "battery",
                "value": 0.1,
            }
        ],
        detection_rows=[],
    )

    assert report["summary"]["health_score"] == 50
    assert report["summary"]["severity"] == "critical"
    assert {finding["severity"] for finding in report["findings"]} >= {
        "critical",
        "warning",
    }


def test_topic_coverage_missing_tf_warns() -> None:
    report = build_diagnostic_report(
        project_id="project",
        recordings=[_recording()],
        sources=[],
        topic_rows=[
            _topic_row("/odom", "trajectory", 10),
            _topic_row("/points", "point_cloud", 10),
        ],
        error_rows=[],
        battery_rows=[],
        detection_rows=[],
    )

    assert report["summary"]["severity"] == "warning"
    assert any(
        finding["category"] == "topic_coverage"
        and "TF" in finding["message"]
        for finding in report["findings"]
    )


def test_empty_topic_and_ros2_unconvertible_are_critical() -> None:
    report = build_diagnostic_report(
        project_id="project",
        recordings=[
            _recording(source_id="source_ros"),
            {"id": "rec_empty", "project_id": "project", "source_id": "source_empty"},
        ],
        sources=[
            {
                "id": "source_ros",
                "type": "ros2_db3",
                "metadata": {
                    "topic_count": 1,
                    "message_count": 1,
                    "convertible_topic_count": 0,
                    "skipped_topics": [
                        {
                            "topic": "/custom",
                            "message_type": "acme_msgs/msg/Unknown",
                            "reason": "missing definition",
                        }
                    ],
                },
            },
            {
                "id": "source_empty",
                "type": "mcap",
                "metadata": {"topic_count": 0, "message_count": 0},
            },
        ],
        topic_rows=[],
        error_rows=[],
        battery_rows=[],
        detection_rows=[],
    )

    assert report["summary"]["severity"] == "critical"
    assert any(
        finding["category"] == "convertibility"
        and finding["severity"] == "critical"
        for finding in report["findings"]
    )


def test_time_sync_normalizes_ns_us_ms_and_seconds() -> None:
    assert normalize_time_seconds(1_700_000_000_000_000_000) == 1_700_000_000.0
    assert normalize_time_seconds(1_700_000_000_000_000) == 1_700_000_000.0
    assert normalize_time_seconds(1_700_000_000_000) == 1_700_000_000.0
    assert normalize_time_seconds(1_700_000_000) == 1_700_000_000.0

    base = 1_700_000_000_000_000_000
    report = build_diagnostic_report(
        project_id="project",
        recordings=[_recording()],
        sources=[],
        topic_rows=[
            _topic_row("/tf", "tf_tree", 1, start_time=base, end_time=base + 1_000),
            _topic_row(
                "/camera/image",
                "camera_image",
                1,
                start_time=base + 250_000_000,
                end_time=base + 250_001_000,
            ),
        ],
        error_rows=[],
        battery_rows=[],
        detection_rows=[],
    )

    assert any(
        finding["category"] == "time_sync"
        and finding["severity"] == "warning"
        for finding in report["findings"]
    )


def test_low_battery_and_cv_detection_findings() -> None:
    report = build_diagnostic_report(
        project_id="project",
        recordings=[_recording()],
        sources=[],
        topic_rows=[_topic_row("/tf", "tf_tree", 1)],
        error_rows=[],
        battery_rows=[
            {
                "recording_id": "rec",
                "time": 1.0,
                "entity_path": "/metrics/battery",
                "key": "battery",
                "value": 0.1,
            }
        ],
        detection_rows=[
            {
                "recording_id": "rec",
                "time": 1.0,
                "entity_path": "/camera/pred/boxes",
                "key": "pred_box_count",
                "value": {"reason": "no_prediction", "value": 0},
            }
        ],
    )

    categories = {finding["category"] for finding in report["findings"]}
    assert "battery" in categories
    assert "cv_detection" in categories


def test_general_data_health_findings_from_schema_and_query_rows() -> None:
    report = build_diagnostic_report(
        project_id="project",
        recordings=[_recording()],
        sources=[{"id": "source", "type": "csv", "metadata": {}}],
        topic_rows=[],
        error_rows=[],
        battery_rows=[],
        detection_rows=[],
        schema_profiles=[
            {
                "source_id": "source",
                "source_type": "csv",
                "sample_rows": 6,
                "timeline": {
                    "field": "timestamp",
                    "present": True,
                    "parse_ratio": 0.5,
                    "monotonic": False,
                    "mixed_units": True,
                },
                "fields": [
                    {
                        "name": "temperature",
                        "dtype": "float64",
                        "null_ratio": 0.6,
                        "null_count": 4,
                        "non_null_count": 2,
                    },
                    {
                        "name": "empty_signal",
                        "dtype": "float64",
                        "null_ratio": 1.0,
                        "null_count": 6,
                        "non_null_count": 0,
                    },
                ],
            }
        ],
        query_rows=[
            _query_row(1.0, "voltage", 12.0),
            _query_row(1.0, "voltage", 12.1),
            _query_row(2.0, "voltage", 12.2),
            _query_row(3.0, "voltage", 12.3),
            _query_row(40.0, "voltage", 30.0),
            _query_row(41.0, "voltage", 12.4),
            _query_row(1.0, "mode", "idle", semantic_type="state"),
            _query_row(2.0, "mode", "idle", semantic_type="state"),
            _query_row(3.0, "mode", "idle", semantic_type="state"),
        ],
        thresholds={
            "missing_ratio_warn": 0.2,
            "missing_ratio_critical": 0.5,
            "time_parse_ratio_warn": 0.9,
            "time_gap_factor_warn": 5.0,
            "outlier_iqr_multiplier": 1.5,
        },
    )

    categories = {finding["category"] for finding in report["findings"]}
    assert {"schema_quality", "time_series_quality", "data_quality"} <= categories
    assert any(
        finding["category"] == "schema_quality"
        and finding["severity"] == "critical"
        for finding in report["findings"]
    )
    assert any("Duplicate timestamps" in finding["message"] for finding in report["findings"])
    assert any("outlier" in finding["message"].lower() for finding in report["findings"])
    assert any(check["id"] == "data_quality" for check in report["checks"])


def _recording(source_id: str = "source") -> dict:
    return {"id": "rec", "project_id": "project", "source_id": source_id}


def _topic_row(
    topic: str,
    role: str,
    message_count: int,
    *,
    start_time: int | None = None,
    end_time: int | None = None,
) -> dict:
    return {
        "recording_id": "rec",
        "source_id": "source",
        "value_json": json.dumps(
            {
                "topic": topic,
                "role": role,
                "schema_name": "",
                "message_count": message_count,
                "start_time": start_time,
                "end_time": end_time,
            }
        ),
    }


def _query_row(
    time: float,
    key: str,
    value: object,
    *,
    semantic_type: str = "scalar",
) -> dict:
    return {
        "recording_id": "rec",
        "source_id": "source",
        "time": time,
        "entity_path": f"/metrics/{key}",
        "semantic_type": semantic_type,
        "key": key,
        "value": value,
    }
