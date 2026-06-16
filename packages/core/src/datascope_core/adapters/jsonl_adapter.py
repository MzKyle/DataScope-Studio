from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from datascope_core.inference import (
    detect_time_column,
    flatten_record,
    infer_semantic_streams,
    safe_slug,
)
from datascope_core.models import ConvertRequest, SourceInfo, StreamInfo
from datascope_core.rerun_writer import write_tabular_chunks


class JsonlAdapter:
    adapter_id = "jsonl"
    display_name = "JSON Lines"
    supported_extensions = [".jsonl", ".ndjson"]

    def inspect(self, path: str, source_id: str | None = None) -> SourceInfo:
        rows = _read_jsonl(path, limit=1000)
        frame = pd.DataFrame(rows)
        total_rows = sum(1 for _ in open(path, "rb"))
        return SourceInfo(
            source_id=source_id or f"source_{safe_slug(Path(path).stem)}",
            source_type="jsonl",
            path=str(path),
            metadata={
                "columns": list(frame.columns),
                "dtypes": {column: str(dtype) for column, dtype in frame.dtypes.items()},
                "rows": total_rows,
                "sample_rows": len(frame),
                "size_bytes": Path(path).stat().st_size,
            },
        )

    def infer_streams(self, source: SourceInfo) -> list[StreamInfo]:
        frame = pd.DataFrame(_read_jsonl(source.path, limit=1000))
        time_key = detect_time_column(list(frame.columns), frame)
        return [
            StreamInfo(
                stream_id=f"stream_{safe_slug(stream['name'])}",
                name=stream["name"],
                semantic_type=stream["semantic_type"],
                fields=stream["fields"],
                time_key=time_key,
                confidence=stream["confidence"],
                metadata=stream["metadata"],
            )
            for stream in infer_semantic_streams(frame, time_key)
        ]

    def preview(self, source: SourceInfo, stream_id: str, limit: int = 100) -> dict:
        frame = pd.DataFrame(_read_jsonl(source.path, limit=limit))
        return {
            "source_id": source.source_id,
            "stream_id": stream_id,
            "columns": list(frame.columns),
            "rows": frame.fillna("").to_dict(orient="records"),
        }

    def convert(self, request: ConvertRequest) -> None:
        write_tabular_chunks(
            (
                pd.DataFrame(rows)
                for rows in _read_jsonl_batches(request.source.path, batch_size=50_000)
            ),
            request,
        )


def _read_jsonl(path: str, limit: int | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if limit is not None and len(rows) >= limit:
                break
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at line {line_number}: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"JSONL line {line_number} is not an object")
            rows.append(flatten_record(record))
    return rows


def _read_jsonl_batches(path: str, batch_size: int) -> Any:
    rows: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at line {line_number}: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"JSONL line {line_number} is not an object")
            rows.append(flatten_record(record))
            if len(rows) >= batch_size:
                yield rows
                rows = []
    if rows:
        yield rows
