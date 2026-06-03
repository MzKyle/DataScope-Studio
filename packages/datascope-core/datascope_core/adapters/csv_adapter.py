from __future__ import annotations

from pathlib import Path

import pandas as pd

from datascope_core.inference import detect_time_column, infer_semantic_streams, safe_slug
from datascope_core.models import ConvertRequest, SourceInfo, StreamInfo
from datascope_core.rerun_writer import write_tabular_recording


class CsvAdapter:
    adapter_id = "csv"
    display_name = "CSV"
    supported_extensions = [".csv"]

    def inspect(self, path: str, source_id: str | None = None) -> SourceInfo:
        sample = pd.read_csv(path, nrows=1000)
        row_count = sum(len(chunk) for chunk in pd.read_csv(path, chunksize=100_000))
        return SourceInfo(
            source_id=source_id or f"source_{safe_slug(Path(path).stem)}",
            source_type="csv",
            path=str(path),
            metadata={
                "columns": list(sample.columns),
                "dtypes": {column: str(dtype) for column, dtype in sample.dtypes.items()},
                "rows": max(row_count, 0),
                "sample_rows": len(sample),
                "size_bytes": Path(path).stat().st_size,
            },
        )

    def infer_streams(self, source: SourceInfo) -> list[StreamInfo]:
        frame = pd.read_csv(source.path, nrows=1000)
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
        frame = pd.read_csv(source.path, nrows=limit)
        return {
            "source_id": source.source_id,
            "stream_id": stream_id,
            "columns": list(frame.columns),
            "rows": frame.fillna("").to_dict(orient="records"),
        }

    def convert(self, request: ConvertRequest) -> None:
        frame = pd.read_csv(request.source.path)
        write_tabular_recording(frame, request)
