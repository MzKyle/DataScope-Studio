from __future__ import annotations

import subprocess
from pathlib import Path

from datascope_core.rerun_cli import rerun_command, rerun_subprocess_env


def open_recording(recording_path: str, blueprint_path: str | None = None) -> dict[str, str | int]:
    args = [*rerun_command(), str(Path(recording_path))]
    if blueprint_path:
        args.append(str(Path(blueprint_path)))
    process = subprocess.Popen(args, env=rerun_subprocess_env())
    return {"status": "started", "pid": process.pid}
