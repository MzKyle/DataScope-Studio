from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "packaging/release/sanity_check.py"
SPEC = importlib.util.spec_from_file_location("sanity_check", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
sanity_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sanity_check)


def test_release_sanity_rejects_version_mismatch(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sanity_check, "_validate_examples", lambda repo_root: None)
    monkeypatch.setattr(sanity_check, "_validate_job_status_docs", lambda repo_root: None)
    monkeypatch.setattr(sanity_check, "_validate_repo_quality", lambda repo_root: None)
    monkeypatch.setattr(
        sanity_check.check_version,
        "collect_versions",
        lambda repo_root: {"VERSION": "0.3.0", "desktop": "0.4.0"},
    )

    with pytest.raises(RuntimeError, match="Version mismatch"):
        sanity_check.run_sanity(tmp_path)


def test_release_sanity_rejects_bad_plugin_example(monkeypatch, tmp_path: Path) -> None:
    _make_example_repo(tmp_path)
    monkeypatch.setattr(
        sanity_check,
        "validate_plugin",
        lambda path, import_entrypoints=False: {"valid": False, "errors": ["bad plugin"]},
    )
    monkeypatch.setattr(
        sanity_check,
        "validate_template",
        lambda path: {"valid": True, "errors": []},
    )

    with pytest.raises(RuntimeError, match="Plugin example is invalid"):
        sanity_check._validate_examples(tmp_path)


def test_release_sanity_rejects_bad_template_example(monkeypatch, tmp_path: Path) -> None:
    _make_example_repo(tmp_path)
    monkeypatch.setattr(
        sanity_check,
        "validate_plugin",
        lambda path, import_entrypoints=False: {"valid": True, "errors": []},
    )
    monkeypatch.setattr(
        sanity_check,
        "validate_template",
        lambda path: {"valid": False, "errors": ["bad template"]},
    )

    with pytest.raises(RuntimeError, match="Template example is invalid"):
        sanity_check._validate_examples(tmp_path)


def test_release_sanity_rejects_job_status_doc_drift(tmp_path: Path) -> None:
    docs = tmp_path / "docs/architecture"
    docs.mkdir(parents=True)
    (docs / "state-model.md").write_text("pending running succeeded", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Job status docs are missing"):
        sanity_check._validate_job_status_docs(tmp_path)


def test_release_sanity_rejects_tracked_generated_files(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        sanity_check.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="apps/desktop/src-tauri/target/app\n"),
    )

    with pytest.raises(RuntimeError, match="Tracked generated/local artifacts"):
        sanity_check._validate_repo_quality(tmp_path)


def _make_example_repo(root: Path) -> None:
    (root / "docs/examples").mkdir(parents=True)
    (root / "docs/examples/plugin.yaml").write_text("id: bad\n", encoding="utf-8")
    (root / "docs/examples/template.yaml").write_text("template:\n", encoding="utf-8")
