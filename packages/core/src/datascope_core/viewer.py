from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def open_recording(recording_path: str, blueprint_path: str | None = None) -> dict[str, str | int]:
    rerun = shutil.which("rerun")
    if rerun is None:
        raise RuntimeError(
            "Rerun CLI is not installed or not on PATH. Install it with `pip install rerun-sdk` "
            "inside the active environment, then retry."
        )

    args = [rerun, str(Path(recording_path))]
    if blueprint_path:
        args.append(str(Path(blueprint_path)))
    process = subprocess.Popen(args)
    return {"status": "started", "pid": process.pid}

