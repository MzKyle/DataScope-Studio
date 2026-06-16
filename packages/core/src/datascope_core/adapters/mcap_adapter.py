from __future__ import annotations

import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any

from datascope_core.inference import safe_slug
from datascope_core.models import ConvertRequest, MappingSpec, SourceInfo, StreamInfo
from datascope_core.rerun_cli import rerun_command, rerun_subprocess_env


class McapAdapter:
    adapter_id = "mcap"
    display_name = "MCAP / ROS2 Bag"
    supported_extensions = [".mcap"]

    def inspect(self, path: str, source_id: str | None = None) -> SourceInfo:
        source_path = Path(path)
        summary = _read_summary(source_path)
        return SourceInfo(
            source_id=source_id or f"source_{safe_slug(source_path.stem)}",
            source_type="mcap",
            path=str(source_path),
            metadata={
                "size_bytes": source_path.stat().st_size,
                **summary,
            },
        )

    def infer_streams(self, source: SourceInfo) -> list[StreamInfo]:
        topics = source.metadata.get("topics", [])
        if not topics:
            return [
                StreamInfo(
                    stream_id="stream_mcap_raw",
                    name="mcap_raw",
                    semantic_type="mcap",
                    fields=["*"],
                    time_key="message_log_time",
                    confidence=0.62,
                    metadata={"role": "raw"},
                )
            ]

        streams = []
        for topic in topics:
            topic_name = str(topic["topic"])
            role, semantic_type, confidence = classify_topic(topic_name, topic.get("schema_name", ""))
            streams.append(
                StreamInfo(
                    stream_id=f"stream_{safe_slug(topic_name)}",
                    name=topic_name,
                    semantic_type=semantic_type,
                    fields=[topic_name],
                    time_key="message_log_time",
                    confidence=confidence,
                    metadata={
                        "role": role,
                        "message_encoding": topic.get("message_encoding"),
                        "schema_name": topic.get("schema_name"),
                        "message_count": topic.get("message_count", 0),
                    },
                )
            )
        return streams

    def preview(self, source: SourceInfo, stream_id: str, limit: int = 100) -> dict[str, Any]:
        topics = source.metadata.get("topics", [])[:limit]
        rows = [
            {
                "topic": topic.get("topic"),
                "role": classify_topic(str(topic.get("topic", "")), str(topic.get("schema_name", "")))[0],
                "schema_name": topic.get("schema_name"),
                "message_encoding": topic.get("message_encoding"),
                "message_count": topic.get("message_count"),
            }
            for topic in topics
        ]
        return {
            "source_id": source.source_id,
            "stream_id": stream_id,
            "columns": ["topic", "role", "schema_name", "message_encoding", "message_count"],
            "rows": rows,
        }

    def convert(self, request: ConvertRequest) -> None:
        convert_mcap_to_rrd(Path(request.source.path), request)

    def validate_mapping(
        self,
        source: SourceInfo,
        spec: MappingSpec,
        profile: dict[str, Any],
    ) -> list[dict[str, Any]]:
        issues = []
        if source.metadata.get("inspect_warning"):
            issues.append(
                {
                    "severity": "warning",
                    "code": "mcap_summary_unavailable",
                    "message": str(source.metadata["inspect_warning"]),
                    "stream_id": None,
                    "rule_key": None,
                    "field": None,
                }
            )
        if not source.metadata.get("topics"):
            issues.append(
                {
                    "severity": "warning",
                    "code": "mcap_topics_unavailable",
                    "message": "No MCAP topics were available for mapping validation.",
                    "stream_id": None,
                    "rule_key": None,
                    "field": None,
                }
            )
        return issues


