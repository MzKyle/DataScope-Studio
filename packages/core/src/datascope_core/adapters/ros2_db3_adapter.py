from __future__ import annotations

from collections import Counter
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from typing import Any

import yaml
from rosbags.interfaces import (
    Connection,
    ConnectionExtRosbag2,
    MessageDefinitionFormat,
)
from rosbags.rosbag2 import Reader, StoragePlugin, Writer
from rosbags.typesys import Stores, get_types_from_idl, get_types_from_msg, get_typestore
from rosbags.typesys.store import Typestore

from datascope_core.adapters.mcap_adapter import (
    classify_topic,
    convert_mcap_to_rrd,
)
from datascope_core.inference import safe_slug
from datascope_core.models import ConvertRequest, MappingSpec, SourceInfo, StreamInfo


ROS_DISTRO_STORES = {
    "dashing": Stores.ROS2_DASHING,
    "eloquent": Stores.ROS2_ELOQUENT,
    "foxy": Stores.ROS2_FOXY,
    "galactic": Stores.ROS2_GALACTIC,
    "humble": Stores.ROS2_HUMBLE,
    "iron": Stores.ROS2_IRON,
    "jazzy": Stores.ROS2_JAZZY,
    "kilted": Stores.ROS2_KILTED,
    "lyrical": Stores.ROS2_LYRICAL,
}
DEFAULT_ROS_DISTRO = "humble"


