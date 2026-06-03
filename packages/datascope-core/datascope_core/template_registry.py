from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


TEMPLATE_MANIFEST = "template.yaml"
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


BUILTIN_TEMPLATES = [
    {
        "id": "sensor_monitor",
        "name": "Sensor Monitor",
        "version": "1.0.0",
        "app_id": "datascope.sensor_monitor.v1",
        "description": "Scalar, state, and log monitoring for CSV and JSONL sources.",
        "source": "builtin",
    },
    {
        "id": "cv_detection",
        "name": "CV Detection",
        "version": "1.0.0",
        "app_id": "datascope.cv_detection.v1",
        "description": "Image, detection boxes, keypoints, masks, and scores.",
        "source": "builtin",
    },
    {
        "id": "robotics_debug",
        "name": "Robotics Debug",
        "version": "1.0.0",
        "app_id": "datascope.robotics_debug.v1",
        "description": "MCAP and ROS robotics debugging layout.",
        "source": "builtin",
    },
    {
        "id": "experiment_compare",
        "name": "Experiment Compare",
        "version": "1.0.0",
        "app_id": "datascope.experiment_compare.v1",
        "description": "Multi-run comparison for scalar and state query results.",
        "source": "builtin",
    },
]


@dataclass(slots=True)
class TemplateManifest:
    id: str
    name: str
    version: str
    app_id: str
    path: str | None = None
    description: str = ""
    source: str = "local"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "app_id": self.app_id,
            "path": self.path,
            "description": self.description,
            "source": self.source,
        }


def load_template_manifest(path: str | Path) -> TemplateManifest:
    template_path = Path(path).expanduser().resolve()
    manifest_path = template_path / TEMPLATE_MANIFEST if template_path.is_dir() else template_path
    if not manifest_path.exists():
        raise ValueError(f"Template manifest not found: {manifest_path}")
    with open(manifest_path, "r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError("Template manifest must be a YAML object")
    if "template" in payload:
        payload = payload["template"] or {}
    if not isinstance(payload, dict):
        raise ValueError("Template manifest template section must be an object")

    for key in ("id", "name", "version", "app_id"):
        if not isinstance(payload.get(key), str) or not payload[key].strip():
            raise ValueError(f"Template manifest requires non-empty {key}")
    template_id = payload["id"].strip()
    if not _ID_PATTERN.match(template_id):
        raise ValueError("Template id may only contain letters, numbers, dot, underscore, and dash")
    return TemplateManifest(
        id=template_id,
        name=payload["name"].strip(),
        version=payload["version"].strip(),
        app_id=payload["app_id"].strip(),
        path=str(manifest_path),
        description=str(payload.get("description") or ""),
        source=str(payload.get("source") or "local"),
    )


def validate_template(path: str | Path) -> dict[str, Any]:
    manifest = load_template_manifest(path)
    return {"valid": True, "template": manifest.to_dict(), "errors": []}
