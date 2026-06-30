#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
DESKTOP_DIR = REPO_ROOT / "apps/desktop"
TAURI_DIR = DESKTOP_DIR / "src-tauri"
VENV_DIR = REPO_ROOT / ".venv"
QUALITY_PATTERN = re.compile(
    r"(^|/)\.history(/|$)|"
    r"(^|/)\.venv(/|$)|"
    r"(^|/)node_modules(/|$)|"
    r"(^|/)target(/|$)|"
    r"\.rrd$|\.rbl$|\.zip$|\.sqlite$|\.env$"
)


@dataclass(frozen=True)
class Command:
    name: str
    argv: tuple[str, ...]
    cwd: Path = REPO_ROOT
    env: dict[str, str] = field(default_factory=dict)


def build_command_plan(
    *,
    profile: str,
    python_exe: Path,
    install_desktop_deps: bool,
    include_runtime_build: bool,
    include_tauri_build: bool,
    stability_loops: int,
    health_duration_seconds: int,
) -> list[Command]:
    commands: list[Command] = []
    if install_desktop_deps:
        commands.append(Command("Install desktop dependencies", ("npm", "ci"), DESKTOP_DIR))

    commands.extend(
        [
            Command("Release sanity", (str(python_exe), "packaging/release/sanity_check.py")),
            Command("Python test suite", (str(python_exe), "-m", "pytest", "-q")),
            Command("Desktop test suite", ("npm", "test"), DESKTOP_DIR),
            Command("Desktop production build", ("npm", "run", "build"), DESKTOP_DIR),
            Command("Tauri shell check", ("cargo", "check", "--locked"), TAURI_DIR),
        ]
    )

    if profile == "release":
        commands.append(
            Command(
                "Strict stability suite",
                (str(python_exe), "-m", "pytest", "-q", "tests/stability"),
                env={
                    "DATASCOPE_STRICT_STABILITY": "1",
                    "DATASCOPE_STABILITY_LOOPS": str(stability_loops),
                    "DATASCOPE_HEALTH_DURATION_SECONDS": str(health_duration_seconds),
                },
            )
        )

    if include_tauri_build and not include_runtime_build:
        include_runtime_build = True
    if include_runtime_build:
        commands.append(
            Command("Build bundled Python runtime", ("npm", "run", "runtime:build"), DESKTOP_DIR)
        )
    if include_tauri_build:
        commands.append(
            Command("Build local Tauri installer", ("npm", "run", "tauri:build"), DESKTOP_DIR)
        )
    return commands


def run_acceptance(args: argparse.Namespace) -> None:
    python_exe = (
        rebuild_python_env(dry_run=args.dry_run) if args.rebuild_python_env else select_python()
    )
    check_tool_versions(python_exe, dry_run=args.dry_run)
    run_command(Command("Git whitespace check", ("git", "diff", "--check")), dry_run=args.dry_run)
    check_tracked_artifacts(dry_run=args.dry_run)

    commands = build_command_plan(
        profile=args.profile,
        python_exe=python_exe,
        install_desktop_deps=args.install_desktop_deps,
        include_runtime_build=args.include_runtime_build,
        include_tauri_build=args.include_tauri_build,
        stability_loops=args.stability_loops,
        health_duration_seconds=args.health_duration_seconds,
    )
    for command in commands:
        run_command(command, dry_run=args.dry_run)


def rebuild_python_env(*, dry_run: bool) -> Path:
    if _is_running_from_repo_venv():
        raise RuntimeError(
            "Refusing to delete the active .venv. Run this script with system Python "
            "when using --rebuild-python-env."
        )
    python_exe = _venv_python()
    if dry_run:
        print(f"[dry-run] Rebuild Python environment at {VENV_DIR}")
        return python_exe
    if VENV_DIR.exists():
        shutil.rmtree(VENV_DIR)
    subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], cwd=REPO_ROOT, check=True)
    subprocess.run(
        [str(python_exe), "-m", "pip", "install", "--upgrade", "pip"],
        cwd=REPO_ROOT,
        check=True,
    )
    subprocess.run(
        [str(python_exe), "-m", "pip", "install", "-r", "requirements-dev.txt"],
        cwd=REPO_ROOT,
        check=True,
    )
    return python_exe


