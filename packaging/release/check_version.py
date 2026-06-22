#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def read_assignment(path: Path, key: str) -> str:
    pattern = re.compile(rf"^{re.escape(key)}\s*=\s*[\"']([^\"']+)[\"']", re.MULTILINE)
    match = pattern.search(path.read_text(encoding="utf-8"))
    if not match:
        raise RuntimeError(f"Could not find {key!r} in {path}")
    return match.group(1)


def read_cargo_lock_version(path: Path, package_name: str) -> str:
    pattern = re.compile(
        rf'\[\[package\]\]\s+name = "{re.escape(package_name)}"\s+version = "([^"]+)"',
        re.MULTILINE,
    )
    match = pattern.search(path.read_text(encoding="utf-8"))
    if not match:
        raise RuntimeError(f"Could not find package {package_name!r} in {path}")
    return match.group(1)


def collect_versions(repo_root: Path = REPO_ROOT) -> dict[str, str]:
    package_json = json.loads(
        (repo_root / "apps/desktop/package.json").read_text(encoding="utf-8")
    )
    package_lock = json.loads(
        (repo_root / "apps/desktop/package-lock.json").read_text(encoding="utf-8")
    )
    tauri_config = json.loads(
        (repo_root / "apps/desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8")
    )

    return {
        "VERSION": (repo_root / "VERSION").read_text(encoding="utf-8").strip(),
        "desktop package": package_json["version"],
        "desktop lock": package_lock["version"],
        "desktop lock root": package_lock["packages"][""]["version"],
        "Tauri config": tauri_config["version"],
        "Cargo package": read_assignment(
            repo_root / "apps/desktop/src-tauri/Cargo.toml", "version"
        ),
        "Cargo lock": read_cargo_lock_version(
            repo_root / "apps/desktop/src-tauri/Cargo.lock", "datascope-studio"
        ),
        "core package": read_assignment(repo_root / "packages/core/pyproject.toml", "version"),
        "CLI package": read_assignment(repo_root / "packages/cli/pyproject.toml", "version"),
        "API package": read_assignment(repo_root / "services/api/pyproject.toml", "version"),
    }


def validate_versions(versions: dict[str, str], tag: str | None = None) -> str:
    expected = versions["VERSION"]
    mismatches = {name: value for name, value in versions.items() if value != expected}
    if mismatches:
        details = ", ".join(f"{name}={value}" for name, value in mismatches.items())
        raise RuntimeError(f"Version mismatch; expected {expected}: {details}")

    if tag:
        tag_version = tag[1:] if tag.startswith("v") else tag
        if tag_version != expected:
            raise RuntimeError(f"Tag {tag} does not match VERSION {expected}")
    return expected


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate DataScope product versions.")
    parser.add_argument("--tag", help="Optional release tag, for example v0.3.0")
    args = parser.parse_args()

    versions = collect_versions()
    version = validate_versions(versions, args.tag)
    for name, value in versions.items():
        print(f"{name}: {value}")
    print(f"DataScope version {version} is consistent.")


if __name__ == "__main__":
    main()