def classify_topic(topic: str, schema_name: str = "") -> tuple[str, str, float]:
    value = f"{topic} {schema_name}".lower()
    if "robot_description" in value or "urdf" in value:
        return "robot_model", "asset3d", 0.86
    if "tf" in value or "transform" in value:
        return "tf_tree", "transform3d", 0.9
    if "camera" in value or "image" in value or "compressedimage" in value:
        return "camera_image", "image", 0.88
    if any(token in value for token in ("pointcloud", "point_cloud", "lidar", "velodyne")):
        return "point_cloud", "points3d", 0.9
    if "laserscan" in value or "laser_scan" in value:
        return "laser_scan", "points2d", 0.86
    if any(token in value for token in ("odom", "pose", "trajectory")):
        return "trajectory", "trajectory3d", 0.82
    if "sensor_msgs/msg/imu" in value or "/imu" in value:
        return "imu", "scalar_group", 0.82
    if "joint" in value:
        return "joint_state", "scalar_group", 0.78
    if any(token in value for token in ("diagnostic", "rosout", "log")):
        return "diagnostics", "text_log", 0.76
    return "raw_topic", "mcap", 0.55


def convert_mcap_to_rrd(mcap_path: Path, request: ConvertRequest) -> None:
    Path(request.output_rrd).parent.mkdir(parents=True, exist_ok=True)
    command = [
        *rerun_command(),
        "mcap",
        "convert",
        str(mcap_path),
        "--output",
        str(request.output_rrd),
        "--application-id",
        request.app_id,
        "--recording-id",
        request.recording_id,
    ]
    if not request.poll_subprocess:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            env=rerun_subprocess_env(),
        )
        if result.returncode != 0:
            message = (
                result.stderr
                or result.stdout
                or "Rerun MCAP conversion failed"
            ).strip()
            raise RuntimeError(message)
        if request.progress_callback is not None:
            request.progress_callback("rerun_mcap", 1.0)
        return

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=rerun_subprocess_env(),
    )
    while process.poll() is None:
        if request.cancel_check is not None:
            request.cancel_check()
        if request.progress_callback is not None:
            request.progress_callback("rerun_mcap", 0.5)
        time.sleep(0.1)
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        message = (stderr or stdout or "Rerun MCAP conversion failed").strip()
        raise RuntimeError(message)
    if request.progress_callback is not None:
        request.progress_callback("rerun_mcap", 1.0)


def _read_summary(path: Path) -> dict[str, Any]:
    try:
        from mcap.reader import make_reader
    except Exception:
        return _fallback_summary(path)

    try:
        with open(path, "rb") as stream:
            summary = make_reader(stream).get_summary()
    except Exception as exc:
        metadata = _fallback_summary(path)
        metadata["inspect_warning"] = str(exc)
        return metadata

    topics = []
    channel_message_counts = (
        summary.statistics.channel_message_counts if summary.statistics is not None else {}
    )
    schemas = summary.schemas or {}
    for channel_id, channel in sorted((summary.channels or {}).items()):
        schema = schemas.get(channel.schema_id)
        topics.append(
            {
                "channel_id": channel_id,
                "topic": channel.topic,
                "message_encoding": channel.message_encoding,
                "schema_id": channel.schema_id,
                "schema_name": schema.name if schema else "",
                "schema_encoding": schema.encoding if schema else "",
                "message_count": channel_message_counts.get(channel_id, 0),
            }
        )

    role_counts = Counter(classify_topic(topic["topic"], topic.get("schema_name", ""))[0] for topic in topics)
    statistics = summary.statistics
    return {
        "profile": getattr(summary, "profile", "") or "",
        "library": getattr(summary, "library", "") or "",
        "topic_count": len(topics),
        "schema_count": len(schemas),
        "message_count": statistics.message_count if statistics else 0,
        "message_start_time": statistics.message_start_time if statistics else None,
        "message_end_time": statistics.message_end_time if statistics else None,
        "has_robot_description": any(
            classify_topic(topic["topic"], topic.get("schema_name", ""))[0] == "robot_model"
            for topic in topics
        ),
        "role_counts": dict(role_counts),
        "topics": topics,
    }


def _fallback_summary(path: Path) -> dict[str, Any]:
    return {
        "profile": "",
        "library": "",
        "topic_count": 0,
        "schema_count": 0,
        "message_count": 0,
        "message_start_time": None,
        "message_end_time": None,
        "role_counts": {},
        "topics": [],
        "inspect_warning": f"MCAP summary unavailable for {path.name}",
    }
