from __future__ import annotations

from pathlib import Path

from datascope_core.adapters.csv_adapter import CsvAdapter
from datascope_core.adapters.image_folder_adapter import ImageFolderAdapter
from datascope_core.adapters.jsonl_adapter import JsonlAdapter
from datascope_core.adapters.mcap_adapter import McapAdapter
from datascope_core.models import DataAdapter


ADAPTERS: dict[str, DataAdapter] = {
    "csv": CsvAdapter(),
    "jsonl": JsonlAdapter(),
    "image_folder": ImageFolderAdapter(),
    "mcap": McapAdapter(),
}


def adapter_for_type(source_type: str) -> DataAdapter:
    try:
        return ADAPTERS[source_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported source type: {source_type}") from exc


def adapter_for_path(path: str) -> DataAdapter:
    source_path = Path(path)
    if source_path.is_dir():
        return adapter_for_type("image_folder")
    suffix = source_path.suffix.lower()
    for adapter in ADAPTERS.values():
        if suffix in adapter.supported_extensions:
            return adapter
    raise ValueError(f"Unsupported source path: {path}")
