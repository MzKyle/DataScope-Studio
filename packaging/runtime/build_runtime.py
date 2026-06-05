#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import venv
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "apps/desktop/src-tauri/resources/datascope-runtime"
PBS_API = "https://api.github.com/repos/astral-sh/python-build-standalone/releases"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the bundled DataScope runtime.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--python-version", default="3.10")
    parser.add_argument("--release", default=os.environ.get("DATASCOPE_PBS_RELEASE", "latest"))
    parser.add_argument("--use-current-python", action="store_true")
    parser.add_argument("--wheelhouse", type=Path)
    parser.add_argument("--index-url", default=os.environ.get("PIP_INDEX_URL"))
    args = parser.parse_args()

    output = args.output.resolve()
    prepare_output(output)

    if args.use_current_python:
        create_development_venv(output / "python")
        python = python_executable(output)
        runtime_kind = "development-venv"
        source_asset = None
    else:
        source_asset = install_standalone_python(output, args.python_version, args.release)
        python = python_executable(output)
        runtime_kind = "python-build-standalone"

    install_runtime_packages(
        python,
        wheelhouse=args.wheelhouse,
        index_url=args.index_url,
    )
    prune_runtime(output)
    manifest = build_manifest(
        python,
        output=output,
        runtime_kind=runtime_kind,
        source_asset=source_asset,
    )
    (output / "runtime-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "THIRD_PARTY_NOTICES.md").write_text(build_notices(python), encoding="utf-8")
    print(f"DataScope runtime built at {output}")
    print(f"Python: {python}")
    print(f"Rerun SDK: {manifest.get('rerun_version', 'unknown')}")


def prepare_output(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for child in output.iterdir():
        if child.name == ".gitkeep":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def create_development_venv(path: Path) -> None:
    print("Building a development runtime from the current Python interpreter.")
    print("Use the default mode for distributable installers with standalone CPython.")
    builder = venv.EnvBuilder(with_pip=True, symlinks=False, clear=True)
    builder.create(path)


def install_standalone_python(output: Path, python_version: str, release: str) -> str:
    asset = select_python_asset(python_version, release)
    with tempfile.TemporaryDirectory(prefix="datascope-python-") as temp_name:
        temp_dir = Path(temp_name)
        archive = temp_dir / asset["name"]
        print(f"Downloading {asset['name']}")
        download(asset["browser_download_url"], archive)
        extract_tarball(archive, temp_dir / "extract")
        extracted_python = find_extracted_python(temp_dir / "extract")
        shutil.copytree(extracted_python, output / "python")
    return asset["name"]


def select_python_asset(python_version: str, release: str) -> dict[str, str]:
    release_url = f"{PBS_API}/{release}" if release == "latest" else f"{PBS_API}/tags/{release}"
    request = urllib.request.Request(
        release_url,
        headers={
            "Accept": "application/vnd.github+json",
            **({"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"} if os.environ.get("GITHUB_TOKEN") else {}),
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))

    target = target_triple()
    assets = payload.get("assets", [])
    matches: list[dict[str, str]] = []
    for asset in assets:
        name = asset.get("name", "")
        if not name.startswith(f"cpython-{python_version}"):
            continue
        if target not in name:
            continue
        if "install_only" not in name or not name.endswith(".tar.gz"):
            continue
        if "debug" in name or "freethreaded" in name:
            continue
        matches.append(asset)

    if not matches:
        raise RuntimeError(
            f"No python-build-standalone asset found for Python {python_version} and target {target}. "
            "Set DATASCOPE_PBS_RELEASE to a release that provides the required artifact, or use "
            "--use-current-python for a development-only runtime."
        )

    matches.sort(key=lambda asset: ("install_only_stripped" not in asset["name"], asset["name"]))
    return matches[0]


def target_triple() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        arch = "x86_64"
    elif machine in {"arm64", "aarch64"}:
        arch = "aarch64"
    else:
        raise RuntimeError(f"Unsupported CPU architecture for packaged runtime: {machine}")

    if system == "linux":
        return f"{arch}-unknown-linux-gnu"
    if system == "darwin":
        return f"{arch}-apple-darwin"
    if system == "windows":
        return f"{arch}-pc-windows-msvc"
    raise RuntimeError(f"Unsupported operating system for packaged runtime: {system}")


def download(url: str, path: Path) -> None:
    with urllib.request.urlopen(url, timeout=300) as response, path.open("wb") as file:
        shutil.copyfileobj(response, file)


def extract_tarball(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        destination_root = destination.resolve()
        for member in members:
            target = (destination / member.name).resolve()
            if not str(target).startswith(str(destination_root)):
                raise RuntimeError(f"Unsafe archive path: {member.name}")
        tar.extractall(destination)


def find_extracted_python(root: Path) -> Path:
    direct = root / "python"
    if direct.is_dir():
        return direct
    matches = [path for path in root.rglob("python") if path.is_dir()]
    if not matches:
        raise RuntimeError("The Python archive did not contain a python/ directory.")
    return matches[0]


def python_executable(runtime_dir: Path) -> Path:
    candidates = [
        runtime_dir / "python/python.exe",
        runtime_dir / "python/Scripts/python.exe",
        runtime_dir / "python/bin/python3",
        runtime_dir / "python/bin/python",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError(f"No Python executable found in {runtime_dir / 'python'}")


def install_runtime_packages(python: Path, wheelhouse: Path | None, index_url: str | None) -> None:
    run([python, "-m", "ensurepip", "--upgrade"])
    run([python, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])

    pip_install = [python, "-m", "pip", "install", "--no-cache-dir", "--ignore-installed"]
    if index_url:
        pip_install.extend(["--index-url", index_url])
    if wheelhouse:
        pip_install.extend(["--find-links", str(wheelhouse), "--prefer-binary"])
    pip_install.extend(
        [
            str(REPO_ROOT / "packages/core"),
            str(REPO_ROOT / "services/api"),
            str(REPO_ROOT / "packages/cli"),
        ]
    )
    run(pip_install)


def prune_runtime(output: Path) -> None:
    python_root = output / "python"
    removable_paths = [
        python_root / "include",
        python_root / "share",
        python_root / "lib/pkgconfig",
        python_root / "lib/tcl9",
        python_root / "lib/tcl9.0",
        python_root / "lib/tk9.0",
        python_root / "lib/itcl4.3.5",
        python_root / "lib/thread3.0.4",
        python_root / "lib/python3.10/idlelib",
        python_root / "lib/python3.10/tkinter",
        python_root / "lib/python3.10/turtledemo",
        python_root / "lib/python3.10/test",
    ]
    for path in removable_paths:
        remove_path(path)

    for pattern in [
        "**/__pycache__",
        "**/_tkinter*.so",
        "**/_tkinter_finder.py",
        "**/_imagingtk*.so",
        "**/_imagingtk.pyi",
        "**/_test*.so",
        "**/libtcl*.so",
        "**/libtcl*.so.*",
        "**/libtk*.so",
        "**/libtk*.so.*",
    ]:
        for path in list(python_root.glob(pattern)):
            remove_path(path)


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def build_manifest(
    python: Path,
    output: Path,
    runtime_kind: str,
    source_asset: str | None,
) -> dict[str, Any]:
    packages = json.loads(
        run_capture(
            [
                python,
                "-c",
                "import importlib.metadata as m, json; "
                "rows=[{'name': d.metadata.get('Name'), 'version': d.version} for d in m.distributions()]; "
                "print(json.dumps(sorted(rows, key=lambda row: (row.get('name') or '').lower()), sort_keys=True))",
            ]
        )
    )
    rerun_version = run_capture(
        [python, "-c", "import rerun as rr; print(getattr(rr, '__version__', 'unknown'))"]
    ).strip()
    api_importable = run(
        [
            python,
            "-c",
            "import datascope_api.launcher, datascope_core, datascope_cli, rerun_cli",
        ],
        check=False,
    ).returncode == 0
    if not api_importable:
        raise RuntimeError("Runtime validation failed: DataScope API/core/CLI or rerun_cli is not importable.")

    return {
        "name": "datascope-runtime",
        "datascope_version": "1.0.0",
        "runtime_kind": runtime_kind,
        "source_asset": source_asset,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": str(python.relative_to(output)),
        "python_version": run_capture([python, "-c", "import sys; print(sys.version)"]).strip(),
        "rerun_version": rerun_version,
        "packages": packages,
    }


def build_notices(python: Path) -> str:
    payload = run_capture(
        [
            python,
            "-c",
            "import importlib.metadata as m, json; "
            "rows=[]\n"
            "for d in m.distributions():\n"
            "    meta=d.metadata\n"
            "    rows.append({'name': meta.get('Name'), 'version': d.version, "
            "'license': meta.get('License') or meta.get('Classifier', ''), "
            "'summary': meta.get('Summary', '')})\n"
            "print(json.dumps(sorted(rows, key=lambda r: (r.get('name') or '').lower())))",
        ]
    )
    rows = json.loads(payload)
    lines = [
        "# Third Party Notices",
        "",
        "This file is generated by `packaging/runtime/build_runtime.py` for the bundled runtime.",
        "",
        "| Package | Version | License | Summary |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {escape(row.get('name'))} | {escape(row.get('version'))} | "
            f"{escape(row.get('license'))} | {escape(row.get('summary'))} |"
        )
    lines.append("")
    return "\n".join(lines)


def escape(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def run(command: list[Any], check: bool = True) -> subprocess.CompletedProcess[str]:
    printable = " ".join(str(part) for part in command)
    print(f"+ {printable}")
    return subprocess.run([str(part) for part in command], text=True, check=check, env=runtime_env())


def run_capture(command: list[Any]) -> str:
    return subprocess.check_output([str(part) for part in command], text=True, env=runtime_env())


def runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONUSERBASE", None)
    env.pop("PIP_USER", None)
    return env


if __name__ == "__main__":
    main()
