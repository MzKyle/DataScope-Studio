from __future__ import annotations

import platform
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Callable

from datascope_core.models import (
    ARTIFACT_VALIDATION_MODES,
    MCAP_DECODERS,
    RRD_OPTIMIZE_PROFILES,
)
from datascope_core.rerun_cli import rerun_command, rerun_subprocess_env


LOCAL_CATALOG_URL = "rerun+http://127.0.0.1:51234"


def normalize_mcap_decoders(decoders: list[str] | None) -> list[str] | None:
    if decoders is None:
        return None
    normalized = [str(decoder).strip() for decoder in decoders if str(decoder).strip()]
    if not normalized:
        return None
    invalid = [decoder for decoder in normalized if decoder not in MCAP_DECODERS]
    if invalid:
        allowed = ", ".join(sorted(MCAP_DECODERS))
        raise ValueError(f"Unsupported MCAP decoder(s): {', '.join(invalid)}. Allowed: {allowed}")
    return normalized


def normalize_rrd_optimize_profile(profile: str | None) -> str:
    normalized = str(profile or "none").strip() or "none"
    if normalized not in RRD_OPTIMIZE_PROFILES:
        allowed = ", ".join(sorted(RRD_OPTIMIZE_PROFILES))
        raise ValueError(f"Unsupported RRD optimize profile: {normalized}. Allowed: {allowed}")
    return normalized


def normalize_artifact_validation(mode: str | None) -> str:
    normalized = str(mode or "basic").strip() or "basic"
    if normalized not in ARTIFACT_VALIDATION_MODES:
        allowed = ", ".join(sorted(ARTIFACT_VALIDATION_MODES))
        raise ValueError(f"Unsupported artifact validation mode: {normalized}. Allowed: {allowed}")
    return normalized


def normalize_catalog_registration(config: dict[str, Any] | None) -> dict[str, Any]:
    if not config or not bool(config.get("enabled")):
        return {
            "enabled": False,
            "dataset_name": "",
            "server_url": None,
            "managed_local": False,
            "status": "disabled",
        }
    dataset_name = str(config.get("dataset_name") or "datascope").strip()
    if not dataset_name:
        raise ValueError("Catalog dataset_name must not be empty when catalog registration is enabled.")
    managed_local = bool(config.get("managed_local"))
    server_url = config.get("server_url")
    server_url = str(server_url).strip() if server_url else None
    if managed_local and not server_url:
        server_url = LOCAL_CATALOG_URL
    if not managed_local and not server_url:
        raise ValueError("Catalog server_url is required when managed_local is false.")
    return {
        "enabled": True,
        "dataset_name": dataset_name,
        "server_url": server_url,
        "managed_local": managed_local,
        "status": "pending",
    }


def require_supported_artifact_options(
    *,
    mcap_decoders: list[str] | None,
    rrd_optimize_profile: str,
    artifact_validation: str,
    catalog_registration: dict[str, Any],
) -> None:
    if mcap_decoders:
        require_rerun_033_feature("mcap_decoders")
    if rrd_optimize_profile != "none":
        require_rerun_033_feature("rrd_optimize")
    if artifact_validation in {"verify", "strict"}:
        require_rerun_033_feature("artifact_verify")
    if artifact_validation == "strict":
        require_rerun_033_feature("headless_screenshot")
    if catalog_registration.get("enabled"):
        require_rerun_033_feature("catalog")


def rerun_version() -> str:
    try:
        return version("rerun-sdk")
    except PackageNotFoundError:
        pass
    try:
        import rerun as rr
    except Exception:
        return "unknown"
    return str(getattr(rr, "__version__", "unknown") or "unknown")


def rerun_features() -> dict[str, bool]:
    version_text = rerun_version()
    supports_033 = _version_at_least(version_text, (0, 33, 0))
    legacy_intel_mac = platform.system() == "Darwin" and platform.machine() == "x86_64"
    return {
        "rerun_033": supports_033 and not legacy_intel_mac,
        "mcap_decoders": supports_033 and not legacy_intel_mac,
        "rrd_optimize": supports_033 and not legacy_intel_mac,
        "artifact_verify": supports_033 and not legacy_intel_mac,
        "headless_screenshot": supports_033 and not legacy_intel_mac,
        "catalog": supports_033 and not legacy_intel_mac,
        "legacy_intel_mac": legacy_intel_mac,
    }


def require_rerun_033_feature(feature: str) -> None:
    features = rerun_features()
    if features.get(feature):
        return
    version_text = rerun_version()
    raise RuntimeError(
        f"Rerun feature '{feature}' requires rerun-sdk 0.33+ on a supported platform; "
        f"detected {version_text}."
    )


