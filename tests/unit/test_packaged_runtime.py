from __future__ import annotations

import sys

import pytest

from datascope_core.rerun_cli import rerun_command


def test_rerun_command_prefers_packaged_python(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATASCOPE_RERUN_BIN", raising=False)
    monkeypatch.setenv("DATASCOPE_RERUN_PYTHON", sys.executable)

    assert rerun_command() == [sys.executable, "-m", "rerun_cli"]


def test_rerun_command_reports_missing_packaged_python(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATASCOPE_RERUN_BIN", raising=False)
    monkeypatch.setenv("DATASCOPE_RERUN_PYTHON", "/missing/datascope/python")

    with pytest.raises(RuntimeError, match="does not exist"):
        rerun_command()
