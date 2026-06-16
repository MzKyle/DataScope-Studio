from __future__ import annotations

from pathlib import Path

from datascope_core.adapters.csv_adapter import CsvAdapter
from datascope_core.adapters.image_folder_adapter import ImageFolderAdapter
from datascope_core.adapters.jsonl_adapter import JsonlAdapter
from datascope_core.adapters.mcap_adapter import McapAdapter
from datascope_core.adapters.point_cloud_adapter import PointCloudAdapter
from datascope_core.adapters.ros2_db3_adapter import Ros2Db3Adapter, is_ros2_db3_source
from datascope_core.models import DataAdapter, IMAGE_EXTENSIONS, POINT_CLOUD_EXTENSIONS


ADAPTERS: dict[str, DataAdapter] = {
    "csv": CsvAdapter(),
    "jsonl": JsonlAdapter(),
    "image_folder": ImageFolderAdapter(),
    "mcap": McapAdapter(),
    "ros2_db3": Ros2Db3Adapter(),
    "point_cloud": PointCloudAdapter(),
}


def adapter_for_type(source_type: str) -> DataAdapter:
    try:
        return ADAPTERS[source_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported source type: {source_type}") from exc


def adapter_for_path(path: str) -> DataAdapter:
    source_path = Path(path)
    if source_path.is_dir():
        if is_ros2_db3_source(source_path):
            return adapter_for_type("ros2_db3")
        if any(
            child.is_file() and child.suffix.lower() in POINT_CLOUD_EXTENSIONS
            for child in source_path.rglob("*")
        ) and not any(
            child.is_file() and child.suffix.lower() in IMAGE_EXTENSIONS
            for child in source_path.rglob("*")
        ):
            return adapter_for_type("point_cloud")
        return adapter_for_type("image_folder")
    suffix = source_path.suffix.lower()
    for adapter in ADAPTERS.values():
        if suffix in adapter.supported_extensions:
            return adapter
    raise ValueError(f"Unsupported source path: {path}")
