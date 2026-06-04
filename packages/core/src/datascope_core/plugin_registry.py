from __future__ import annotations

import importlib
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


PLUGIN_MANIFEST = "plugin.yaml"
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(slots=True)
class PluginManifest:
    id: str
    name: str
    version: str
    path: str
    min_datascope_version: str | None = None
    entrypoints: dict[str, dict[str, str]] = field(default_factory=dict)
    permissions: list[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "path": self.path,
            "min_datascope_version": self.min_datascope_version,
            "entrypoints": self.entrypoints,
            "permissions": self.permissions,
            "description": self.description,
        }


def load_plugin_manifest(path: str | Path) -> PluginManifest:
    plugin_path = Path(path).expanduser().resolve()
    manifest_path = plugin_path / PLUGIN_MANIFEST if plugin_path.is_dir() else plugin_path
    if not manifest_path.exists():
        raise ValueError(f"Plugin manifest not found: {manifest_path}")
    with open(manifest_path, "r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError("Plugin manifest must be a YAML object")

    for key in ("id", "name", "version"):
        if not isinstance(payload.get(key), str) or not payload[key].strip():
            raise ValueError(f"Plugin manifest requires non-empty {key}")
    plugin_id = payload["id"].strip()
    if not _ID_PATTERN.match(plugin_id):
        raise ValueError("Plugin id may only contain letters, numbers, dot, underscore, and dash")

    entrypoints = payload.get("entrypoints") or payload.get("entry_points") or {}
    if not isinstance(entrypoints, dict):
        raise ValueError("Plugin entrypoints must be an object")
    normalized_entrypoints: dict[str, dict[str, str]] = {}
    for group, group_entries in entrypoints.items():
        if group not in {"adapters", "templates"}:
            raise ValueError(f"Unsupported plugin entrypoint group: {group}")
        if not isinstance(group_entries, (dict, list)):
            raise ValueError(f"Plugin entrypoints.{group} must be an object or string array")
        normalized_entrypoints[group] = {}
        items = (
            group_entries.items()
            if isinstance(group_entries, dict)
            else ((_entrypoint_name(entrypoint), entrypoint) for entrypoint in group_entries)
        )
        for name, entrypoint in items:
            if not isinstance(name, str) or not isinstance(entrypoint, str):
                raise ValueError(f"Plugin entrypoints.{group} values must be strings")
            _split_entrypoint(entrypoint)
            normalized_entrypoints[group][name] = entrypoint

    permissions = payload.get("permissions") or []
    if not isinstance(permissions, list) or not all(isinstance(item, str) for item in permissions):
        raise ValueError("Plugin permissions must be a string array")

    return PluginManifest(
        id=plugin_id,
        name=payload["name"].strip(),
        version=payload["version"].strip(),
        path=str(manifest_path.parent),
        min_datascope_version=payload.get("min_datascope_version"),
        entrypoints=normalized_entrypoints,
        permissions=permissions,
        description=str(payload.get("description") or ""),
    )


def validate_plugin(
    path: str | Path,
    *,
    import_entrypoints: bool = True,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    manifest = load_plugin_manifest(path)
    errors: list[str] = []
    loaded: dict[str, list[str]] = {"adapters": [], "templates": []}
    if import_entrypoints:
        try:
            subprocess_result = _validate_entrypoints_subprocess(manifest.path, timeout_seconds)
            loaded = subprocess_result["loaded"]
            errors.extend(subprocess_result["errors"])
        except subprocess.TimeoutExpired:
            errors.append(f"Plugin entrypoint validation timed out after {timeout_seconds:g}s")
    return {
        "valid": not errors,
        "manifest": manifest.to_dict(),
        "loaded": loaded,
        "errors": errors,
    }


def load_entrypoint(plugin_path: str | Path, entrypoint: str) -> Any:
    module_name, object_name = _split_entrypoint(entrypoint)
    plugin_root = str(Path(plugin_path).expanduser().resolve())
    added = False
    if plugin_root not in sys.path:
        sys.path.insert(0, plugin_root)
        added = True
    try:
        module = importlib.import_module(module_name)
        target: Any = module
        for part in object_name.split("."):
            target = getattr(target, part)
        return target
    finally:
        if added:
            try:
                sys.path.remove(plugin_root)
            except ValueError:
                pass


def instantiate_entrypoint(plugin_path: str | Path, entrypoint: str) -> Any:
    target = load_entrypoint(plugin_path, entrypoint)
    return target() if isinstance(target, type) else target


def _split_entrypoint(entrypoint: str) -> tuple[str, str]:
    if ":" not in entrypoint:
        raise ValueError(f"Invalid entrypoint {entrypoint!r}; expected module:object")
    module_name, object_name = entrypoint.split(":", 1)
    if not module_name or not object_name:
        raise ValueError(f"Invalid entrypoint {entrypoint!r}; expected module:object")
    return module_name, object_name


def _entrypoint_name(entrypoint: str) -> str:
    if not isinstance(entrypoint, str):
        return ""
    _, object_name = _split_entrypoint(entrypoint)
    return object_name.rsplit(".", 1)[-1]


def _validate_entrypoints_subprocess(plugin_path: str | Path, timeout_seconds: float) -> dict[str, Any]:
    code = """
import json
import sys
from datascope_core.plugin_registry import load_entrypoint, load_plugin_manifest

manifest = load_plugin_manifest(sys.argv[1])
loaded = {"adapters": [], "templates": []}
errors = []
for group, entries in manifest.entrypoints.items():
    for name, entrypoint in entries.items():
        try:
            load_entrypoint(manifest.path, entrypoint)
            loaded.setdefault(group, []).append(name)
        except Exception as exc:
            errors.append(f"{group}.{name}: {exc}")
print(json.dumps({"loaded": loaded, "errors": errors}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(plugin_path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds,
    )
    if result.returncode != 0 and not result.stdout.strip():
        return {"loaded": {"adapters": [], "templates": []}, "errors": [(result.stderr or "Plugin validation failed").strip()]}
    try:
        payload = yaml.safe_load(result.stdout) or {}
    except Exception as exc:
        return {"loaded": {"adapters": [], "templates": []}, "errors": [f"Invalid validation output: {exc}"]}
    return {
        "loaded": payload.get("loaded", {"adapters": [], "templates": []}),
        "errors": payload.get("errors", []),
    }
