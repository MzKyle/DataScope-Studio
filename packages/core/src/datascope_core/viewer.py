from __future__ import annotations

import subprocess
from pathlib import Path

from datascope_core.rerun_cli import rerun_command, rerun_subprocess_env


class ViewerOpenError(RuntimeError):
    def __init__(self, code: str, message: str, path: Path) -> None:
        self.code = code
        self.paths = [str(path)]
        super().__init__(message)


def open_recording(recording_path: str, blueprint_path: str | None = None) -> dict[str, str | int]:
    recording = Path(recording_path)
    if not recording.is_file():
        raise ViewerOpenError(
            "viewer_recording_missing",
            f"Recording file does not exist: {recording}",
            recording,
        )
    args = [str(recording)]
    if blueprint_path:
        blueprint = Path(blueprint_path)
        if not blueprint.is_file():
            raise ViewerOpenError(
                "viewer_blueprint_missing",
                f"Blueprint file does not exist: {blueprint}",
                blueprint,
            )
        args.append(str(blueprint))
    args = [*rerun_command(), *args]
    process = subprocess.Popen(args, env=rerun_subprocess_env())
    return {"status": "started", "pid": process.pid}
