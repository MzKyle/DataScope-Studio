from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

import datascope_core.rerun_artifacts as artifact_module
import datascope_core.workspace as workspace_module
from datascope_core.models import ConvertRequest
from datascope_core.workspace import RerunArtifactError, Workspace, _converter_id


def test_build_recording_persists_artifact_info(tmp_path: Path, monkeypatch) -> None:
    workspace, project, source, mapping = _mapped_csv_workspace(tmp_path)
    _install_fake_artifact_writers(monkeypatch, recording_payload=b"rrd", blueprint_payload=b"rbl")

    result = workspace.build_recording(
        project["id"],
        source["id"],
        mapping_id=mapping["id"],
        output_name="artifact_run",
    )
    recording = workspace.get_recording(result["recording_id"])

    assert result["artifact_info"] == {
        "recording_size_bytes": 3,
        "blueprint_size_bytes": 3,
        "app_id": "datascope.sensor_monitor.v1",
        "template_id": "sensor_monitor",
        "rerun_recording_id": result["artifact_info"]["rerun_recording_id"],
        "source_type": "csv",
        "converter": "rerun_python_sdk",
        "rerun_version": result["artifact_info"]["rerun_version"],
        "mcap_decoders": None,
        "rrd_optimize_profile": "none",
        "rrd_optimize": {"status": "skipped", "profile": "none"},
        "artifact_validation": "basic",
        "artifact_checks": {
            "mode": "basic",
            "recording_exists": True,
            "blueprint_exists": True,
            "recording_non_empty": True,
            "blueprint_non_empty": True,
        },
        "catalog_registration": {
            "enabled": False,
            "dataset_name": "",
            "server_url": None,
            "managed_local": False,
            "status": "disabled",
        },
    }
    assert recording["params"]["rerun_artifact"] == result["artifact_info"]
    assert recording["artifact_status"]["status"] == "ready"
    assert recording["artifact_status"]["recording_size_bytes"] == 3


