from __future__ import annotations

import os
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from datascope_core.mapping import mapping_from_yaml_dict, mapping_to_yaml_dict
from datascope_core.viewer import open_recording
from datascope_core.workspace import Workspace


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1)
    workspace_path: str | None = None
    description: str = ""


class SourceCreate(BaseModel):
    path: str = Field(min_length=1)


class MappingCreate(BaseModel):
    mapping: dict[str, Any] | None = None


class BuildRecordingRequest(BaseModel):
    project_id: str
    source_id: str
    mapping_id: str | None = None
    template_id: str = "sensor_monitor"
    output_name: str = "run"


class ViewerOpenRequest(BaseModel):
    recording_path: str
    blueprint_path: str | None = None


class RecordingPatch(BaseModel):
    run_name: str | None = None
    tags: list[str] | None = None
    params: dict[str, Any] | None = None
    add_tags: list[str] | None = None
    remove_tags: list[str] | None = None


class QueryRequest(BaseModel):
    template_id: str
    recording_ids: list[str] | None = None
    params: dict[str, Any] = {}
    limit: int = Field(default=1000, ge=1, le=10000)


class QueryExportRequest(QueryRequest):
    format: str = "csv"
    output_path: str | None = None


class PluginInstallRequest(BaseModel):
    path: str = Field(min_length=1)
    enabled: bool = True


class TemplateInstallRequest(BaseModel):
    path: str = Field(min_length=1)
    enabled: bool = True


class BatchImportRequest(BaseModel):
    project_id: str
    patterns: list[str] = Field(min_length=1)
    template_id: str = "sensor_monitor"
    output_prefix: str = "batch_run"


class CompareRequest(BaseModel):
    project_id: str
    recording_ids: list[str] = Field(default_factory=list)
    metric_keys: list[str] = Field(default_factory=list)
    mode: str = "summary"
    limit: int = Field(default=1000, ge=1, le=10000)


class ProjectExportRequest(BaseModel):
    output_path: str | None = None


