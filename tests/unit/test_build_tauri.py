from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[2] / "packaging/runtime/build_tauri.py"
SPEC = importlib.util.spec_from_file_location("build_tauri", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
build_tauri = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_tauri)


def test_resolve_npx_prefers_cmd_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    requested: list[str] = []

    def fake_which(name: str) -> str | None:
        requested.append(name)
        if name == "npx.cmd":
            return r"C:\hostedtoolcache\node\npx.cmd"
        return None

    monkeypatch.setattr(build_tauri.platform, "system", lambda: "Windows")
    monkeypatch.setattr(build_tauri.shutil, "which", fake_which)

    assert build_tauri.resolve_npx() == r"C:\hostedtoolcache\node\npx.cmd"
    assert requested == ["npx.cmd"]


def test_resolve_npx_uses_plain_binary_on_unix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_tauri.platform, "system", lambda: "Linux")
    monkeypatch.setattr(build_tauri.shutil, "which", lambda name: f"/usr/bin/{name}")

    assert build_tauri.resolve_npx() == "/usr/bin/npx"


def test_resolve_npx_reports_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_tauri.platform, "system", lambda: "Linux")
    monkeypatch.setattr(build_tauri.shutil, "which", lambda name: None)

    with pytest.raises(RuntimeError, match="Unable to find npx"):
        build_tauri.resolve_npx()


def test_default_bundles_uses_nsis_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_tauri.platform, "system", lambda: "Windows")

    assert build_tauri.default_bundles() == "nsis"
