from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "packaging/release/prepare_artifacts.py"
SPEC = importlib.util.spec_from_file_location("prepare_artifacts", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
prepare_artifacts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare_artifacts)


def write_manifest(path: Path, machine: str) -> Path:
    path.write_text(json.dumps({"machine": machine}), encoding="utf-8")
    return path


def test_stage_linux_artifacts_uses_stable_names(tmp_path: Path) -> None:
    input_dir = tmp_path / "bundle"
    input_dir.mkdir()
    (input_dir / "datascope.deb").write_bytes(b"deb")
    (input_dir / "datascope.AppImage").write_bytes(b"appimage")
    manifest = write_manifest(tmp_path / "runtime-manifest.json", "x86_64")

    staged = prepare_artifacts.stage_artifacts(
        input_dir, tmp_path / "out", "linux", "x86_64", "0.3.0", manifest
    )

    assert [path.name for path in staged] == [
        "DataScope-Studio-v0.3.0-linux-amd64.deb",
        "DataScope-Studio-v0.3.0-linux-x86_64.AppImage",
    ]


def test_stage_rejects_duplicate_bundle_type(tmp_path: Path) -> None:
    input_dir = tmp_path / "bundle"
    input_dir.mkdir()
    (input_dir / "one.dmg").write_bytes(b"one")
    (input_dir / "two.dmg").write_bytes(b"two")
    manifest = write_manifest(tmp_path / "runtime-manifest.json", "arm64")

    with pytest.raises(RuntimeError, match="Expected one macOS disk image"):
        prepare_artifacts.stage_artifacts(
            input_dir, tmp_path / "out", "macos", "aarch64", "0.3.0", manifest
        )


def test_stage_rejects_mislabeled_architecture(tmp_path: Path) -> None:
    input_dir = tmp_path / "bundle"
    input_dir.mkdir()
    (input_dir / "app.dmg").write_bytes(b"dmg")
    manifest = write_manifest(tmp_path / "runtime-manifest.json", "x86_64")

    with pytest.raises(RuntimeError, match="does not match"):
        prepare_artifacts.stage_artifacts(
            input_dir, tmp_path / "out", "macos", "aarch64", "0.3.0", manifest
        )


def test_stage_windows_nsis_artifact_uses_stable_name(tmp_path: Path) -> None:
    input_dir = tmp_path / "bundle"
    input_dir.mkdir()
    (input_dir / "DataScope Studio_0.3.0_x64-setup.exe").write_bytes(b"exe")
    manifest = write_manifest(tmp_path / "runtime-manifest.json", "AMD64")

    staged = prepare_artifacts.stage_artifacts(
        input_dir, tmp_path / "out", "windows", "x86_64", "0.3.0", manifest
    )

    assert [path.name for path in staged] == [
        "DataScope-Studio-v0.3.0-windows-x86_64-setup.exe"
    ]


def test_write_checksums_requires_complete_release(tmp_path: Path) -> None:
    names = prepare_artifacts.public_artifact_names("0.3.0")
    for index, name in enumerate(names):
        (tmp_path / name).write_bytes(f"artifact-{index}".encode())

    checksum_path = prepare_artifacts.write_checksums(tmp_path, "0.3.0")
    contents = checksum_path.read_text(encoding="utf-8")

    assert len(contents.splitlines()) == 5
    assert all(name in contents for name in names)


def test_write_checksums_rejects_missing_artifact(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="missing="):
        prepare_artifacts.write_checksums(tmp_path, "0.3.0")
