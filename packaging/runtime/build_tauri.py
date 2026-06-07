#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DESKTOP_DIR = REPO_ROOT / "apps/desktop"
PRODUCT_NAME = "DataScope Studio"
VERSION = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the host-platform Tauri installer.")
    parser.add_argument("--bundles", default=default_bundles())
    args = parser.parse_args()

    tauri_bundles = build_bundles(args.bundles)
    command = [resolve_npx(), "tauri", "build", "--ci", "--verbose", "--bundles", tauri_bundles]
    env = build_environment(args.bundles)
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=DESKTOP_DIR, check=True, env=env)
    if use_native_macos_dmg(args.bundles):
        create_macos_dmg(cargo_bundle_root(env))


def default_bundles() -> str:
    system = platform.system().lower()
    if system == "linux":
        return "deb,appimage"
    if system == "windows":
        return "nsis"
    if system == "darwin":
        return "dmg"
    raise RuntimeError(f"Unsupported Tauri bundle platform: {platform.system()}")


def build_bundles(requested: str) -> str:
    if use_native_macos_dmg(requested):
        return "app"
    return requested


def use_native_macos_dmg(requested: str) -> bool:
    bundles = {bundle.strip().lower() for bundle in requested.split(",")}
    return platform.system().lower() == "darwin" and "dmg" in bundles


def cargo_bundle_root(env: dict[str, str]) -> Path:
    configured = env.get("CARGO_TARGET_DIR")
    target_dir = Path(configured) if configured else DESKTOP_DIR / "src-tauri/target"
    if not target_dir.is_absolute():
        target_dir = DESKTOP_DIR / target_dir
    return target_dir.resolve() / "release/bundle"


def create_macos_dmg(bundle_root: Path) -> Path:
    macos_dir = bundle_root / "macos"
    apps = sorted(path for path in macos_dir.glob("*.app") if path.is_dir())
    if len(apps) != 1:
        raise RuntimeError(f"Expected one macOS app bundle in {macos_dir}, found {len(apps)}.")

    arch = "aarch64" if platform.machine().lower() in {"arm64", "aarch64"} else "x64"
    output = bundle_root / "dmg" / f"{PRODUCT_NAME}_{VERSION}_{arch}.dmg"
    output.parent.mkdir(parents=True, exist_ok=True)

    app = apps[0]
    staging = Path(tempfile.mkdtemp(prefix=".datascope-dmg-", dir=macos_dir))
    staged_app = staging / app.name
    app.rename(staged_app)
    try:
        os.symlink("/Applications", staging / "Applications", target_is_directory=True)
        command = [
            "hdiutil",
            "create",
            "-volname",
            PRODUCT_NAME,
            "-srcfolder",
            str(staging),
            "-ov",
            "-format",
            "UDZO",
            str(output),
        ]
        print("+ " + " ".join(command), flush=True)
        subprocess.run(command, check=True)
    finally:
        if staged_app.exists():
            staged_app.rename(app)
        shutil.rmtree(staging, ignore_errors=True)

    if not output.is_file():
        raise RuntimeError(f"hdiutil did not create the expected DMG: {output}")
    return output


def resolve_npx() -> str:
    candidates = (
        ["npx.cmd", "npx.exe", "npx"]
        if platform.system().lower() == "windows"
        else ["npx"]
    )
    for candidate in candidates:
        executable = shutil.which(candidate)
        if executable:
            return executable

    raise RuntimeError(
        "Unable to find npx on PATH. Install Node.js/npm before building the Tauri installer."
    )


def build_environment(bundles: str) -> dict[str, str]:
    env = os.environ.copy()
    if platform.system().lower() != "linux" or "appimage" not in bundles.lower():
        return env

    runtime_python = DESKTOP_DIR / "src-tauri/resources/datascope-runtime/python"
    lib_dirs = runtime_library_dirs(runtime_python)
    if not lib_dirs:
        return env

    existing = env.get("LD_LIBRARY_PATH")
    joined = os.pathsep.join(str(path) for path in lib_dirs)
    env["LD_LIBRARY_PATH"] = joined if not existing else joined + os.pathsep + existing
    return env


def runtime_library_dirs(runtime_python: Path) -> list[Path]:
    if not runtime_python.exists():
        return []

    dirs = {
        path.parent.resolve()
        for path in runtime_python.rglob("*")
        if path.is_file() and (".so" in path.name or path.name.endswith(".bin"))
    }
    return sorted(dirs, key=lambda path: str(path))


if __name__ == "__main__":
    main()
