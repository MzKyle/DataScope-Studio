from __future__ import annotations

import csv
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from datascope_core.inference import detect_time_column, infer_semantic_streams, safe_slug
from datascope_core.models import ConvertRequest, SourceInfo, StreamInfo, TEXT_TABLE_EXTENSIONS
from datascope_core.rerun_writer import write_tabular_chunks


DELIMITER_SEPARATORS = {
    "comma": ",",
    "tab": "\t",
    "semicolon": ";",
    "pipe": "|",
}
SUPPORTED_DELIMITERS = {"auto", *DELIMITER_SEPARATORS.keys(), "whitespace"}


class TextTableAdapter:
    adapter_id = "text_table"
    display_name = "Text Table / Log"
    supported_extensions = sorted(TEXT_TABLE_EXTENSIONS)

    def inspect(
        self,
        path: str,
        source_id: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> SourceInfo:
        text_config = _resolve_text_config(path, options)
        sample = read_text_table_path(path, text_config=text_config, nrows=1000)
        row_count = _row_count(path, text_config)
        return SourceInfo(
            source_id=source_id or f"source_{safe_slug(Path(path).stem)}",
            source_type="text_table",
            path=str(path),
            metadata={
                "columns": list(sample.columns),
                "dtypes": {column: str(dtype) for column, dtype in sample.dtypes.items()},
                "rows": max(row_count, 0),
                "sample_rows": len(sample),
                "size_bytes": Path(path).stat().st_size,
                "import_options": {"text": text_config},
                "text": text_config,
            },
        )

    def infer_streams(self, source: SourceInfo) -> list[StreamInfo]:
        frame = read_text_table_source(source, nrows=1000)
        text_config = _source_text_config(source)
        time_key = (
            "line_number"
            if text_config.get("mode") == "log" and "line_number" in frame.columns
            else detect_time_column(list(frame.columns), frame)
        )
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
        frame = read_text_table_source(source, nrows=limit)
        return {
            "source_id": source.source_id,
            "stream_id": stream_id,
            "columns": list(frame.columns),
            "rows": frame.fillna("").to_dict(orient="records"),
        }

    def convert(self, request: ConvertRequest) -> None:
        write_tabular_chunks(
            _read_text_batches(
                request.source.path,
                _source_text_config(request.source),
                batch_size=50_000,
            ),
            request,
        )


def read_text_table_source(source: SourceInfo, *, nrows: int | None = None) -> pd.DataFrame:
    return read_text_table_path(
        source.path,
        text_config=_source_text_config(source),
        nrows=nrows,
    )


def read_text_table_path(
    path: str,
    *,
    text_config: dict[str, Any],
    nrows: int | None = None,
) -> pd.DataFrame:
    if text_config.get("mode") == "log":
        return pd.DataFrame(_read_log_rows(path, limit=nrows))
    return pd.read_csv(
        path,
        nrows=nrows,
        **_read_text_kwargs(text_config),
    )


def _read_text_batches(
    path: str,
    text_config: dict[str, Any],
    batch_size: int,
) -> Iterable[pd.DataFrame]:
    if text_config.get("mode") == "log":
        rows: list[dict[str, Any]] = []
        for row in _read_log_rows(path, limit=None):
            rows.append(row)
            if len(rows) >= batch_size:
                yield pd.DataFrame(rows)
                rows = []
        if rows:
            yield pd.DataFrame(rows)
        return

    yield from pd.read_csv(
        path,
        chunksize=batch_size,
        **_read_text_kwargs(text_config),
    )


def _source_text_config(source: SourceInfo) -> dict[str, Any]:
    config = source.metadata.get("text")
    if isinstance(config, dict):
        return config
    import_options = source.metadata.get("import_options")
    if isinstance(import_options, dict) and isinstance(import_options.get("text"), dict):
        return import_options["text"]
    return _resolve_text_config(source.path, None)


def _resolve_text_config(
    path: str,
    options: dict[str, Any] | None,
) -> dict[str, Any]:
    text_options = options.get("text", options) if isinstance(options, dict) else {}
    header_mode = str(text_options.get("header_mode") or "auto")
    if header_mode not in {"auto", "header", "no_header"}:
        raise ValueError(f"Unsupported text header mode: {header_mode}")

    delimiter = str(text_options.get("delimiter") or "auto")
    if delimiter not in SUPPORTED_DELIMITERS:
        raise ValueError(f"Unsupported text delimiter: {delimiter}")

    rows = _sample_text_rows(path)
    resolved_delimiter = _resolve_delimiter(path, rows, delimiter)
    if resolved_delimiter is None:
        return _log_config(header_mode, delimiter)

    parsed_rows = _parse_rows(rows, resolved_delimiter)
    column_count = _stable_column_count(parsed_rows)
    if column_count is None:
        return _log_config(header_mode, delimiter)

    resolved_header_mode = (
        _detect_header_mode(parsed_rows)
        if header_mode == "auto"
        else header_mode
    )
    column_names = _column_names(text_options, column_count, resolved_header_mode)
    return {
        "mode": "table",
        "delimiter": delimiter,
        "resolved_delimiter": resolved_delimiter,
        "header_mode": header_mode,
        "resolved_header_mode": resolved_header_mode,
        "column_names": column_names,
    }


def _log_config(header_mode: str, delimiter: str) -> dict[str, Any]:
    return {
        "mode": "log",
        "delimiter": delimiter,
        "resolved_delimiter": None,
        "header_mode": header_mode,
        "resolved_header_mode": "no_header",
        "column_names": ["line_number", "message"],
    }


def _column_names(
    text_options: dict[str, Any],
    column_count: int,
    resolved_header_mode: str,
) -> list[str]:
    raw_names = text_options.get("column_names") or []
    if isinstance(raw_names, str):
        raw_names = raw_names.split(",")
    column_names = [str(name).strip() for name in raw_names]
    if column_names:
        if len(column_names) != column_count:
            raise ValueError(
                "Text column name count does not match the source: "
                f"expected {column_count}, got {len(column_names)}"
            )
        if any(not name for name in column_names):
            raise ValueError("Text column names cannot be empty")
        if len(set(column_names)) != len(column_names):
            raise ValueError("Text column names must be unique")
    elif resolved_header_mode == "no_header":
        column_names = [f"column_{index}" for index in range(1, column_count + 1)]
    return column_names


def _resolve_delimiter(
    path: str,
    rows: list[str],
    requested: str,
) -> str | None:
    if requested != "auto":
        return requested if _stable_column_count(_parse_rows(rows, requested)) is not None else None
    if Path(path).suffix.lower() == ".tsv":
        return "tab" if _stable_column_count(_parse_rows(rows, "tab")) is not None else None
    candidates = ["tab", "comma", "semicolon", "pipe", "whitespace"]
    scored = []
    for delimiter in candidates:
        parsed = _parse_rows(rows, delimiter)
        column_count = _stable_column_count(parsed)
        if (
            column_count is not None
            and (delimiter != "whitespace" or _whitespace_rows_look_tabular(parsed))
        ):
            scored.append((column_count, delimiter))
    if not scored:
        return None
    return sorted(scored, key=lambda item: (item[0], item[1]), reverse=True)[0][1]


def _stable_column_count(rows: list[list[str]]) -> int | None:
    nonempty = [row for row in rows if row]
    if len(nonempty) < 2:
        return None
    counts = [len(row) for row in nonempty]
    common_count = max(set(counts), key=counts.count)
    if common_count <= 1:
        return None
    if counts.count(common_count) / len(counts) < 0.9:
        return None
    return common_count


def _whitespace_rows_look_tabular(rows: list[list[str]]) -> bool:
    nonempty = [row for row in rows if row]
    if not nonempty:
        return False
    numeric_rows = sum(any(_is_number(value) for value in row) for row in nonempty)
    return numeric_rows / len(nonempty) >= 0.5


def _sample_text_rows(path: str, limit: int = 25) -> list[str]:
    rows: list[str] = []
    with open(path, "r", encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            rows.append(stripped)
            if len(rows) >= limit:
                break
    return rows


def _parse_rows(rows: list[str], delimiter: str) -> list[list[str]]:
    parsed: list[list[str]] = []
    for row in rows:
        if delimiter == "whitespace":
            parsed.append(re.split(r"\s+", row.strip()))
            continue
        separator = DELIMITER_SEPARATORS[delimiter]
        parsed.extend(csv.reader([row], delimiter=separator))
    return parsed


def _detect_header_mode(rows: list[list[str]]) -> str:
    if not rows:
        return "header"
    first = rows[0]
    if first and all(_is_number(value) for value in first):
        return "no_header"
    if len(rows) > 1:
        first_numeric = sum(_is_number(value) for value in first)
        second_numeric = sum(_is_number(value) for value in rows[1])
        if first_numeric < second_numeric:
            return "header"
    try:
        sample = "\n".join(",".join(row) for row in rows)
        return "header" if csv.Sniffer().has_header(sample) else "no_header"
    except csv.Error:
        return "header"


def _read_text_kwargs(config: dict[str, Any]) -> dict[str, Any]:
    delimiter = str(config["resolved_delimiter"])
    kwargs: dict[str, Any] = {
        "encoding": "utf-8-sig",
        "encoding_errors": "replace",
        "header": 0 if config.get("resolved_header_mode") == "header" else None,
    }
    if delimiter == "whitespace":
        kwargs["sep"] = r"\s+"
        kwargs["engine"] = "python"
    else:
        kwargs["sep"] = DELIMITER_SEPARATORS[delimiter]
    column_names = config.get("column_names")
    if column_names:
        kwargs["names"] = list(column_names)
    return kwargs


def _read_log_rows(path: str, limit: int | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8-sig", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            if limit is not None and len(rows) >= limit:
                break
            message = line.rstrip("\r\n")
            if not message.strip():
                continue
            rows.append({"line_number": line_number, "message": message})
    return rows


def _row_count(path: str, text_config: dict[str, Any]) -> int:
    if text_config.get("mode") == "log":
        return len(_read_log_rows(path, limit=None))
    return sum(
        len(chunk)
        for chunk in pd.read_csv(
            path,
            chunksize=100_000,
            **_read_text_kwargs(text_config),
        )
    )


def _is_number(value: str) -> bool:
    try:
        float(value.strip())
    except ValueError:
        return False
    return True
