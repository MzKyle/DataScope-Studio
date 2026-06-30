from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


class RerunCliError(RuntimeError):
    code = "rerun_cli_missing"


def rerun_command() -> list[str]:
    explicit_bin = os.environ.get("DATASCOPE_RERUN_BIN")
    if explicit_bin:
        path = Path(explicit_bin)
        if not path.exists():
            raise RerunCliError(f"Configured Rerun binary does not exist: {path}")
        return [str(path)]

    runtime_python = os.environ.get("DATASCOPE_RERUN_PYTHON")
    if runtime_python:
        python = Path(runtime_python)
        if not python.exists():
            raise RerunCliError(f"Configured Rerun Python runtime does not exist: {python}")
        if not _python_has_rerun_cli(python):
            raise RerunCliError(
                "The bundled Python runtime is present, but rerun_cli is not importable. "
                "Rebuild the DataScope runtime package."
            )
        return [str(python), "-m", "rerun_cli"]

    rerun = shutil.which("rerun")
    if rerun is None:
        raise RerunCliError(
            "Rerun CLI is not installed or not on PATH. Install rerun-sdk in the active "
            "environment, or launch DataScope Studio from an installer with the bundled runtime."
        )
    return [rerun]


def rerun_subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    runtime_dir = env.get("DATASCOPE_RUNTIME_DIR")
    runtime_python = env.get("DATASCOPE_RERUN_PYTHON")
    if runtime_dir:
        env["DATASCOPE_RUNTIME_DIR"] = runtime_dir
    if runtime_python:
        env["DATASCOPE_RERUN_PYTHON"] = runtime_python
        env["PYTHONNOUSERSITE"] = "1"
        python_bin = str(Path(runtime_python).resolve().parent)
        env["PATH"] = python_bin + os.pathsep + env.get("PATH", "")
    return env


def _python_has_rerun_cli(python: Path) -> bool:
    result = subprocess.run(
        [
            str(python),
            "-c",
            "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('rerun_cli') else 1)",
        ],
        env={**os.environ, "PYTHONNOUSERSITE": "1"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0