def create_app() -> FastAPI:
    app = FastAPI(title="DataScope Studio API", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:1420",
            "http://127.0.0.1:1420",
            "tauri://localhost",
            "http://tauri.localhost",
            "https://tauri.localhost",
            "null",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and "error" in detail:
            return JSONResponse(status_code=exc.status_code, content=detail)
        return _api_error(exc.status_code, "http_error", str(detail))

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_, exc: RequestValidationError) -> JSONResponse:
        return _api_error(422, "validation_error", str(exc))

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_, exc: Exception) -> JSONResponse:
        return _api_error(500, "internal_error", str(exc))

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/projects")
    def create_project(payload: ProjectCreate) -> dict[str, Any]:
        return _guard(
            lambda: _workspace().create_project(
                payload.name,
                workspace_path=payload.workspace_path,
                description=payload.description,
            )
        )

    @app.get("/api/projects")
    def list_projects() -> list[dict[str, Any]]:
        return _guard(lambda: _workspace().list_projects())

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        return _guard(lambda: _workspace().get_project(project_id))

    @app.post("/api/projects/{project_id}/sources")
    def add_source(project_id: str, payload: SourceCreate) -> dict[str, Any]:
        return _guard(lambda: _workspace().add_source(project_id, payload.path))

    @app.post("/api/sources/{source_id}/inspect")
    def inspect_source(source_id: str) -> dict[str, Any]:
        return _guard(lambda: _workspace().inspect_source(source_id))

    @app.get("/api/sources/{source_id}/streams")
    def get_streams(source_id: str) -> list[dict[str, Any]]:
        return _guard(lambda: [asdict(stream) for stream in _workspace().get_streams(source_id)])

    @app.get("/api/sources/{source_id}/preview")
    def preview_source(
        source_id: str,
        stream_id: str = Query(...),
        limit: int = Query(100, ge=1, le=1000),
    ) -> dict[str, Any]:
        return _guard(lambda: _workspace().preview_source(source_id, stream_id, limit=limit))

    @app.get("/api/sources/{source_id}/mapping/suggest")
    def suggest_mapping(source_id: str, template_id: str | None = None) -> dict[str, Any]:
        return _guard(lambda: mapping_to_yaml_dict(_workspace().suggest_mapping(source_id, template_id)))

    @app.get("/api/sources/{source_id}/templates/suggest")
    def suggest_templates(source_id: str) -> list[dict[str, float | str]]:
        return _guard(lambda: _workspace().suggest_templates(source_id))

    @app.post("/api/sources/{source_id}/mapping")
    def save_mapping(source_id: str, payload: MappingCreate) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            workspace = _workspace()
            source = workspace.get_source(source_id)
            spec = (
                mapping_from_yaml_dict({"mapping": payload.mapping})
                if payload.mapping is not None
                else workspace.suggest_mapping(source_id)
            )
            return workspace.save_mapping(source["project_id"], source_id, spec)

        return _guard(run)

    @app.post("/api/recordings/build")
    def build_recording(payload: BuildRecordingRequest) -> dict[str, Any]:
        return _guard(
            lambda: _workspace().build_recording(
                payload.project_id,
                payload.source_id,
                mapping_id=payload.mapping_id,
                output_name=payload.output_name,
                template_id=payload.template_id,
            )
        )

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        return _guard(lambda: _workspace().get_job(job_id))

    @app.get("/api/projects/{project_id}/jobs")
    def list_jobs(project_id: str) -> list[dict[str, Any]]:
        return _guard(lambda: _workspace().list_jobs(project_id))

    @app.get("/api/projects/{project_id}/recordings")
    def list_recordings(project_id: str) -> list[dict[str, Any]]:
        return _guard(lambda: _workspace().list_recordings(project_id))

    @app.get("/api/recordings/{recording_id}")
    def get_recording(recording_id: str) -> dict[str, Any]:
        return _guard(lambda: _workspace().get_recording(recording_id))

    @app.patch("/api/recordings/{recording_id}")
    def patch_recording(recording_id: str, payload: RecordingPatch) -> dict[str, Any]:
        return _guard(
            lambda: _workspace().update_recording(
                recording_id,
                run_name=payload.run_name,
                tags=payload.tags,
                params=payload.params,
                add_tags=payload.add_tags,
                remove_tags=payload.remove_tags,
            )
        )

    @app.get("/api/projects/{project_id}/query/templates")
    def query_templates(project_id: str) -> list[dict[str, Any]]:
        return _guard(lambda: _workspace().query_templates(project_id))

    @app.post("/api/projects/{project_id}/query")
    def query(project_id: str, payload: QueryRequest) -> dict[str, Any]:
        return _guard(
            lambda: _workspace().run_query(
                project_id,
                payload.template_id,
                recording_ids=payload.recording_ids,
                params=payload.params,
                limit=payload.limit,
            )
        )

    @app.post("/api/projects/{project_id}/query/export")
    def export_query(project_id: str, payload: QueryExportRequest) -> dict[str, Any]:
        return _guard(
            lambda: _workspace().export_query(
                project_id,
                payload.template_id,
                recording_ids=payload.recording_ids,
                params=payload.params,
                limit=payload.limit,
                fmt=payload.format,
                output_path=payload.output_path,
            )
        )

    @app.get("/api/plugins")
    def list_plugins() -> list[dict[str, Any]]:
        return _guard(lambda: _workspace().list_plugins())

    @app.post("/api/plugins/install")
    def install_plugin(payload: PluginInstallRequest) -> dict[str, Any]:
        return _guard(lambda: _workspace().install_plugin(payload.path, enabled=payload.enabled))

    @app.post("/api/plugins/validate")
    def validate_plugin(payload: PluginInstallRequest) -> dict[str, Any]:
        return _guard(lambda: _workspace().validate_plugin(payload.path))

    @app.get("/api/templates")
    def list_templates() -> list[dict[str, Any]]:
        return _guard(lambda: _workspace().list_templates())

    @app.post("/api/templates/install")
    def install_template(payload: TemplateInstallRequest) -> dict[str, Any]:
        return _guard(lambda: _workspace().install_template(payload.path, enabled=payload.enabled))

    @app.post("/api/templates/validate")
    def validate_template(payload: TemplateInstallRequest) -> dict[str, Any]:
        return _guard(lambda: _workspace().validate_template(payload.path))

    @app.post("/api/batch/import")
    def batch_import(payload: BatchImportRequest) -> dict[str, Any]:
        return _guard(
            lambda: _workspace().batch_import(
                payload.project_id,
                payload.patterns,
                template_id=payload.template_id,
                output_prefix=payload.output_prefix,
            )
        )

    @app.get("/api/batch/{batch_id}")
    def get_batch(batch_id: str) -> dict[str, Any]:
        return _guard(lambda: _workspace().get_batch(batch_id))

    @app.post("/api/compare")
    def compare(payload: CompareRequest) -> dict[str, Any]:
        return _guard(
            lambda: _workspace().compare(
                payload.project_id,
                payload.recording_ids,
                metric_keys=payload.metric_keys,
                mode=payload.mode,
                limit=payload.limit,
            )
        )

    @app.post("/api/projects/{project_id}/export")
    def export_project(project_id: str, payload: ProjectExportRequest | None = None) -> dict[str, Any]:
        output_path = payload.output_path if payload else None
        return _guard(lambda: _workspace().export_project(project_id, output_path=output_path))

    @app.post("/api/viewer/open")
    def viewer_open(payload: ViewerOpenRequest) -> dict[str, str | int]:
        return _guard(lambda: open_recording(payload.recording_path, payload.blueprint_path))

    return app


def _workspace() -> Workspace:
    return Workspace(os.environ.get("DATASCOPE_WORKSPACE"))


def _guard(operation):
    try:
        return operation()
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "not_found", "message": str(exc)}},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "bad_request", "message": str(exc)}},
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "runtime_error", "message": str(exc)}},
        ) from exc


def _api_error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


app = create_app()
