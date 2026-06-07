from __future__ import annotations

import importlib.util
import urllib.error
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[2] / "packaging/runtime/build_runtime.py"
SPEC = importlib.util.spec_from_file_location("build_runtime_network", MODULE_PATH)
assert SPEC and SPEC.loader
build_runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_runtime)


def test_retry_network_operation_retries_transient_errors() -> None:
    calls = 0
    delays: list[float] = []

    def operation() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise urllib.error.URLError("temporary DNS failure")
        return "ok"

    result = build_runtime.retry_network_operation(
        operation,
        description="test request",
        attempts=3,
        sleep=delays.append,
    )

    assert result == "ok"
    assert calls == 3
    assert delays == [1, 2]


def test_retry_network_operation_does_not_retry_not_found() -> None:
    calls = 0

    def operation() -> None:
        nonlocal calls
        calls += 1
        raise urllib.error.HTTPError("https://example.invalid", 404, "not found", {}, None)

    with pytest.raises(urllib.error.HTTPError):
        build_runtime.retry_network_operation(
            operation,
            description="test request",
            attempts=3,
            sleep=lambda _: None,
        )

    assert calls == 1


def test_release_workflow_pins_python_build_standalone() -> None:
    workflow = (MODULE_PATH.parents[2] / ".github/workflows/release.yml").read_text(
        encoding="utf-8"
    )

    assert 'DATASCOPE_PBS_RELEASE: "20260602"' in workflow
