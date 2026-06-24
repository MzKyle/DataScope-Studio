from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol


JOB_STATUSES = {
    "pending",
    "running",
    "cancel_requested",
    "cancelled",
    "succeeded",
    "failed",
    "interrupted",
}
TIME_COLUMN_CANDIDATES = {"timestamp", "time", "t", "datetime"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff", ".gif"}
POINT_CLOUD_EXTENSIONS = {
    ".ply",
    ".pcd",
    ".npy",
    ".npz",
    ".xyz",
    ".xyzn",
    ".xyzrgb",
    ".pts",
    ".asc",
}
TEXT_TABLE_EXTENSIONS = {".tsv", ".txt", ".log", ".dat", ".lst", ".list"}


@dataclass(slots=True)
class SourceInfo:
    source_id: str
    source_type: str
    path: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StreamInfo:
    stream_id: str
    name: str
    semantic_type: str
    fields: list[str]
    time_key: str | None
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConvertRequest:
    source: SourceInfo
    mappings: list[dict[str, Any]]
    output_rrd: str
    app_id: str
    recording_id: str
    primary_timeline: str | None = None
    timeline_unit: str = "auto"
    timeline_sort: str = "source"
    cache_dir: str | None = None
    progress_callback: Callable[[str, float], None] | None = None
    cancel_check: Callable[[], None] | None = None
    poll_subprocess: bool = False


@dataclass(slots=True)
class MappingSpec:
    mapping_id: str
    source_id: str
    app_id: str
    recording_id: str
    primary_timeline: str
    streams: list[dict[str, Any]]
    schema_version: int = 2
    timeline_unit: str = "auto"
    timeline_sort: str = "source"
    effective_timeline_unit: str | None = None
    template_id: str | None = None
    mapping_template_id: str | None = None
    status: str = "draft"


class DataAdapter(Protocol):
    adapter_id: str
    display_name: str
    supported_extensions: list[str]

    def inspect(self, path: str, source_id: str | None = None) -> SourceInfo:
        ...

    def infer_streams(self, source: SourceInfo) -> list[StreamInfo]:
        ...

    def preview(self, source: SourceInfo, stream_id: str, limit: int = 100) -> dict[str, Any]:
        ...

    def convert(self, request: ConvertRequest) -> None:
        ...


def detect_source_type(path: str | Path) -> str:
    source_path = Path(path)
    if source_path.is_dir():
        from datascope_core.adapters.ros2_db3_adapter import is_ros2_db3_source

        if is_ros2_db3_source(source_path):
            return "ros2_db3"
        if any(
            child.is_file() and child.suffix.lower() in IMAGE_EXTENSIONS
            for child in source_path.rglob("*")
        ):
            return "image_folder"
        if any(
            child.is_file() and child.suffix.lower() in POINT_CLOUD_EXTENSIONS
            for child in source_path.rglob("*")
        ):
            return "point_cloud"
        raise ValueError(f"Unsupported directory source, no supported images or point clouds found: {path}")

    suffix = source_path.suffix.lower()
    if suffix == ".csv":
        return "csv"
    if suffix in {".jsonl", ".ndjson"}:
        return "jsonl"
    if suffix in IMAGE_EXTENSIONS:
        return "image_folder"
    if suffix in TEXT_TABLE_EXTENSIONS:
        return "text_table"
    if suffix == ".mcap":
        return "mcap"
    if suffix == ".db3":
        return "ros2_db3"
    if suffix in POINT_CLOUD_EXTENSIONS:
        return "point_cloud"
    raise ValueError(f"Unsupported source type for path: {path}")
