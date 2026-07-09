from __future__ import annotations

import sys

import pytest

from datascope_core import rerun_cli
from datascope_core.rerun_cli import RerunCliError, clear_rerun_command_cache, rerun_command


@pytest.fixture(autouse=True)
def clear_rerun_cache() -> None:
    clear_rerun_command_cache()


def test_rerun_command_prefers_packaged_python(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATASCOPE_RERUN_BIN", raising=False)
    monkeypatch.setenv("DATASCOPE_RERUN_PYTHON", sys.executable)

    assert rerun_command() == [sys.executable, "-m", "rerun_cli"]


def test_rerun_command_reports_missing_packaged_python(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATASCOPE_RERUN_BIN", raising=False)
    monkeypatch.setenv("DATASCOPE_RERUN_PYTHON", "/missing/datascope/python")

    with pytest.raises(RerunCliError, match="does not exist") as exc_info:
        rerun_command()
    assert exc_info.value.code == "rerun_cli_missing"


def test_rerun_command_caches_packaged_python_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_python_has_rerun_cli(_: object) -> bool:
        nonlocal calls
        calls += 1
        return True

    monkeypatch.delenv("DATASCOPE_RERUN_BIN", raising=False)
    monkeypatch.setenv("DATASCOPE_RERUN_PYTHON", sys.executable)
    monkeypatch.setattr(rerun_cli, "_python_has_rerun_cli", fake_python_has_rerun_cli)

    assert rerun_command() == [sys.executable, "-m", "rerun_cli"]
    assert rerun_command() == [sys.executable, "-m", "rerun_cli"]
    assert calls == 1
