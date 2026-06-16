from __future__ import annotations

import glob
import hashlib
import json
import os
import shutil
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from datascope_core.adapters.ros2_db3_adapter import metadata_references_db3
from datascope_core.models import SourceInfo


DISK_MARGIN_MIN_BYTES = 512 * 1024 * 1024


def source_info_from_row(row: dict[str, Any]) -> SourceInfo:
    return SourceInfo(
        source_id=row["id"],
        source_type=row["type"],
        path=row["uri"],
        metadata=row.get("metadata", {}),
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def recording_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = row_to_dict(row)
    result["tags"] = json.loads(result.pop("tags_json") or "[]")
    result["params"] = json.loads(result.pop("params_json") or "{}")
    return result


def job_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = row_to_dict(row)
    result["payload"] = json.loads(result.pop("payload_json") or "{}")
    result["result"] = json.loads(result.pop("result_json")) if result.get("result_json") else None
    result["error"] = json.loads(result.pop("error_json")) if result.get("error_json") else None
    return result


def plugin_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = row_to_dict(row)
    result["manifest"] = json.loads(result.pop("manifest_json") or "{}")
    return result


def template_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = row_to_dict(row)
    result["manifest"] = json.loads(result.pop("manifest_json") or "{}")
    result["enabled"] = bool(result["enabled"])
    return result


def mapping_template_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = row_to_dict(row)
    result["config"] = json.loads(result.pop("config_json") or "{}")
    result["enabled"] = bool(result["enabled"])
    return result


def resolve_patterns(patterns: list[str]) -> list[Path]:
    resolved: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        matches = glob.glob(str(Path(pattern).expanduser()), recursive=True)
        if not matches and Path(pattern).expanduser().exists():
            matches = [str(Path(pattern).expanduser())]
        for match in matches:
            path = Path(match).expanduser().resolve()
            if path in seen:
                continue
            seen.add(path)
            resolved.append(path)
    return sorted(resolved, key=str)


def artifact_paths(manifest: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for source in manifest.get("sources", []):
        if source.get("uri"):
            paths.append(source["uri"])
    for mapping in manifest.get("mappings", []):
        if mapping.get("path"):
            paths.append(mapping["path"])
    for recording in manifest.get("recordings", []):
        for key in ("path", "blueprint_path"):
            if recording.get(key):
                paths.append(recording[key])
    for export in manifest.get("query_exports", []):
        if export.get("path"):
            paths.append(export["path"])
    return paths


def archive_name(project_path: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_path.resolve()))
    except ValueError:
        return f"external/{path.name}"


def safe_extract_zip(archive: zipfile.ZipFile, destination: Path) -> None:
    destination_root = destination.resolve()
    for member in archive.infolist():
        member_path = destination / member.filename
        resolved = member_path.resolve()
        if os.path.commonpath([str(destination_root), str(resolved)]) != str(destination_root):
            raise ValueError(f"Unsafe project package path: {member.filename}")
        if member.is_dir():
            resolved.mkdir(parents=True, exist_ok=True)
            continue
        resolved.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(member) as source, open(resolved, "wb") as target:
            shutil.copyfileobj(source, target)


def relocated_artifact_path(
    path_value: Any,
    original_project_path: Path,
    project_path: Path,
) -> str | None:
    if not path_value:
        return None
    original = Path(str(path_value))
    try:
        relative_path = original.resolve().relative_to(original_project_path.resolve())
    except (OSError, RuntimeError, ValueError):
        relative_path = Path("external") / original.name
    return str(project_path / relative_path)


def json_object(value: Any, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return dict(fallback or {})


def json_object_text(value: Any, fallback: Any = None) -> str:
    return json.dumps(
        json_object(value, fallback if isinstance(fallback, dict) else {}),
        ensure_ascii=False,
    )


def json_array_text(value: Any, fallback: Any = None) -> str:
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return json.dumps(parsed, ensure_ascii=False)
        except json.JSONDecodeError:
            pass
    if isinstance(fallback, list):
        return json.dumps(fallback, ensure_ascii=False)
    return "[]"


def source_checksum(path: Path) -> str:
    if path.is_file():
        return _sha256(path)
    digest = hashlib.sha256()
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        digest.update(str(child.relative_to(path)).encode("utf-8"))
        with open(child, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def source_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())


def copy_parent_sidecars(source_path: Path, raw_dir: Path) -> None:
    for name in ("annotations.json", "predictions.json"):
        source_sidecar = source_path.parent / name
        if source_sidecar.exists() and source_sidecar.is_file():
            shutil.copy2(source_sidecar, raw_dir / name)
    metadata_path = source_path.parent / "metadata.yaml"
    if source_path.suffix.lower() == ".db3" and metadata_references_db3(
        metadata_path,
        source_path,
    ):
        shutil.copy2(metadata_path, raw_dir / metadata_path.name)


def safe_output_name(value: str) -> str:
    return "".join(
        character if character.isalnum() or character in {"_", "-"} else "_"
        for character in value
    )


def source_output_name(value: str | Path) -> str:
    path = Path(value)
    return path.name if path.is_dir() else path.stem


def disk_estimate(
    operation: str,
    estimated_bytes: int,
    destination: Path,
    *,
    confidence: str,
    warnings: list[str],
) -> dict[str, Any]:
    margin = max(DISK_MARGIN_MIN_BYTES, int(estimated_bytes * 0.1))
    required = estimated_bytes + margin
    probe = destination.expanduser()
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        free = shutil.disk_usage(probe).free
    except OSError:
        free = None
        warnings = [*warnings, "Free disk space could not be determined."]
    return {
        "kind": operation,
        "estimated": estimated_bytes,
        "margin": margin,
        "required": required,
        "free": free,
        "confidence": confidence,
        "sufficient": None if free is None else free >= required,
        "warnings": warnings,
    }


def structured_error(exc: Exception) -> dict[str, Any]:
    code = getattr(exc, "code", "job_failed")
    result = {"code": str(code), "message": str(exc), "type": type(exc).__name__}
    estimate = getattr(exc, "estimate", None)
    if isinstance(estimate, dict):
        result["estimate"] = estimate
    source_id = getattr(exc, "source_id", None)
    if source_id:
        result["source_id"] = source_id
    output_name = getattr(exc, "output_name", None)
    if output_name:
        result["output_name"] = output_name
    paths = getattr(exc, "paths", None)
    if isinstance(paths, list):
        result["paths"] = paths
    validation = getattr(exc, "report", None)
    if isinstance(validation, dict):
        result["validation"] = validation
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
