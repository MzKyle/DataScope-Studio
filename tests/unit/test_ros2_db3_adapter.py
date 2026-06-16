from pathlib import Path

import pytest
from mcap.reader import make_reader

from datascope_core.adapters.ros2_db3_adapter import (
    Ros2Db3Adapter,
    _convert_ros2_bag_to_mcap,
    is_ros2_db3_source,
)
from datascope_core.mapping import suggest_mapping
from datascope_core.models import detect_source_type
from datascope_core.schema_profile import build_schema_profile
from tests.ros2_bag_helpers import (
    make_embedded_custom_bag,
    make_legacy_db3,
    make_ros2_directory,
)


def test_detects_raw_db3_and_valid_ros2_directory(tmp_path: Path) -> None:
    db3 = make_legacy_db3(
        tmp_path / "raw.db3",
        [("/chatter", "std_msgs/msg/String")],
    )
    bag = make_ros2_directory(
        tmp_path / "bag",
        [("bag_0.db3", [("/tf", "tf2_msgs/msg/TFMessage")])],
    )
    invalid = tmp_path / "invalid"
    invalid.mkdir()
    (invalid / "orphan.db3").write_bytes(b"not a bag")

    assert is_ros2_db3_source(db3)
    assert is_ros2_db3_source(bag)
    assert not is_ros2_db3_source(invalid)
    assert detect_source_type(db3) == "ros2_db3"
    assert detect_source_type(bag) == "ros2_db3"


def test_inspect_uses_humble_and_skips_unknown_custom_topics(tmp_path: Path) -> None:
    bag = make_ros2_directory(
        tmp_path / "bag",
        [
            (
                "bag.db3",
                [
                    ("/chatter", "std_msgs/msg/String"),
                    ("/custom", "acme_msgs/msg/Unknown"),
                ],
            )
        ],
        ros_distro="humble",
    )
    adapter = Ros2Db3Adapter()

    source = adapter.inspect(str(bag))
    streams = adapter.infer_streams(source)
    profile = build_schema_profile(source, streams)
    spec = suggest_mapping(source, streams, template_id="robotics_debug")
    issues = adapter.validate_mapping(source, spec, profile)

    assert source.metadata["effective_ros_distro"] == "humble"
    assert source.metadata["distro_fallback"] is False
    assert source.metadata["convertible_topic_count"] == 1
    assert source.metadata["skipped_topic_count"] == 1
    assert source.metadata["skipped_topics"][0]["topic"] == "/custom"
    assert any(issue["code"] == "ros2_topics_skipped" for issue in issues)
    assert profile["source_family"] == "mcap"


def test_inspect_falls_back_to_humble_without_metadata(tmp_path: Path) -> None:
    db3 = make_legacy_db3(
        tmp_path / "raw.db3",
        [("/chatter", "std_msgs/msg/String")],
    )
    source = Ros2Db3Adapter().inspect(str(db3))

    assert source.metadata["ros_distro"] is None
    assert source.metadata["effective_ros_distro"] == "humble"
    assert source.metadata["distro_fallback"] is True


def test_embedded_custom_message_definition_is_convertible(tmp_path: Path) -> None:
    bag = make_embedded_custom_bag(tmp_path / "custom_bag")
    source = Ros2Db3Adapter().inspect(str(bag))

    assert source.metadata["convertible_topic_count"] == 1
    assert source.metadata["skipped_topic_count"] == 0
    assert source.metadata["topics"][0]["has_message_definition"] is True


def test_split_bag_directory_merges_topics(tmp_path: Path) -> None:
    bag = make_ros2_directory(
        tmp_path / "split_bag",
        [
            ("split_0.db3", [("/camera/image", "sensor_msgs/msg/Image")]),
            ("split_1.db3", [("/lidar/points", "sensor_msgs/msg/PointCloud2")]),
        ],
    )
    source = Ros2Db3Adapter().inspect(str(bag))

    assert source.metadata["topic_count"] == 2
    assert source.metadata["message_count"] == 2
    assert {topic["topic"] for topic in source.metadata["topics"]} == {
        "/camera/image",
        "/lidar/points",
    }


def test_conversion_writes_temporary_mcap_with_only_convertible_topics(
    tmp_path: Path,
) -> None:
    db3 = make_legacy_db3(
        tmp_path / "raw.db3",
        [
            ("/chatter", "std_msgs/msg/String"),
            ("/custom", "acme_msgs/msg/Unknown"),
        ],
    )
    mcap_path = _convert_ros2_bag_to_mcap(db3, tmp_path / "converted")

    with mcap_path.open("rb") as stream:
        summary = make_reader(stream).get_summary()

    assert mcap_path.exists()
    assert summary is not None
    assert {channel.topic for channel in summary.channels.values()} == {"/chatter"}


def test_supported_robotics_message_families_convert_to_mcap(tmp_path: Path) -> None:
    topics = [
        ("/camera/image", "sensor_msgs/msg/Image"),
        ("/camera/compressed", "sensor_msgs/msg/CompressedImage"),
        ("/points", "sensor_msgs/msg/PointCloud2"),
        ("/tf", "tf2_msgs/msg/TFMessage"),
        ("/odom", "nav_msgs/msg/Odometry"),
        ("/imu/data", "sensor_msgs/msg/Imu"),
        ("/scan", "sensor_msgs/msg/LaserScan"),
        ("/joint_states", "sensor_msgs/msg/JointState"),
        ("/diagnostics", "diagnostic_msgs/msg/DiagnosticArray"),
    ]
    db3 = make_legacy_db3(tmp_path / "robotics.db3", topics)

    source = Ros2Db3Adapter().inspect(str(db3))
    mcap_path = _convert_ros2_bag_to_mcap(db3, tmp_path / "robotics_converted")

    with mcap_path.open("rb") as stream:
        summary = make_reader(stream).get_summary()

    assert source.metadata["convertible_topic_count"] == len(topics)
    assert source.metadata["skipped_topic_count"] == 0
    assert summary is not None
    assert {channel.topic for channel in summary.channels.values()} == {
        topic for topic, _ in topics
    }


def test_conversion_fails_when_all_topics_are_unknown(tmp_path: Path) -> None:
    db3 = make_legacy_db3(
        tmp_path / "raw.db3",
        [("/custom", "acme_msgs/msg/Unknown")],
    )

    with pytest.raises(RuntimeError, match="no topics"):
        _convert_ros2_bag_to_mcap(db3, tmp_path / "converted")
