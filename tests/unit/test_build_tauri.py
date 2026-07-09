from __future__ import annotations

import importlib.util
import json
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


def test_macos_dmg_builds_app_before_native_packaging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_tauri.platform, "system", lambda: "Darwin")

    assert build_tauri.build_bundles("dmg") == "app"
    assert build_tauri.use_native_macos_dmg("dmg") is True


def test_appimage_build_cleans_stale_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_root = tmp_path / "bundle"
    appdir = bundle_root / "appimage/DataScope Studio.AppDir"
    staging = bundle_root / "appimage_deb"
    appdir.mkdir(parents=True)
    staging.mkdir()
    (appdir / "stale").write_text("stale", encoding="utf-8")
    (staging / "stale").write_text("stale", encoding="utf-8")

    monkeypatch.setattr(build_tauri.platform, "system", lambda: "Linux")
    monkeypatch.setattr(build_tauri, "cargo_bundle_root", lambda env: bundle_root)

    build_tauri.clean_stale_appimage_staging("appimage", {})

    assert not appdir.exists()
    assert not staging.exists()


def test_create_macos_dmg_uses_hdiutil_without_mounting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_root = tmp_path / "bundle"
    app = bundle_root / "macos/DataScope Studio.app"
    app.mkdir(parents=True)
    (app / "Contents").mkdir()
    commands: list[list[str]] = []

    def fake_run(command, check):
        commands.append(command)
        Path(command[-1]).write_bytes(b"dmg")

    monkeypatch.setattr(build_tauri.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(build_tauri.subprocess, "run", fake_run)

    output = build_tauri.create_macos_dmg(bundle_root)

    assert output.name == f"DataScope Studio_{build_tauri.VERSION}_x64.dmg"
    assert app.is_dir()
    assert len(commands) == 1
    command = commands[0]
    assert command[:5] == [
        "hdiutil",
        "create",
        "-volname",
        "DataScope Studio",
        "-srcfolder",
    ]
    assert Path(command[5]).parent == bundle_root / "macos"
    assert Path(command[5]).name.startswith(".datascope-dmg-")
    assert command[6:] == ["-ov", "-format", "UDZO", str(output)]


def test_windows_nsis_bundle_has_required_icon() -> None:
    repo_root = MODULE_PATH.parents[2]
    config = json.loads(
        (repo_root / "apps/desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8")
    )

    assert config["bundle"]["windows"]["nsis"]["installMode"] == "currentUser"
    assert config["bundle"]["windows"]["webviewInstallMode"]["type"] == "embedBootstrapper"
    assert "icons/icon.ico" in config["bundle"]["icon"]
    assert (repo_root / "apps/desktop/src-tauri/icons/icon.ico").is_file()