def test_build_recording_persists_enabled_artifact_options(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace, project, source, mapping = _mapped_csv_workspace(tmp_path)
    requests: list[ConvertRequest] = []
    _install_fake_artifact_writers(
        monkeypatch,
        recording_payload=b"rrd",
        blueprint_payload=b"rbl",
        requests=requests,
    )

    def fake_optimize(
        path: Path,
        profile: str,
        *,
        cancel_check=None,
    ) -> dict:
        path.write_bytes(b"optimized rrd")
        return {"status": "optimized", "profile": profile}

    def fake_validate(
        recording_path: Path,
        blueprint_path: Path,
        mode: str,
        *,
        output_dir: Path,
        cancel_check=None,
    ) -> dict:
        return {"mode": mode, "verify": {"status": "passed"}}

    def fake_register(recording_path: Path, registration: dict) -> dict:
        return {
            **registration,
            "status": "registered",
            "recording_uri": recording_path.absolute().as_uri(),
        }

    monkeypatch.setattr(workspace_module, "optimize_rrd", fake_optimize)
    monkeypatch.setattr(workspace_module, "validate_artifacts", fake_validate)
    monkeypatch.setattr(workspace_module, "register_recording_with_catalog", fake_register)
    monkeypatch.setattr(
        workspace_module,
        "require_supported_artifact_options",
        lambda **kwargs: None,
    )

    result = workspace.build_recording(
        project["id"],
        source["id"],
        mapping_id=mapping["id"],
        output_name="advanced_artifact",
        mcap_decoders=["ros2msg", "foxglove"],
        rrd_optimize_profile="object-store",
        artifact_validation="verify",
        catalog_registration={
            "enabled": True,
            "dataset_name": "robot_runs",
            "server_url": "rerun+http://127.0.0.1:51234",
            "managed_local": False,
        },
    )

    artifact_info = result["artifact_info"]
    assert requests[0].mcap_decoders == ["ros2msg", "foxglove"]
    assert artifact_info["mcap_decoders"] == ["ros2msg", "foxglove"]
    assert artifact_info["rrd_optimize"] == {
        "status": "optimized",
        "profile": "object-store",
    }
    assert artifact_info["artifact_checks"] == {
        "mode": "verify",
        "verify": {"status": "passed"},
    }
    assert artifact_info["catalog_registration"]["status"] == "registered"
    assert artifact_info["catalog_registration"]["dataset_name"] == "robot_runs"


def test_recording_artifact_status_reports_missing_and_empty_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace, project, source, mapping = _mapped_csv_workspace(tmp_path)
    _install_fake_artifact_writers(monkeypatch, recording_payload=b"rrd", blueprint_payload=b"rbl")
    result = workspace.build_recording(
        project["id"],
        source["id"],
        mapping_id=mapping["id"],
        output_name="status_run",
    )

    Path(result["recording_path"]).unlink()
    missing = workspace.get_recording(result["recording_id"])
    assert missing["artifact_status"]["status"] == "missing"

    Path(result["recording_path"]).write_bytes(b"")
    empty = workspace.get_recording(result["recording_id"])
    assert empty["artifact_status"]["status"] == "empty"


@pytest.mark.parametrize(
    ("recording_payload", "blueprint_payload"),
    [(b"", b"rbl"), (b"rrd", b"")],
)
def test_build_recording_rejects_empty_artifacts(
    tmp_path: Path,
    monkeypatch,
    recording_payload: bytes,
    blueprint_payload: bytes,
) -> None:
    workspace, project, source, mapping = _mapped_csv_workspace(tmp_path)
    _install_fake_artifact_writers(
        monkeypatch,
        recording_payload=recording_payload,
        blueprint_payload=blueprint_payload,
    )

    with pytest.raises(RerunArtifactError) as exc_info:
        workspace.build_recording(
            project["id"],
            source["id"],
            mapping_id=mapping["id"],
            output_name="empty_artifact",
        )

    recording_path = Path(project["workspace_path"]) / "recordings" / "empty_artifact.rrd"
    blueprint_path = Path(project["workspace_path"]) / "blueprints" / "empty_artifact.rbl"
    job = workspace.list_jobs(project["id"])[0]
    assert exc_info.value.code == "rerun_artifact_invalid"
    assert job["status"] == "failed"
    assert job["error"]["code"] == "rerun_artifact_invalid"
    assert not recording_path.exists()
    assert not blueprint_path.exists()
    assert workspace.list_recordings(project["id"]) == []


def test_build_recording_rejects_missing_artifact(tmp_path: Path, monkeypatch) -> None:
    workspace, project, source, mapping = _mapped_csv_workspace(tmp_path)

    class MissingRecordingAdapter:
        def convert(self, request: ConvertRequest) -> None:
            Path(request.output_rrd).unlink(missing_ok=True)

    monkeypatch.setattr(
        Workspace,
        "_adapter_for_path",
        lambda self, path, source_type=None: MissingRecordingAdapter(),
    )
    monkeypatch.setattr(
        workspace_module,
        "save_blueprint",
        lambda spec, template_id, path: Path(path).write_bytes(b"rbl"),
    )

    with pytest.raises(RerunArtifactError):
        workspace.build_recording(
            project["id"],
            source["id"],
            mapping_id=mapping["id"],
            output_name="missing_artifact",
        )

    assert not (Path(project["workspace_path"]) / "blueprints" / "missing_artifact.rbl").exists()


def test_converter_ids_are_stable() -> None:
    assert _converter_id("mcap") == "rerun_mcap_cli"
    assert _converter_id("ros2_db3") == "ros2_db3_to_mcap_to_rerun_cli"
    assert _converter_id("csv") == "rerun_python_sdk"
    assert _converter_id("custom") == "adapter_python"


def test_normalize_mcap_decoders_rejects_unknown_decoder() -> None:
    with pytest.raises(ValueError, match="Unsupported MCAP decoder"):
        artifact_module.normalize_mcap_decoders(["ros2msg", "unknown"])


def test_optimize_rrd_replaces_input_with_temp_output(tmp_path: Path, monkeypatch) -> None:
    recording_path = tmp_path / "run.rrd"
    recording_path.write_bytes(b"original")
    commands = []

    def fake_run(args, *, cancel_check=None):
        commands.append(args)
        output = Path(args[args.index("-o") + 1])
        output.write_bytes(b"optimized")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(artifact_module, "require_rerun_033_feature", lambda feature: None)
    monkeypatch.setattr(artifact_module, "_run_rerun", fake_run)

    result = artifact_module.optimize_rrd(recording_path, "live")

    assert result == {"status": "optimized", "profile": "live"}
    assert recording_path.read_bytes() == b"optimized"
    assert commands == [
        [
            "rrd",
            "optimize",
            str(recording_path),
            "--profile",
            "live",
            "-o",
            str(tmp_path / "run.optimized.tmp.rrd"),
        ]
    ]
    assert not (tmp_path / "run.optimized.tmp.rrd").exists()


def test_validate_artifacts_strict_runs_verify_stats_and_headless(
    tmp_path: Path,
    monkeypatch,
) -> None:
    recording_path = tmp_path / "run.rrd"
    blueprint_path = tmp_path / "run.rbl"
    recording_path.write_bytes(b"rrd")
    blueprint_path.write_bytes(b"rbl")
    commands = []

    def fake_run(args, *, cancel_check=None):
        commands.append(args)
        if "--screenshot-to" in args:
            Path(args[args.index("--screenshot-to") + 1]).write_bytes(b"png")
        return subprocess.CompletedProcess(args, 0, "ok", "")

    monkeypatch.setattr(artifact_module, "require_rerun_033_feature", lambda feature: None)
    monkeypatch.setattr(artifact_module, "_run_rerun", fake_run)

    checks = artifact_module.validate_artifacts(
        recording_path,
        blueprint_path,
        "strict",
        output_dir=tmp_path,
    )

    assert commands[0] == ["rrd", "verify", str(recording_path)]
    assert commands[1] == ["rrd", "stats", "--no-decode", str(recording_path)]
    assert commands[2][:4] == ["--headless", "--window-size", "1280x720", "--screenshot-to"]
    assert checks["verify"]["status"] == "passed"
    assert checks["stats"]["status"] == "passed"
    assert checks["headless_screenshot"]["size_bytes"] == 3


def test_rerun_features_disable_033_on_legacy_intel_mac(monkeypatch) -> None:
    monkeypatch.setattr(artifact_module, "rerun_version", lambda: "0.33.0")
    monkeypatch.setattr(artifact_module.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(artifact_module.platform, "machine", lambda: "x86_64")

    features = artifact_module.rerun_features()

    assert features["legacy_intel_mac"] is True
    assert features["rerun_033"] is False
    with pytest.raises(RuntimeError, match="requires rerun-sdk 0.33\\+"):
        artifact_module.require_rerun_033_feature("rrd_optimize")


def test_require_supported_artifact_options_rejects_unsupported_mcap_decoders(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        artifact_module,
        "rerun_features",
        lambda: {
            "rerun_033": False,
            "mcap_decoders": False,
            "rrd_optimize": False,
            "artifact_verify": False,
            "headless_screenshot": False,
            "catalog": False,
            "legacy_intel_mac": False,
        },
    )
    monkeypatch.setattr(artifact_module, "rerun_version", lambda: "0.32.2")

    with pytest.raises(RuntimeError, match="requires rerun-sdk 0.33\\+"):
        artifact_module.require_supported_artifact_options(
            mcap_decoders=["ros2msg"],
            rrd_optimize_profile="none",
            artifact_validation="basic",
            catalog_registration={"enabled": False},
        )


def test_catalog_registration_uses_rerun_catalog_client(
    tmp_path: Path,
    monkeypatch,
) -> None:
    recording_path = tmp_path / "run.rrd"
    recording_path.write_bytes(b"rrd")
    calls: dict[str, object] = {}

    class FakeRegistration:
        def wait(self) -> None:
            calls["waited"] = True

    class FakeDataset:
        def register(self, uris: list[str]) -> FakeRegistration:
            calls["uris"] = uris
            return FakeRegistration()

    class FakeCatalogClient:
        def __init__(self, server_url: str) -> None:
            calls["server_url"] = server_url

        def create_dataset(self, name: str, *, exist_ok: bool) -> FakeDataset:
            calls["dataset_name"] = name
            calls["exist_ok"] = exist_ok
            return FakeDataset()

    fake_rerun = SimpleNamespace(
        catalog=SimpleNamespace(CatalogClient=FakeCatalogClient)
    )
    monkeypatch.setattr(artifact_module, "require_rerun_033_feature", lambda feature: None)
    monkeypatch.setitem(sys.modules, "rerun", fake_rerun)

    result = artifact_module.register_recording_with_catalog(
        recording_path,
        {
            "enabled": True,
            "dataset_name": "robot_runs",
            "server_url": "rerun+http://127.0.0.1:51234",
            "managed_local": False,
        },
    )

    assert calls == {
        "server_url": "rerun+http://127.0.0.1:51234",
        "dataset_name": "robot_runs",
        "exist_ok": True,
        "uris": [recording_path.absolute().as_uri()],
        "waited": True,
    }
    assert result["status"] == "registered"
    assert result["recording_uri"] == recording_path.absolute().as_uri()


def _mapped_csv_workspace(tmp_path: Path) -> tuple[Workspace, dict, dict, dict]:
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("time,value\n1,2\n2,3\n", encoding="utf-8")
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Artifacts")
    source = workspace.add_source(project["id"], str(csv_path))
    workspace.inspect_source(source["id"])
    spec = workspace.suggest_mapping(source["id"])
    mapping = workspace.save_mapping(project["id"], source["id"], spec)
    return workspace, project, source, mapping


def _install_fake_artifact_writers(
    monkeypatch,
    *,
    recording_payload: bytes,
    blueprint_payload: bytes,
    requests: list[ConvertRequest] | None = None,
) -> None:
    class FakeAdapter:
        def convert(self, request: ConvertRequest) -> None:
            if requests is not None:
                requests.append(request)
            Path(request.output_rrd).write_bytes(recording_payload)

    monkeypatch.setattr(
        Workspace,
        "_adapter_for_path",
        lambda self, path, source_type=None: FakeAdapter(),
    )
    monkeypatch.setattr(
        workspace_module,
        "save_blueprint",
        lambda spec, template_id, path: Path(path).write_bytes(blueprint_payload),
    )
