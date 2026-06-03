from pathlib import Path

from mcap.writer import Writer

from datascope_core.adapters.mcap_adapter import McapAdapter, classify_topic
from datascope_core.mapping import suggest_mapping
from datascope_core.templates import match_templates


def test_classify_robotics_topics() -> None:
    assert classify_topic("/tf", "tf2_msgs/msg/TFMessage")[0] == "tf_tree"
    assert classify_topic("/camera/front/image_raw", "sensor_msgs/msg/Image")[0] == "camera_image"
    assert classify_topic("/lidar/points", "sensor_msgs/msg/PointCloud2")[0] == "point_cloud"
    assert classify_topic("/odom", "nav_msgs/msg/Odometry")[0] == "trajectory"


def test_mcap_inspect_streams_mapping_and_template(tmp_path: Path) -> None:
    mcap_path = _make_mcap_fixture(tmp_path)
    adapter = McapAdapter()

    source = adapter.inspect(str(mcap_path), source_id="source_mcap")
    streams = adapter.infer_streams(source)
    spec = suggest_mapping(source, streams, template_id="robotics_debug")
    matches = match_templates(streams)

    assert source.source_type == "mcap"
    assert source.metadata["topic_count"] == 4
    assert source.metadata["message_count"] == 4
    assert {stream.metadata["role"] for stream in streams} >= {
        "camera_image",
        "point_cloud",
        "tf_tree",
        "trajectory",
    }
    assert spec.app_id == "datascope.robotics_debug.v1"
    assert any(stream["entity_path"].startswith("/sensors/") for stream in spec.streams)
    assert matches[0]["template_id"] == "robotics_debug"


def _make_mcap_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "robot.mcap"
    with open(path, "wb") as stream:
        writer = Writer(stream)
        writer.start(profile="ros2", library="datascope-test")
        topics = [
            ("/tf", "tf2_msgs/msg/TFMessage"),
            ("/camera/front/image_raw", "sensor_msgs/msg/Image"),
            ("/lidar/points", "sensor_msgs/msg/PointCloud2"),
            ("/odom", "nav_msgs/msg/Odometry"),
        ]
        for index, (topic, schema_name) in enumerate(topics, start=1):
            schema_id = writer.register_schema(schema_name, "ros2msg", b"uint8[] data")
            channel_id = writer.register_channel(topic, "cdr", schema_id)
            writer.add_message(
                channel_id,
                log_time=index,
                publish_time=index,
                data=b"\x00\x01",
                sequence=index,
            )
        writer.finish()
    return path

