import json
from pathlib import Path

from PIL import Image
from typer.testing import CliRunner

from datascope_api.main import app as api_app
from datascope_cli.main import app as cli_app
from datascope_core.workspace import Workspace
from fastapi.testclient import TestClient
from tests.api_helpers import wait_for_job


def test_workspace_image_folder_to_rerun_artifacts(tmp_path: Path) -> None:
    image_dir = _make_cv_fixture(tmp_path)
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("CV Pipeline")
    source = workspace.add_source(project["id"], str(image_dir))
    inspection = workspace.inspect_source(source["id"])
    templates = workspace.suggest_templates(source["id"])
    spec = workspace.suggest_mapping(source["id"], template_id="cv_detection")
    mapping = workspace.save_mapping(project["id"], source["id"], spec)

    result = workspace.build_recording(
        project["id"],
        source["id"],
        mapping_id=mapping["id"],
        output_name="cv_run",
        template_id="cv_detection",
    )

    assert source["type"] == "image_folder"
    assert len(inspection["streams"]) >= 3
    assert templates[0]["template_id"] == "cv_detection"
    assert Path(result["recording_path"]).exists()
    assert Path(result["blueprint_path"]).exists()
    assert result["artifact_info"]["converter"] == "rerun_python_sdk"
    assert result["artifact_info"]["recording_size_bytes"] > 0


def test_workspace_single_tiff_image_to_rerun_artifacts(tmp_path: Path) -> None:
    image_path = tmp_path / "frame_001.tif"
    Image.new("RGB", (64, 48), (100, 160, 220)).save(image_path)
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Single Image Pipeline")
    source = workspace.add_source(project["id"], str(image_path))
    inspection = workspace.inspect_source(source["id"])
    spec = workspace.suggest_mapping(source["id"], template_id="cv_detection")
    mapping = workspace.save_mapping(project["id"], source["id"], spec)

    result = workspace.build_recording(
        project["id"],
        source["id"],
        mapping_id=mapping["id"],
        output_name="single_image_run",
        template_id="cv_detection",
    )

    assert source["type"] == "image_folder"
    assert inspection["source"]["metadata"]["image_count"] == 1
    assert inspection["streams"][0]["semantic_type"] == "image"
    assert Path(result["recording_path"]).exists()
    assert Path(result["blueprint_path"]).exists()


def test_api_image_folder_flow(tmp_path: Path, monkeypatch) -> None:
    image_dir = _make_cv_fixture(tmp_path)
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "api_workspace"))
    client = TestClient(api_app)

    project = client.post("/api/projects", json={"name": "CV API"}).json()
    source = client.post(
        f"/api/projects/{project['id']}/sources",
        json={"path": str(image_dir)},
    ).json()

    inspect_response = client.post(f"/api/sources/{source['id']}/inspect")
    assert inspect_response.status_code == 200

    template_response = client.get(f"/api/sources/{source['id']}/templates/suggest")
    assert template_response.status_code == 200
    assert template_response.json()[0]["template_id"] == "cv_detection"

    mapping_response = client.get(
        f"/api/sources/{source['id']}/mapping/suggest?template_id=cv_detection"
    )
    mapping = mapping_response.json()["mapping"]
    saved_mapping = client.post(
        f"/api/sources/{source['id']}/mapping",
        json={"mapping": mapping},
    ).json()

    build_response = client.post(
        "/api/recordings/build",
        json={
            "project_id": project["id"],
            "source_id": source["id"],
            "mapping_id": saved_mapping["id"],
            "template_id": "cv_detection",
            "output_name": "api_cv_run",
        },
    )
    assert build_response.status_code == 202
    job = wait_for_job(client, build_response.json()["id"])
    assert job["status"] == "succeeded"
    assert Path(job["result"]["recording_path"]).exists()


def test_cli_image_folder_import(tmp_path: Path, monkeypatch) -> None:
    image_dir = _make_cv_fixture(tmp_path)
    monkeypatch.setenv("DATASCOPE_WORKSPACE", str(tmp_path / "cli_workspace"))
    runner = CliRunner()

    inspect_result = runner.invoke(cli_app, ["inspect", str(image_dir)])
    assert inspect_result.exit_code == 0
    assert "Source type: image_folder" in inspect_result.output

    import_result = runner.invoke(
        cli_app,
        [
            "import",
            str(image_dir),
            "--project",
            "CV CLI",
            "--template",
            "cv_detection",
            "--out",
            "cli_cv_run",
        ],
    )
    assert import_result.exit_code == 0
    assert "Recording:" in import_result.output


def _make_cv_fixture(tmp_path: Path) -> Path:
    image_dir = tmp_path / "dataset" / "images"
    image_dir.mkdir(parents=True)
    for index, color in enumerate(((230, 60, 60), (60, 130, 230)), start=1):
        Image.new("RGB", (96, 64), color).save(image_dir / f"{index:06d}.png")

    classes = [{"id": 1, "label": "person", "color": [255, 80, 80]}]
    annotation_frames = []
    prediction_frames = []
    for index in (1, 2):
        annotation_frames.append(
            {
                "image": f"images/{index:06d}.png",
                "time": float(index - 1),
                "boxes": [{"bbox": [10, 12, 30, 24], "class_id": 1, "label": "person"}],
            }
        )
        prediction_frames.append(
            {
                "image": f"images/{index:06d}.png",
                "time": float(index - 1),
                "boxes": [
                    {
                        "bbox": [12, 14, 28, 22],
                        "class_id": 1,
                        "label": "person",
                        "score": 0.82,
                    }
                ],
            }
        )
    (tmp_path / "dataset" / "annotations.json").write_text(
        json.dumps({"classes": classes, "frames": annotation_frames}),
        encoding="utf-8",
    )
    (tmp_path / "dataset" / "predictions.json").write_text(
        json.dumps({"classes": classes, "frames": prediction_frames}),
        encoding="utf-8",
    )
    return image_dir
