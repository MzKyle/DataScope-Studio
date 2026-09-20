from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "packaging/release/check_version.py"
SPEC = importlib.util.spec_from_file_location("check_version", MODULE_PATH)
assert SPEC is not None
assert SPEC.loader is not None
check_version = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_version)


def test_repository_product_versions_match() -> None:
    versions = check_version.collect_versions(REPO_ROOT)
    expected = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()

    assert check_version.validate_versions(versions, f"v{expected}") == expected
    assert check_version.validate_public_release_docs(REPO_ROOT) == "0.3.1"


def test_version_validation_rejects_mismatch() -> None:
    with pytest.raises(RuntimeError, match="Version mismatch"):
        check_version.validate_versions({"VERSION": "0.3.0", "desktop": "1.0.0"})


def test_version_validation_rejects_wrong_tag() -> None:
    with pytest.raises(RuntimeError, match="does not match"):
        check_version.validate_versions({"VERSION": "0.3.0"}, "v0.2.0")


def test_public_release_docs_reject_stale_installer_names(tmp_path: Path) -> None:
    _make_release_doc_repo(tmp_path, stale=True)

    with pytest.raises(RuntimeError, match="unreleased installer artifacts"):
        check_version.validate_public_release_docs(
            tmp_path,
            metadata={"download_version": "0.3.1", "release_tag": "v0.3.1"},
        )


def test_public_release_docs_reject_tag_mismatch(tmp_path: Path) -> None:
    _make_release_doc_repo(tmp_path)

    with pytest.raises(RuntimeError, match="must match the release tag"):
        check_version.validate_public_release_docs(
            tmp_path,
            metadata={"download_version": "0.3.1", "release_tag": "v0.3.1"},
            tag="v0.4.0",
        )


def _make_release_doc_repo(root: Path, *, stale: bool = False) -> None:
    (root / "docs/guide").mkdir(parents=True)
    (root / "VERSION").write_text("0.4.0\n", encoding="utf-8")
    names = check_version.public_artifact_names("0.3.1")
    if stale:
        names = [*names, check_version.public_artifact_names("0.4.0")[0]]
    body = "v0.3.1\n" + "\n".join(names)
    for relative_path in check_version.PUBLIC_RELEASE_DOCS:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
