from pathlib import Path

import pytest

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
