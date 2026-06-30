from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "packaging/release/strict_acceptance.py"
SPEC = importlib.util.spec_from_file_location("strict_acceptance", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
strict_acceptance = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = strict_acceptance
SPEC.loader.exec_module(strict_acceptance)


def test_pr_profile_runs_fast_quality_gates_only() -> None:
    plan = strict_acceptance.build_command_plan(
        profile="pr",
        python_exe=Path("/python"),
        install_desktop_deps=False,
        include_runtime_build=False,
        include_tauri_build=False,
        stability_loops=50,
        health_duration_seconds=1800,
    )

    names = [command.name for command in plan]

    assert names == [
        "Release sanity",
        "Python test suite",
        "Desktop test suite",
        "Desktop production build",
        "Tauri shell check",
    ]


def test_release_profile_enables_strict_stability_suite() -> None:
    plan = strict_acceptance.build_command_plan(
        profile="release",
        python_exe=Path("/python"),
        install_desktop_deps=True,
        include_runtime_build=False,
        include_tauri_build=False,
        stability_loops=7,
        health_duration_seconds=11,
    )

    stability = next(command for command in plan if command.name == "Strict stability suite")

    assert plan[0].name == "Install desktop dependencies"
    assert stability.env == {
        "DATASCOPE_STRICT_STABILITY": "1",
        "DATASCOPE_STABILITY_LOOPS": "7",
        "DATASCOPE_HEALTH_DURATION_SECONDS": "11",
    }


def test_tauri_build_implies_runtime_build() -> None:
    plan = strict_acceptance.build_command_plan(
        profile="pr",
        python_exe=Path("/python"),
        install_desktop_deps=False,
        include_runtime_build=False,
        include_tauri_build=True,
        stability_loops=50,
        health_duration_seconds=1800,
    )

    names = [command.name for command in plan]

    assert names[-2:] == ["Build bundled Python runtime", "Build local Tauri installer"]


def test_tracked_artifact_check_rejects_generated_paths(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="apps/desktop/src-tauri/target/debug/app\n",
        )

    monkeypatch.setattr(strict_acceptance.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="Tracked generated/local artifacts"):
        strict_acceptance.check_tracked_artifacts(dry_run=False)


def test_parse_node_version_accepts_semver_prefix() -> None:
    assert strict_acceptance.parse_node_version("v20.19.5") == (20, 19, 5)