def optimize_rrd(
    path: Path,
    profile: str,
    *,
    cancel_check: Callable[[], None] | None = None,
) -> dict[str, Any]:
    if profile == "none":
        return {"status": "skipped", "profile": "none"}
    require_rerun_033_feature("rrd_optimize")
    output = path.with_name(f"{path.stem}.optimized.tmp{path.suffix}")
    output.unlink(missing_ok=True)
    try:
        _run_rerun(
            [
                "rrd",
                "optimize",
                str(path),
                "--profile",
                profile,
                "-o",
                str(output),
            ],
            cancel_check=cancel_check,
        )
        if not output.is_file() or output.stat().st_size <= 0:
            raise RuntimeError(f"Rerun optimize did not create a valid output file: {output}")
        output.replace(path)
    finally:
        output.unlink(missing_ok=True)
    return {"status": "optimized", "profile": profile}


def validate_artifacts(
    recording_path: Path,
    blueprint_path: Path,
    mode: str,
    *,
    output_dir: Path,
    cancel_check: Callable[[], None] | None = None,
) -> dict[str, Any]:
    checks: dict[str, Any] = {
        "mode": mode,
        "recording_exists": recording_path.is_file(),
        "blueprint_exists": blueprint_path.is_file(),
        "recording_non_empty": recording_path.is_file() and recording_path.stat().st_size > 0,
        "blueprint_non_empty": blueprint_path.is_file() and blueprint_path.stat().st_size > 0,
    }
    if mode in {"verify", "strict"}:
        require_rerun_033_feature("artifact_verify")
        verify = _run_rerun(["rrd", "verify", str(recording_path)], cancel_check=cancel_check)
        stats = _run_rerun(
            ["rrd", "stats", "--no-decode", str(recording_path)],
            cancel_check=cancel_check,
        )
        checks["verify"] = _completed_check(verify)
        checks["stats"] = _completed_check(stats)
    if mode == "strict":
        require_rerun_033_feature("headless_screenshot")
        screenshot_path = output_dir / f"{recording_path.stem}.headless.png"
        screenshot_path.unlink(missing_ok=True)
        _run_rerun(
            [
                "--headless",
                "--window-size",
                "1280x720",
                "--screenshot-to",
                str(screenshot_path),
                str(recording_path),
                str(blueprint_path),
            ],
            cancel_check=cancel_check,
        )
        if not screenshot_path.is_file() or screenshot_path.stat().st_size <= 0:
            raise RuntimeError("Rerun headless screenshot did not produce a non-empty PNG.")
        checks["headless_screenshot"] = {
            "status": "passed",
            "path": str(screenshot_path),
            "size_bytes": screenshot_path.stat().st_size,
        }
    return checks


def register_recording_with_catalog(
    recording_path: Path,
    registration: dict[str, Any],
) -> dict[str, Any]:
    normalized = normalize_catalog_registration(registration)
    if not normalized["enabled"]:
        return normalized
    require_rerun_033_feature("catalog")
    try:
        import rerun as rr
    except Exception as exc:
        raise RuntimeError("rerun-sdk[catalog] is required for catalog registration.") from exc
    catalog = getattr(rr, "catalog", None)
    if catalog is None or not hasattr(catalog, "CatalogClient"):
        raise RuntimeError("rerun.catalog.CatalogClient is not available.")
    client = catalog.CatalogClient(normalized["server_url"])
    dataset = client.create_dataset(normalized["dataset_name"], exist_ok=True)
    registration_job = dataset.register([recording_path.absolute().as_uri()])
    if hasattr(registration_job, "wait"):
        registration_job.wait()
    normalized["status"] = "registered"
    normalized["recording_uri"] = recording_path.absolute().as_uri()
    return normalized


def _run_rerun(
    args: list[str],
    *,
    cancel_check: Callable[[], None] | None = None,
) -> subprocess.CompletedProcess[str]:
    if cancel_check is not None:
        cancel_check()
    result = subprocess.run(
        [*rerun_command(), *args],
        capture_output=True,
        text=True,
        check=False,
        env=rerun_subprocess_env(),
    )
    if cancel_check is not None:
        cancel_check()
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "Rerun command failed").strip()
        raise RuntimeError(message)
    return result


def _completed_check(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return {
        "status": "passed",
        "stdout": _short_text(result.stdout),
        "stderr": _short_text(result.stderr),
    }


def _short_text(value: str) -> str:
    text = (value or "").strip()
    if len(text) > 2000:
        return text[:2000] + "\n..."
    return text


def _version_at_least(version_text: str, minimum: tuple[int, int, int]) -> bool:
    parts = []
    for piece in version_text.split(".")[:3]:
        number = ""
        for char in piece:
            if char.isdigit():
                number += char
            else:
                break
        if not number:
            break
        parts.append(int(number))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3]) >= minimum
