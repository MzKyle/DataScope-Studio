#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PROTECTED_NAMES = {".git", ".venv", "venv", "node_modules", "tests", "packages", "services", "docs"}


def planned_paths(repo_root: Path = REPO_ROOT) -> list[Path]:
    runtime_dir = repo_root / "apps/desktop/src-tauri/resources/datascope-runtime"
    paths = [
        repo_root / "apps/desktop/src-tauri/target",
        repo_root / "apps/desktop/dist",
        repo_root / ".pytest_cache",
        repo_root / ".ruff_cache",
        repo_root / ".mypy_cache",
        repo_root / "htmlcov",
        repo_root / "apps/desktop/coverage",
    ]
    if runtime_dir.exists():
        paths.extend(child for child in runtime_dir.iterdir() if child.name != ".gitkeep")
    return [_safe_path(repo_root, path) for path in paths if path.exists()]


def clean(*, apply: bool = False, repo_root: Path = REPO_ROOT) -> list[Path]:
    targets = planned_paths(repo_root)
    if not apply:
        return targets
    for path in targets:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    return targets


def _safe_path(repo_root: Path, path: Path) -> Path:
    root = repo_root.resolve()
    resolved = path.resolve()
    if root not in [resolved, *resolved.parents]:
        raise ValueError(f"Refusing to clean path outside repository: {path}")
    if resolved == root or any(part in PROTECTED_NAMES for part in resolved.relative_to(root).parts):
        if resolved.name not in {"target", "dist", "coverage", ".pytest_cache", ".ruff_cache", ".mypy_cache", "htmlcov"}:
            raise ValueError(f"Refusing to clean protected path: {path}")
    return resolved


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean local generated DataScope artifacts.")
    parser.add_argument("--apply", action="store_true", help="Delete files. Default is dry-run.")
    args = parser.parse_args()
    targets = clean(apply=args.apply)
    action = "deleted" if args.apply else "would delete"
    if not targets:
        print("No local generated artifacts found.")
        return
    for path in targets:
        print(f"{action}: {path}")


if __name__ == "__main__":
    main()
