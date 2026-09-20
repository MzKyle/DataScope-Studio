#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from release_manifest import (  # noqa: E402
    load_public_release_metadata,
    public_artifact_names,
    public_download_version,
    public_release_tag,
)

PUBLIC_RELEASE_DOCS = (
    Path("README.md"),
    Path("README.zh-CN.md"),
    Path("docs/guide/package-install.md"),
)


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


def validate_public_release_docs(
    repo_root: Path = REPO_ROOT,
    *,
    metadata: dict[str, object] | None = None,
    tag: str | None = None,
) -> str:
    metadata = dict(metadata or load_public_release_metadata(repo_root))
    download_version = public_download_version(metadata)
    release_tag = public_release_tag(metadata)
    if tag:
        tag_version = tag[1:] if tag.startswith("v") else tag
        if tag_version != download_version:
            raise RuntimeError(
                "Public release metadata must match the release tag before publishing; "
                f"metadata={release_tag}, tag={tag}"
            )

    product_version = (repo_root / "VERSION").read_text(encoding="utf-8").strip()
    expected_names = public_artifact_names(download_version)
    stale_names = (
        public_artifact_names(product_version)
        if product_version and product_version != download_version
        else []
    )
    for relative_path in PUBLIC_RELEASE_DOCS:
        text = (repo_root / relative_path).read_text(encoding="utf-8")
        missing = [name for name in expected_names if name not in text]
        if missing:
            raise RuntimeError(
                f"{relative_path} does not list public installer artifacts for {release_tag}: "
                + ", ".join(missing)
            )
        if release_tag not in text:
            raise RuntimeError(f"{relative_path} does not mention public release {release_tag}")
        stale = [name for name in stale_names if name in text]
        if stale:
            raise RuntimeError(
                f"{relative_path} still references unreleased installer artifacts: "
                + ", ".join(stale)
            )
    return download_version


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate DataScope product versions.")
    parser.add_argument("--tag", help="Optional release tag, for example v0.3.0")
    args = parser.parse_args()

    versions = collect_versions()
    version = validate_versions(versions, args.tag)
    public_version = validate_public_release_docs(tag=args.tag)
    for name, value in versions.items():
        print(f"{name}: {value}")
    print(f"DataScope version {version} is consistent.")
    print(f"Public installer documentation targets v{public_version}.")


if __name__ == "__main__":
    main()
