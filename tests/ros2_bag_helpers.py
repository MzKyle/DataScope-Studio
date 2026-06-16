from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

import yaml
from rosbags.rosbag2 import StoragePlugin, Writer
from rosbags.typesys import Stores, get_types_from_msg, get_typestore


Topic = tuple[str, str]


def make_legacy_db3(
    path: Path,
    topics: Iterable[Topic],
    *,
    start_time: int = 1_700_000_000_000_000_000,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            create table topics(
              id integer primary key,
              name text not null,
              type text not null,
              serialization_format text not null,
              offered_qos_profiles text not null
            );
            create table messages(
              id integer primary key,
              topic_id integer not null,
              timestamp integer not null,
              data blob not null
            );
            create index timestamp_idx on messages(timestamp asc);
            """
        )
        for index, (topic, message_type) in enumerate(topics, start=1):
            conn.execute(
                """
                insert into topics(id, name, type, serialization_format, offered_qos_profiles)
                values (?, ?, ?, ?, ?)
                """,
                (index, topic, message_type, "cdr", "[]"),
            )
            conn.execute(
                "insert into messages(id, topic_id, timestamp, data) values (?, ?, ?, ?)",
                (index, index, start_time + index, b"\x00\x01"),
            )
    return path


def make_ros2_directory(
    path: Path,
    files: list[tuple[str, list[Topic]]],
    *,
    ros_distro: str | None = "humble",
) -> Path:
    all_topics: list[Topic] = []
    for index, (file_name, topics) in enumerate(files):
        make_legacy_db3(
            path / file_name,
            topics,
            start_time=1_700_000_000_000_000_000 + index * 1_000,
        )
        all_topics.extend(topics)
    metadata = {
        "rosbag2_bagfile_information": {
            "version": 5,
            "storage_identifier": "sqlite3",
            "relative_file_paths": [name for name, _ in files],
            "duration": {"nanoseconds": max(len(all_topics), 1)},
            "starting_time": {
                "nanoseconds_since_epoch": 1_700_000_000_000_000_001
            },
            "message_count": len(all_topics),
            "topics_with_message_count": [
                {
                    "topic_metadata": {
                        "name": topic,
                        "type": message_type,
                        "serialization_format": "cdr",
                        "offered_qos_profiles": [],
                    },
                    "message_count": 1,
                }
                for topic, message_type in all_topics
            ],
            "compression_format": "",
            "compression_mode": "",
            "files": [],
            "custom_data": None,
            **({"ros_distro": ros_distro} if ros_distro else {}),
        }
    }
    path.mkdir(parents=True, exist_ok=True)
    (path / "metadata.yaml").write_text(
        yaml.safe_dump(metadata, sort_keys=False),
        encoding="utf-8",
    )
    return path


def make_embedded_custom_bag(path: Path) -> Path:
    store = get_typestore(Stores.ROS2_HUMBLE)
    message_type = "custom_msgs/msg/Status"
    store.register(get_types_from_msg("string label\nint32 value\n", message_type))
    message = store.types[message_type](label="ready", value=7)
    raw = store.serialize_cdr(message, message_type)
    with Writer(path, version=Writer.VERSION_LATEST, storage_plugin=StoragePlugin.SQLITE3) as writer:
        connection = writer.add_connection("/custom/status", message_type, typestore=store)
        writer.write(connection, 1_700_000_000_000_000_000, raw)
    metadata_path = path / "metadata.yaml"
    metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    metadata["rosbag2_bagfile_information"]["ros_distro"] = "humble"
    metadata_path.write_text(yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8")
    return path
