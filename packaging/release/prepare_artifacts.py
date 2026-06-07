#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VERSION = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()


def public_artifact_names(version: str) -> list[str]:
    return [
        f"DataScope-Studio-v{version}-linux-amd64.deb",
        f"DataScope-Studio-v{version}-linux-x86_64.AppImage",
        f"DataScope-Studio-v{version}-windows-x86_64-setup.exe",
        f"DataScope-Studio-v{version}-macos-aarch64.dmg",
        f"DataScope-Studio-v{version}-macos-x86_64.dmg",
    ]


def find_one(root: Path, predicate, description: str) -> Path:
    matches = sorted(path for path in root.rglob("*") if path.is_file() and predicate(path))
    if len(matches) != 1:
        rendered = ", ".join(str(path) for path in matches) or "none"
        raise RuntimeError(
            f"Expected one {description} in {root}, found {len(matches)}: {rendered}"
        )
    return matches[0]


def validate_runtime_architecture(manifest_path: Path, arch: str) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    machine = str(manifest.get("machine", "")).lower()
    aliases = {
        "x86_64": {"x86_64", "amd64"},
        "aarch64": {"aarch64", "arm64"},
    }
    if arch not in aliases:
        raise RuntimeError(f"Unsupported release architecture: {arch}")
    if machine not in aliases[arch]:
        raise RuntimeError(
            f"Runtime architecture {machine or 'unknown'} does not match release architecture {arch}"
        )


def stage_artifacts(
    input_dir: Path,
    output_dir: Path,
    platform_name: str,
    arch: str,
    version: str,
    runtime_manifest: Path,
) -> list[Path]:
    validate_runtime_architecture(runtime_manifest, arch)
    output_dir.mkdir(parents=True, exist_ok=True)

    if platform_name == "linux":
        if arch != "x86_64":
            raise RuntimeError("Linux release artifacts currently support x86_64 only")
        sources = [
            (
                find_one(input_dir, lambda path: path.name.endswith(".deb"), "Debian package"),
                f"DataScope-Studio-v{version}-linux-amd64.deb",
            ),
            (
                find_one(input_dir, lambda path: path.name.endswith(".AppImage"), "AppImage"),
                f"DataScope-Studio-v{version}-linux-x86_64.AppImage",
            ),
        ]
    elif platform_name == "windows":
        if arch != "x86_64":
            raise RuntimeError("Windows release artifacts currently support x86_64 only")
        sources = [
            (
                find_one(
                    input_dir,
                    lambda path: path.name.lower().endswith("-setup.exe"),
                    "NSIS setup executable",
                ),
                f"DataScope-Studio-v{version}-windows-x86_64-setup.exe",
            )
        ]
    elif platform_name == "macos":
        sources = [
            (
                find_one(input_dir, lambda path: path.name.endswith(".dmg"), "macOS disk image"),
                f"DataScope-Studio-v{version}-macos-{arch}.dmg",
            )
        ]
    else:
        raise RuntimeError(f"Unsupported release platform: {platform_name}")

    staged: list[Path] = []
    for source, name in sources:
        destination = output_dir / name
        shutil.copy2(source, destination)
        staged.append(destination)
    return staged


def write_checksums(directory: Path, version: str) -> Path:
    expected = public_artifact_names(version)
    missing = [name for name in expected if not (directory / name).is_file()]
    extras = sorted(
        path.name
        for path in directory.iterdir()
        if path.is_file() and path.name != "SHA256SUMS.txt" and path.name not in expected
    )
    if missing or extras:
        raise RuntimeError(f"Invalid release artifact set; missing={missing}, extras={extras}")

    lines = []
    for name in expected:
        digest = hashlib.sha256((directory / name).read_bytes()).hexdigest()
        lines.append(f"{digest}  {name}")
    checksum_path = directory / "SHA256SUMS.txt"
    checksum_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return checksum_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare DataScope release artifacts.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    stage = subparsers.add_parser("stage", help="Validate and rename one platform's bundles.")
    stage.add_argument("--input", type=Path, required=True)
    stage.add_argument("--output", type=Path, required=True)
    stage.add_argument("--platform", choices=["linux", "windows", "macos"], required=True)
    stage.add_argument("--arch", choices=["x86_64", "aarch64"], required=True)
    stage.add_argument("--runtime-manifest", type=Path, required=True)
    stage.add_argument("--version", default=DEFAULT_VERSION)

    checksums = subparsers.add_parser(
        "checksums", help="Validate the complete artifact set and write SHA256SUMS.txt."
    )
    checksums.add_argument("--directory", type=Path, required=True)
    checksums.add_argument("--version", default=DEFAULT_VERSION)

    args = parser.parse_args()
    if args.command == "stage":
        staged = stage_artifacts(
            args.input,
            args.output,
            args.platform,
            args.arch,
            args.version,
            args.runtime_manifest,
        )
        for path in staged:
            print(path)
    else:
        print(write_checksums(args.directory, args.version))


if __name__ == "__main__":
    main()