def select_python() -> Path:
    python_exe = _venv_python()
    if python_exe.exists():
        return python_exe
    return Path(sys.executable)


def check_tool_versions(python_exe: Path, *, dry_run: bool) -> None:
    if dry_run:
        print(f"[dry-run] Check Python >=3.10 with {python_exe}")
        print("[dry-run] Check Node >=20.19 and Cargo availability")
        return

    python_version = _python_version(python_exe)
    if python_version < (3, 10):
        raise RuntimeError(f"Python >=3.10 is required, got {python_version}")

    node_version = parse_node_version(_capture(("node", "-v"), cwd=REPO_ROOT).strip())
    if node_version < (20, 19, 0):
        rendered = ".".join(str(part) for part in node_version)
        raise RuntimeError(f"Node >=20.19.0 is required, got {rendered}")

    _capture(("cargo", "--version"), cwd=REPO_ROOT)


def check_tracked_artifacts(*, dry_run: bool) -> None:
    if dry_run:
        print("[dry-run] Check tracked generated/local artifacts")
        return
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    offenders = [line for line in result.stdout.splitlines() if QUALITY_PATTERN.search(line)]
    if offenders:
        rendered = "\n".join(offenders[:50])
        raise RuntimeError(f"Tracked generated/local artifacts found:\n{rendered}")


def run_command(command: Command, *, dry_run: bool) -> None:
    rendered = shlex.join(command.argv)
    print(f"\n==> {command.name}")
    print(f"$ {rendered}")
    if dry_run:
        return
    env = os.environ.copy()
    env.update(command.env)
    subprocess.run(command.argv, cwd=command.cwd, env=env, check=True)


def parse_node_version(raw: str) -> tuple[int, int, int]:
    value = raw.strip().removeprefix("v")
    parts = value.split(".")
    if len(parts) < 2:
        raise RuntimeError(f"Unable to parse Node version: {raw}")
    major = int(parts[0])
    minor = int(parts[1])
    patch = int(parts[2]) if len(parts) > 2 else 0
    return major, minor, patch


def _python_version(python_exe: Path) -> tuple[int, int]:
    output = _capture(
        (
            str(python_exe),
            "-c",
            "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
        ),
        cwd=REPO_ROOT,
    )
    major, minor = output.strip().split(".")
    return int(major), int(minor)


def _capture(argv: Sequence[str], *, cwd: Path) -> str:
    result = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, check=True)
    return result.stdout


def _venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts/python.exe"
    return VENV_DIR / "bin/python"


def _is_running_from_repo_venv() -> bool:
    try:
        prefix = Path(sys.prefix).resolve()
        venv = VENV_DIR.resolve()
    except OSError:
        return False
    return prefix == venv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run DataScope Studio strict acceptance gates.")
    parser.add_argument(
        "--profile",
        choices=["pr", "release"],
        default="pr",
        help="pr runs fast automated gates; release also runs opt-in stability tests.",
    )
    parser.add_argument(
        "--rebuild-python-env",
        action="store_true",
        help="Delete and rebuild the repository .venv before running Python gates.",
    )
    parser.add_argument(
        "--install-desktop-deps",
        action="store_true",
        help="Run npm ci in apps/desktop before desktop gates.",
    )
    parser.add_argument(
        "--include-runtime-build",
        action="store_true",
        help="Also run the formal bundled runtime build.",
    )
    parser.add_argument(
        "--include-tauri-build",
        action="store_true",
        help="Also build the local Tauri installer; implies --include-runtime-build.",
    )
    parser.add_argument(
        "--stability-loops",
        type=int,
        default=50,
        help="Number of import/build/query loops for the release stability suite.",
    )
    parser.add_argument(
        "--health-duration-seconds",
        type=int,
        default=1800,
        help="API health-loop duration for the release stability suite.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print gates without running them.")
    args = parser.parse_args()
    if args.stability_loops < 1:
        parser.error("--stability-loops must be >= 1")
    if args.health_duration_seconds < 1:
        parser.error("--health-duration-seconds must be >= 1")
    return args


def main() -> None:
    args = parse_args()
    run_acceptance(args)
    if args.dry_run:
        print("\nDataScope strict acceptance dry-run completed.")
    else:
        print("\nDataScope strict acceptance gates passed.")


if __name__ == "__main__":
    main()
