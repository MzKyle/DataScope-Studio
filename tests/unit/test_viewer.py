from pathlib import Path
from types import SimpleNamespace

import pytest

import datascope_core.viewer as viewer_module
from datascope_core.viewer import ViewerOpenError, open_recording


def test_open_recording_rejects_missing_recording(tmp_path: Path) -> None:
    with pytest.raises(ViewerOpenError) as exc_info:
        open_recording(str(tmp_path / "missing.rrd"))

    assert exc_info.value.code == "viewer_recording_missing"


def test_open_recording_rejects_missing_blueprint(tmp_path: Path) -> None:
    recording = tmp_path / "run.rrd"
    recording.write_bytes(b"rrd")

    with pytest.raises(ViewerOpenError) as exc_info:
        open_recording(str(recording), str(tmp_path / "missing.rbl"))

    assert exc_info.value.code == "viewer_blueprint_missing"


def test_open_recording_starts_viewer_detached_from_api_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recording = tmp_path / "run.rrd"
    blueprint = tmp_path / "run.rbl"
    recording.write_bytes(b"rrd")
    blueprint.write_bytes(b"rbl")
    popen_calls: list[dict] = []

    def fake_popen(args, **kwargs):
        popen_calls.append({"args": args, **kwargs})
        return SimpleNamespace(pid=1234)

    monkeypatch.setattr(viewer_module, "rerun_command", lambda: ["/usr/bin/rerun"])
    monkeypatch.setattr(viewer_module, "rerun_subprocess_env", lambda: {"RERUN": "1"})
    monkeypatch.setattr(viewer_module.subprocess, "Popen", fake_popen)

    assert open_recording(str(recording), str(blueprint)) == {"status": "started", "pid": 1234}
    assert popen_calls[0]["args"] == ["/usr/bin/rerun", str(recording), str(blueprint)]
    assert popen_calls[0]["env"] == {"RERUN": "1"}
    assert popen_calls[0]["stdout"] is viewer_module.subprocess.DEVNULL
    assert popen_calls[0]["stderr"] is viewer_module.subprocess.DEVNULL
