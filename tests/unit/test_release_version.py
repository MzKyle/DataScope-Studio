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

    assert check_version.validate_versions(versions, "v0.3.1") == "0.3.1"


def test_version_validation_rejects_mismatch() -> None:
    with pytest.raises(RuntimeError, match="Version mismatch"):
        check_version.validate_versions({"VERSION": "0.3.0", "desktop": "1.0.0"})


def test_version_validation_rejects_wrong_tag() -> None:
    with pytest.raises(RuntimeError, match="does not match"):
        check_version.validate_versions({"VERSION": "0.3.0"}, "v0.2.0")
