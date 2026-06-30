#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import re
import subprocess
from pathlib import Path

from datascope_core.models import JOB_STATUSES
from datascope_core.plugin_registry import validate_plugin
from datascope_core.template_registry import validate_template


REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_VERSION_PATH = REPO_ROOT / "packaging/release/check_version.py"
SPEC = importlib.util.spec_from_file_location("datascope_check_version", CHECK_VERSION_PATH)
assert SPEC is not None
assert SPEC.loader is not None
check_version = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_version)
QUALITY_PATTERN = re.compile(
    r"(^|/)\.history(/|$)|"
    r"(^|/)\.venv(/|$)|"
    r"(^|/)node_modules(/|$)|"
    r"(^|/)target(/|$)|"
    r"\.rrd$|\.rbl$|\.zip$|\.sqlite$|\.env$"
)


def run_sanity(repo_root: Path = REPO_ROOT, *, tag: str | None = None) -> None:
    check_version.validate_versions(check_version.collect_versions(repo_root), tag)
    _validate_examples(repo_root)
    _validate_job_status_docs(repo_root)
    _validate_repo_quality(repo_root)


def _validate_examples(repo_root: Path) -> None:
    plugin = validate_plugin(
        repo_root / "docs/examples/plugin.yaml",
        import_entrypoints=False,
    )
    if not plugin["valid"]:
        raise RuntimeError(f"Plugin example is invalid: {plugin['errors']}")
    template = validate_template(repo_root / "docs/examples/template.yaml")
    if not template["valid"]:
        raise RuntimeError(f"Template example is invalid: {template['errors']}")


def _validate_job_status_docs(repo_root: Path) -> None:
    text = (repo_root / "docs/architecture/state-model.md").read_text(encoding="utf-8")
    missing = sorted(status for status in JOB_STATUSES if status not in text)
    if missing:
        raise RuntimeError(f"Job status docs are missing: {', '.join(missing)}")


def _validate_repo_quality(repo_root: Path) -> None:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=True,
    )
    offenders = [line for line in result.stdout.splitlines() if QUALITY_PATTERN.search(line)]
    if offenders:
        rendered = "\n".join(offenders[:50])
        raise RuntimeError(f"Tracked generated/local artifacts found:\n{rendered}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run DataScope release sanity checks.")
    parser.add_argument("--tag", help="Optional release tag, for example v0.3.0")
    args = parser.parse_args()
    run_sanity(tag=args.tag)
    print("DataScope release sanity checks passed.")


if __name__ == "__main__":
    main()
