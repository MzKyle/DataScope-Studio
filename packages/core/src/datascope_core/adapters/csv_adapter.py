from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import pandas as pd

from datascope_core.inference import detect_time_column, infer_semantic_streams, safe_slug
from datascope_core.models import ConvertRequest, SourceInfo, StreamInfo
from datascope_core.rerun_writer import write_tabular_chunks


class CsvAdapter:
    adapter_id = "csv"
    display_name = "CSV"
    supported_extensions = [".csv"]

    def inspect(
        self,
        path: str,
        source_id: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> SourceInfo:
        csv_config = _resolve_csv_config(path, options)
        sample = pd.read_csv(path, nrows=1000, **_read_csv_kwargs(csv_config))
        row_count = sum(
            len(chunk)
            for chunk in pd.read_csv(
                path,
                chunksize=100_000,
                **_read_csv_kwargs(csv_config),
            )
        )
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
                "import_options": {"csv": csv_config},
                "csv": csv_config,
            },
        )

    def infer_streams(self, source: SourceInfo) -> list[StreamInfo]:
        frame = read_csv_source(source, nrows=1000)
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
        frame = read_csv_source(source, nrows=limit)
        return {
            "source_id": source.source_id,
            "stream_id": stream_id,
            "columns": list(frame.columns),
            "rows": frame.fillna("").to_dict(orient="records"),
        }

    def convert(self, request: ConvertRequest) -> None:
        write_tabular_chunks(
            pd.read_csv(
                request.source.path,
                chunksize=50_000,
                **_read_csv_kwargs(_source_csv_config(request.source)),
            ),
            request,
        )


def read_csv_source(source: SourceInfo, *, nrows: int | None = None) -> pd.DataFrame:
    return pd.read_csv(
        source.path,
        nrows=nrows,
        **_read_csv_kwargs(_source_csv_config(source)),
    )


def _source_csv_config(source: SourceInfo) -> dict[str, Any]:
    config = source.metadata.get("csv")
    if isinstance(config, dict):
        return config
    import_options = source.metadata.get("import_options")
    if isinstance(import_options, dict) and isinstance(import_options.get("csv"), dict):
        return import_options["csv"]
    return _resolve_csv_config(source.path, None)


def _resolve_csv_config(
    path: str,
    options: dict[str, Any] | None,
) -> dict[str, Any]:
    csv_options = options.get("csv", options) if isinstance(options, dict) else {}
    header_mode = str(csv_options.get("header_mode") or "auto")
    if header_mode not in {"auto", "header", "no_header"}:
        raise ValueError(f"Unsupported CSV header mode: {header_mode}")

    rows = _sample_csv_rows(path)
    column_count = len(rows[0]) if rows else 0
    if column_count == 0:
        raise ValueError("CSV source does not contain any columns")
    if any(len(row) != column_count for row in rows):
        raise ValueError("CSV source has inconsistent column counts in the inspected sample")

    resolved_header_mode = (
        _detect_header_mode(rows)
        if header_mode == "auto"
        else header_mode
    )
    raw_names = csv_options.get("column_names") or []
    if isinstance(raw_names, str):
        raw_names = raw_names.split(",")
    column_names = [str(name).strip() for name in raw_names]
    if column_names:
        if len(column_names) != column_count:
            raise ValueError(
                "CSV column name count does not match the source: "
                f"expected {column_count}, got {len(column_names)}"
            )
        if any(not name for name in column_names):
            raise ValueError("CSV column names cannot be empty")
        if len(set(column_names)) != len(column_names):
            raise ValueError("CSV column names must be unique")
    elif resolved_header_mode == "no_header":
        column_names = [f"column_{index}" for index in range(1, column_count + 1)]

    return {
        "header_mode": header_mode,
        "resolved_header_mode": resolved_header_mode,
        "column_names": column_names,
    }


def _read_csv_kwargs(config: dict[str, Any]) -> dict[str, Any]:
    resolved_header_mode = config.get("resolved_header_mode") or config.get("header_mode")
    kwargs: dict[str, Any] = {
        "header": 0 if resolved_header_mode == "header" else None,
    }
    column_names = config.get("column_names")
    if column_names:
        kwargs["names"] = list(column_names)
    return kwargs


def _sample_csv_rows(path: str, limit: int = 20) -> list[list[str]]:
    rows: list[list[str]] = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if not row or all(not value.strip() for value in row):
                continue
            rows.append(row)
            if len(rows) >= limit:
                break
    return rows


def _detect_header_mode(rows: list[list[str]]) -> str:
    if not rows:
        return "header"
    first = rows[0]
    if first and all(_is_number(value) for value in first):
        return "no_header"
    try:
        sample = "\n".join(",".join(row) for row in rows)
        return "header" if csv.Sniffer().has_header(sample) else "no_header"
    except csv.Error:
        return "header"


def _is_number(value: str) -> bool:
    try:
        float(value.strip())
    except ValueError:
        return False
    return True