class Ros2Db3Adapter:
    adapter_id = "ros2_db3"
    display_name = "ROS2 SQLite Bag"
    supported_extensions = [".db3"]

    def inspect(self, path: str, source_id: str | None = None) -> SourceInfo:
        source_path = Path(path)
        metadata = _inspect_ros2_bag(source_path)
        source_name = source_path.name if source_path.is_dir() else source_path.stem
        return SourceInfo(
            source_id=source_id or f"source_{safe_slug(source_name)}",
            source_type=self.adapter_id,
            path=str(source_path),
            metadata={
                "size_bytes": _source_size(source_path),
                **metadata,
            },
        )

    def infer_streams(self, source: SourceInfo) -> list[StreamInfo]:
        streams = []
        for topic in source.metadata.get("topics", []):
            topic_name = str(topic["topic"])
            message_type = str(topic.get("message_type") or "")
            role, semantic_type, confidence = classify_topic(topic_name, message_type)
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
                        "schema_name": message_type,
                        "message_count": topic.get("message_count", 0),
                        "convertible": bool(topic.get("convertible")),
                        "skip_reason": topic.get("skip_reason"),
                    },
                )
            )
        return streams

    def preview(self, source: SourceInfo, stream_id: str, limit: int = 100) -> dict[str, Any]:
        rows = []
        for topic in source.metadata.get("topics", [])[:limit]:
            topic_name = str(topic.get("topic") or "")
            message_type = str(topic.get("message_type") or "")
            rows.append(
                {
                    "topic": topic_name,
                    "role": classify_topic(topic_name, message_type)[0],
                    "message_type": message_type,
                    "message_encoding": topic.get("message_encoding"),
                    "message_count": topic.get("message_count"),
                    "convertible": bool(topic.get("convertible")),
                    "skip_reason": topic.get("skip_reason") or "",
                }
            )
        return {
            "source_id": source.source_id,
            "stream_id": stream_id,
            "columns": [
                "topic",
                "role",
                "message_type",
                "message_encoding",
                "message_count",
                "convertible",
                "skip_reason",
            ],
            "rows": rows,
        }

    def convert(self, request: ConvertRequest) -> None:
        source_path = Path(request.source.path)
        if request.cache_dir:
            temp_root = Path(request.cache_dir) / "ros2-mcap"
            shutil.rmtree(temp_root, ignore_errors=True)
            temp_root.mkdir(parents=True, exist_ok=True)
            try:
                bag_dir = temp_root / "converted"
                mcap_path = _convert_ros2_bag_to_mcap(source_path, bag_dir, request)
                convert_mcap_to_rrd(mcap_path, request)
            finally:
                shutil.rmtree(temp_root, ignore_errors=True)
            return
        with TemporaryDirectory(prefix="datascope-ros2-db3-") as temp_name:
            bag_dir = Path(temp_name) / "converted"
            mcap_path = _convert_ros2_bag_to_mcap(source_path, bag_dir, request)
            convert_mcap_to_rrd(mcap_path, request)

    def validate_mapping(
        self,
        source: SourceInfo,
        spec: MappingSpec,
        profile: dict[str, Any],
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        if source.metadata.get("distro_fallback"):
            issues.append(
                {
                    "severity": "warning",
                    "code": "ros2_distro_fallback",
                    "message": (
                        "ROS distribution was missing or unsupported; "
                        f"{source.metadata.get('effective_ros_distro', DEFAULT_ROS_DISTRO)} "
                        "message definitions are being used."
                    ),
                    "stream_id": None,
                    "rule_key": None,
                    "field": None,
                }
            )
        skipped_topics = source.metadata.get("skipped_topics", [])
        if skipped_topics:
            details = ", ".join(
                f"{item.get('topic')} ({item.get('message_type')})"
                for item in skipped_topics
            )
            issues.append(
                {
                    "severity": "warning",
                    "code": "ros2_topics_skipped",
                    "message": f"ROS2 topics will be skipped: {details}",
                    "stream_id": None,
                    "rule_key": None,
                    "field": None,
                    "topics": skipped_topics,
                }
            )
        if int(source.metadata.get("convertible_topic_count") or 0) == 0:
            issues.append(
                {
                    "severity": "error",
                    "code": "ros2_no_convertible_topics",
                    "message": "The ROS2 bag contains no topics that can be converted.",
                    "stream_id": None,
                    "rule_key": None,
                    "field": None,
                }
            )
        return issues


def is_ros2_db3_source(path: str | Path) -> bool:
    source_path = Path(path)
    if source_path.is_file():
        return source_path.suffix.lower() == ".db3"
    if not source_path.is_dir():
        return False
    metadata = _load_metadata(source_path / "metadata.yaml")
    info = metadata.get("rosbag2_bagfile_information")
    if not isinstance(info, dict) or str(info.get("storage_identifier") or "") != "sqlite3":
        return False
    relative_paths = info.get("relative_file_paths")
    if not isinstance(relative_paths, list) or not relative_paths:
        return False
    db3_paths = [
        source_path / Path(str(relative_path)).name
        for relative_path in relative_paths
        if Path(str(relative_path)).suffix.lower() == ".db3"
    ]
    return bool(db3_paths) and all(path.is_file() for path in db3_paths)


def metadata_references_db3(metadata_path: Path, db3_path: Path) -> bool:
    metadata = _load_metadata(metadata_path)
    info = metadata.get("rosbag2_bagfile_information")
    if not isinstance(info, dict) or str(info.get("storage_identifier") or "") != "sqlite3":
        return False
    relative_paths = info.get("relative_file_paths")
    if not isinstance(relative_paths, list):
        return False
    return db3_path.name in {Path(str(path)).name for path in relative_paths}


def _inspect_ros2_bag(path: Path) -> dict[str, Any]:
    if not is_ros2_db3_source(path):
        raise ValueError(f"Unsupported ROS2 SQLite bag source: {path}")
    requested_distro = _ros_distro(path)
    effective_distro, distro_fallback, typestore = _resolve_typestore(requested_distro)
    with Reader(path) as reader:
        topics = _topic_metadata(reader.connections, typestore)
        message_count = int(reader.message_count)
        start_time = int(reader.start_time) if message_count else None
        end_time = int(reader.end_time) if message_count else None

    skipped_topics = [
        {
            "topic": topic["topic"],
            "message_type": topic["message_type"],
            "reason": topic["skip_reason"],
        }
        for topic in topics
        if not topic["convertible"]
    ]
    role_counts = Counter(
        classify_topic(str(topic["topic"]), str(topic["message_type"]))[0]
        for topic in topics
    )
    return {
        "storage_identifier": "sqlite3",
        "ros_distro": requested_distro,
        "effective_ros_distro": effective_distro,
        "distro_fallback": distro_fallback,
        "topic_count": len(topics),
        "convertible_topic_count": len(topics) - len(skipped_topics),
        "skipped_topic_count": len(skipped_topics),
        "skipped_topics": skipped_topics,
        "message_count": message_count,
        "message_start_time": start_time,
        "message_end_time": end_time,
        "has_robot_description": any(
            classify_topic(str(topic["topic"]), str(topic["message_type"]))[0]
            == "robot_model"
            for topic in topics
        ),
        "role_counts": dict(role_counts),
        "topics": topics,
    }


def _convert_ros2_bag_to_mcap(
    source_path: Path,
    destination: Path,
    request: ConvertRequest | None = None,
) -> Path:
    requested_distro = _ros_distro(source_path)
    _, _, typestore = _resolve_typestore(requested_distro)
    with Reader(source_path) as reader:
        convertible = _convertible_connections(reader.connections, typestore)
        if not convertible:
            raise RuntimeError("The ROS2 bag contains no topics that can be converted.")
        with Writer(
            destination,
            version=Writer.VERSION_LATEST,
            storage_plugin=StoragePlugin.MCAP,
        ) as writer:
            connection_map: dict[tuple[int, int], Connection] = {}
            for connection in convertible:
                ext = connection.ext
                if not isinstance(ext, ConnectionExtRosbag2):
                    continue
                output_connection = writer.add_connection(
                    connection.topic,
                    connection.msgtype,
                    typestore=typestore,
                    serialization_format=ext.serialization_format,
                    offered_qos_profiles=ext.offered_qos_profiles,
                )
                connection_map[(connection.id, id(connection.owner))] = output_connection
            total = max(int(reader.message_count), 1)
            for index, (connection, timestamp, data) in enumerate(
                reader.messages(connections=convertible),
                start=1,
            ):
                if request is not None and request.cancel_check is not None:
                    request.cancel_check()
                output_connection = connection_map.get((connection.id, id(connection.owner)))
                if output_connection is not None:
                    writer.write(output_connection, timestamp, data)
                if request is not None and request.progress_callback is not None:
                    request.progress_callback("ros2_to_mcap", index / total)
    return destination / f"{destination.name}.mcap"


def _convertible_connections(
    connections: list[Connection],
    typestore: Typestore,
) -> list[Connection]:
    result = []
    for connection in connections:
        ext = connection.ext
        if not isinstance(ext, ConnectionExtRosbag2) or ext.serialization_format != "cdr":
            continue
        if _register_message_definition(connection, typestore):
            result.append(connection)
    return result


def _topic_metadata(
    connections: list[Connection],
    typestore: Typestore,
) -> list[dict[str, Any]]:
    topics = []
    for connection in connections:
        ext = connection.ext
        serialization_format = (
            ext.serialization_format if isinstance(ext, ConnectionExtRosbag2) else ""
        )
        has_definition = (
            connection.msgdef.format != MessageDefinitionFormat.NONE
            and bool(connection.msgdef.data)
        )
        convertible = (
            serialization_format == "cdr"
            and _register_message_definition(connection, typestore)
        )
        if serialization_format != "cdr":
            skip_reason = f"Unsupported serialization format: {serialization_format or 'unknown'}"
        elif not convertible:
            skip_reason = "Message definition is unavailable for the selected ROS distribution"
        else:
            skip_reason = ""
        topics.append(
            {
                "channel_id": connection.id,
                "topic": connection.topic,
                "message_type": connection.msgtype,
                "schema_name": connection.msgtype,
                "message_encoding": serialization_format,
                "message_count": int(connection.msgcount),
                "has_message_definition": has_definition,
                "convertible": convertible,
                "skip_reason": skip_reason,
            }
        )
    return topics


def _register_message_definition(connection: Connection, typestore: Typestore) -> bool:
    if connection.msgtype in typestore.fielddefs:
        return True
    definition = connection.msgdef
    if definition.format == MessageDefinitionFormat.NONE or not definition.data:
        return False
    try:
        if definition.format == MessageDefinitionFormat.IDL:
            separator = "=" * 80 + "\n"
            types: dict[str, Any] = {}
            if definition.data.startswith(f"{separator}IDL: "):
                for item in definition.data.split(separator)[1:]:
                    header, idl = item.split("\n", 1)
                    if header.startswith("IDL: "):
                        types.update(get_types_from_idl(idl))
            else:
                types.update(get_types_from_idl(definition.data))
        else:
            types = get_types_from_msg(definition.data, connection.msgtype)
        typestore.register(types)
    except Exception:
        return False
    return connection.msgtype in typestore.fielddefs


def _resolve_typestore(requested_distro: str | None) -> tuple[str, bool, Typestore]:
    normalized = str(requested_distro or "").strip().lower()
    store = ROS_DISTRO_STORES.get(normalized)
    fallback = store is None
    effective = normalized if store is not None else DEFAULT_ROS_DISTRO
    return effective, fallback, get_typestore(store or Stores.ROS2_HUMBLE)


def _ros_distro(path: Path) -> str | None:
    metadata_path = path / "metadata.yaml" if path.is_dir() else path.parent / "metadata.yaml"
    if path.is_file() and not metadata_references_db3(metadata_path, path):
        return None
    metadata = _load_metadata(metadata_path)
    info = metadata.get("rosbag2_bagfile_information")
    if not isinstance(info, dict):
        return None
    value = info.get("ros_distro")
    return str(value).strip().lower() if value else None


def _load_metadata(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _source_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())
