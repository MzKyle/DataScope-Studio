from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def public_artifact_names(version: str) -> list[str]:
    return [
        f"DataScope-Studio-v{version}-linux-amd64.deb",
        f"DataScope-Studio-v{version}-linux-x86_64.AppImage",
        f"DataScope-Studio-v{version}-windows-x86_64-setup.exe",
        f"DataScope-Studio-v{version}-macos-aarch64.dmg",
        f"DataScope-Studio-v{version}-macos-x86_64.dmg",
    ]


def load_public_release_metadata(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "packaging/release/public_release.json"
    return json.loads(path.read_text(encoding="utf-8"))


def public_download_version(metadata: dict[str, Any]) -> str:
    version = str(metadata.get("download_version", "")).strip()
    if not version:
        raise RuntimeError("public_release.json is missing download_version")
    return version


def public_release_tag(metadata: dict[str, Any]) -> str:
    version = public_download_version(metadata)
    tag = str(metadata.get("release_tag", "")).strip() or f"v{version}"
    if tag != f"v{version}":
        raise RuntimeError(
            f"public_release.json release_tag {tag} does not match download_version {version}"
        )
    return tag
