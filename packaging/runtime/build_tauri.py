#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DESKTOP_DIR = REPO_ROOT / "apps/desktop"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the host-platform Tauri installer.")
    parser.add_argument("--bundles", default=default_bundles())
    args = parser.parse_args()

    command = [resolve_npx(), "tauri", "build", "--ci", "--verbose", "--bundles", args.bundles]
    env = build_environment(args.bundles)
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=DESKTOP_DIR, check=True, env=env)


def default_bundles() -> str:
    system = platform.system().lower()
    if system == "linux":
        return "deb,appimage"
    if system == "windows":
        return "msi"
    if system == "darwin":
        return "dmg"
    raise RuntimeError(f"Unsupported Tauri bundle platform: {platform.system()}")


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
