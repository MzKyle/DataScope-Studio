from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "packaging/dev/clean_local_artifacts.py"
SPEC = importlib.util.spec_from_file_location("clean_local_artifacts", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
clean_local_artifacts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(clean_local_artifacts)


def test_clean_local_artifacts_dry_run_does_not_delete(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    target = repo / "apps/desktop/src-tauri/target"
    runtime_dir = repo / "apps/desktop/src-tauri/resources/datascope-runtime/python"
    dist = repo / "apps/desktop/dist"

    planned = clean_local_artifacts.clean(repo_root=repo)

    assert target in planned
    assert runtime_dir in planned
    assert dist in planned
    assert target.exists()
    assert runtime_dir.exists()
    assert dist.exists()


def test_clean_local_artifacts_apply_only_deletes_allowed_paths(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    gitkeep = repo / "apps/desktop/src-tauri/resources/datascope-runtime/.gitkeep"

    deleted = clean_local_artifacts.clean(apply=True, repo_root=repo)

    assert deleted
    assert not (repo / "apps/desktop/src-tauri/target").exists()
    assert not (repo / "apps/desktop/dist").exists()
    assert not (repo / ".pytest_cache").exists()
    assert gitkeep.exists()
    assert not (repo / "apps/desktop/src-tauri/resources/datascope-runtime/python").exists()


def test_clean_local_artifacts_rejects_outside_and_protected_paths(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)

    with pytest.raises(ValueError, match="outside repository"):
        clean_local_artifacts._safe_path(repo, tmp_path / "outside")

    with pytest.raises(ValueError, match="protected path"):
        clean_local_artifacts._safe_path(repo, repo / ".venv")


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    runtime = repo / "apps/desktop/src-tauri/resources/datascope-runtime"
    (repo / "apps/desktop/src-tauri/target").mkdir(parents=True)
    (repo / "apps/desktop/dist").mkdir(parents=True)
    (repo / ".pytest_cache").mkdir(parents=True)
    (runtime / "python/bin").mkdir(parents=True)
    (runtime / ".gitkeep").write_text("", encoding="utf-8")
    (runtime / "python/bin/python").write_text("python", encoding="utf-8")
    return repo
