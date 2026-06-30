from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from datascope_core.mapping import mapping_from_yaml_dict, mapping_to_yaml_dict
from datascope_core.mapping_validation import MappingValidationError
from datascope_core.version import __version__
from datascope_core.viewer import open_recording
from datascope_core.workspace import (
    ArtifactConflictError,
    DiskSpaceError,
    SourceUnavailableError,
    Workspace,
)
from datascope_api.services import services


logger = logging.getLogger("uvicorn.error.datascope")


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1)
    workspace_path: str | None = None
    description: str = ""


class SourceCreate(BaseModel):
    path: str = Field(min_length=1)
    storage_mode: str = "copy"
    import_options: dict[str, Any] = Field(default_factory=dict)


class SourceEstimateRequest(BaseModel):
    path: str = Field(min_length=1)
    storage_mode: str = "copy"


class MappingCreate(BaseModel):
    mapping: dict[str, Any] | None = None
    confirmed: bool = False


class MappingTemplateCreate(BaseModel):
    name: str = Field(min_length=1)
    source_id: str
    mapping_id: str
    template_id: str | None = None


class MappingTemplateSave(BaseModel):
    config: dict[str, Any]
    enabled: bool = True


class MappingTemplateImport(BaseModel):
    path: str = Field(min_length=1)
    enabled: bool = True


class MappingTemplateExport(BaseModel):
    output_path: str | None = None


class MappingTemplateApply(BaseModel):
    source_id: str


class MappingTemplateDiff(BaseModel):
    template_id: str
    left_source_id: str
    right_source_id: str


class BuildRecordingRequest(BaseModel):
    project_id: str
    source_id: str
    mapping_id: str | None = None
    template_id: str = "sensor_monitor"
    output_name: str | None = None
    output_dir: str | None = None


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
    storage_mode: str = "copy"


class BatchEstimateRequest(BaseModel):
    patterns: list[str] = Field(min_length=1)
    storage_mode: str = "copy"


class CompareRequest(BaseModel):
    project_id: str
    recording_ids: list[str] = Field(default_factory=list)
    metric_keys: list[str] = Field(default_factory=list)
    mode: str = "summary"
    limit: int = Field(default=1000, ge=1, le=10000)


class DiagnosticsRequest(BaseModel):
    recording_ids: list[str] | None = None
    thresholds: dict[str, float] = Field(default_factory=dict)
    preset: str | None = None
    limit: int = Field(default=1000, ge=1, le=10000)


class DiagnosticsExportRequest(DiagnosticsRequest):
    format: str = "json"
    output_path: str | None = None


class ProjectExportRequest(BaseModel):
    output_path: str | None = None


class ProjectImportRequest(BaseModel):
    path: str = Field(min_length=1)
    project_name: str | None = None


class JobSettingsPatch(BaseModel):
    max_workers: int = Field(ge=1, le=4)


@asynccontextmanager
async def _lifespan(_: FastAPI):
    _workspace()
    try:
        yield
    finally:
        services.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="DataScope Studio API",
        version=__version__,
        lifespan=_lifespan,
    )
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
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        error = detail.get("error", {}) if isinstance(detail, dict) else {}
        code = error.get("code", "http_error") if isinstance(error, dict) else "http_error"
        message = _log_text(
            error.get("message", str(detail)) if isinstance(error, dict) else str(detail)
        )
        logger.warning(
            "api_error method=%s path=%s status=%s code=%s message=%s",
            request.method,
            request.url.path,
            exc.status_code,
            code,
            message,
        )
        if isinstance(detail, dict) and "error" in detail:
            return JSONResponse(status_code=exc.status_code, content=detail)
        return _api_error(exc.status_code, "http_error", str(detail))

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        logger.warning(
            "api_validation_error method=%s path=%s errors=%s",
            request.method,
            request.url.path,
            len(exc.errors()),
        )
        return _api_error(422, "validation_error", str(exc))

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "api_unhandled_exception method=%s path=%s",
            request.method,
            request.url.path,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
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
        return _guard(
            lambda: _workspace().add_source(
                project_id,
                payload.path,
                storage_mode=payload.storage_mode,
                import_options=payload.import_options,
            )
        )

    @app.post("/api/projects/{project_id}/estimates/source-import")
    def estimate_source_import(
        project_id: str,
        payload: SourceEstimateRequest,
    ) -> dict[str, Any]:
        return _guard(
            lambda: _workspace().estimate_source_import(
                project_id,
                payload.path,
                storage_mode=payload.storage_mode,
            )
        )

    @app.get("/api/projects/{project_id}/sources")
    def list_sources(project_id: str) -> list[dict[str, Any]]:
        return _guard(lambda: _workspace().list_sources(project_id))

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
        return _guard(
            lambda: mapping_to_yaml_dict(
                _workspace().suggest_mapping(source_id, template_id)
            )
        )

    @app.post("/api/sources/{source_id}/mapping/preview")
    def preview_mapping(source_id: str, payload: MappingCreate) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            workspace = _workspace()
            spec = (
                mapping_from_yaml_dict({"mapping": payload.mapping})
                if payload.mapping is not None
                else workspace.suggest_mapping(source_id)
            )
            return workspace.mapping_preview(source_id, spec)

        return _guard(run)

    @app.post("/api/sources/{source_id}/mapping/validate")
    def validate_source_mapping(source_id: str, payload: MappingCreate) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            workspace = _workspace()
            spec = (
                mapping_from_yaml_dict({"mapping": payload.mapping})
                if payload.mapping is not None
                else workspace.suggest_mapping(source_id)
            )
            return workspace.validate_mapping_spec(source_id, spec)

        return _guard(run)

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
            return workspace.save_mapping(
                source["project_id"],
                source_id,
                spec,
                confirmed=payload.confirmed,
            )

        return _guard(run)

    @app.post("/api/mappings/{mapping_id}/confirm")
    def confirm_mapping(mapping_id: str) -> dict[str, Any]:
        return _guard(lambda: _workspace().confirm_mapping(mapping_id))

    @app.get("/api/mappings/{mapping_id}/validate")
    def validate_saved_mapping(mapping_id: str) -> dict[str, Any]:
        return _guard(lambda: _workspace().validate_saved_mapping(mapping_id))

    @app.post("/api/recordings/build", status_code=202)
    def build_recording(payload: BuildRecordingRequest) -> dict[str, Any]:
        def enqueue() -> dict[str, Any]:
            job = _workspace().enqueue_build_recording(
                payload.project_id,
                payload.source_id,
                mapping_id=payload.mapping_id,
                output_name=payload.output_name,
                template_id=payload.template_id,
                output_dir=payload.output_dir,
            )
            services.supervisor().wake()
            return job

        return _guard(enqueue)

    @app.post("/api/projects/{project_id}/estimates/build/{source_id}")
    def estimate_build(
        project_id: str,
        source_id: str,
        output_dir: str | None = None,
    ) -> dict[str, Any]:
        return _guard(
            lambda: _workspace().estimate_build(
                project_id,
                source_id,
                output_dir=output_dir,
            )
        )

    @app.get("/api/jobs/settings")
    def get_job_settings() -> dict[str, int]:
        return services.job_settings()

    @app.patch("/api/jobs/settings")
    def patch_job_settings(payload: JobSettingsPatch) -> dict[str, int]:
        return _guard(lambda: services.update_job_settings(max_workers=payload.max_workers))

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        return _guard(lambda: _workspace().get_job(job_id))

    @app.get("/api/projects/{project_id}/jobs")
    def list_jobs(project_id: str) -> list[dict[str, Any]]:
        return _guard(lambda: _workspace().list_jobs(project_id))

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict[str, Any]:
        job = _guard(lambda: _workspace().cancel_job(job_id))
        services.supervisor().wake()
        return job

    @app.post("/api/jobs/{job_id}/retry", status_code=202)
    def retry_job(job_id: str) -> dict[str, Any]:
        job = _guard(lambda: _workspace().retry_job(job_id))
        services.supervisor().wake()
        return job

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

    @app.post("/api/projects/{project_id}/diagnostics")
    def diagnostics(project_id: str, payload: DiagnosticsRequest) -> dict[str, Any]:
        return _guard(
            lambda: _workspace().run_diagnostics(
                project_id,
                recording_ids=payload.recording_ids,
                thresholds=payload.thresholds,
                preset=payload.preset,
                limit=payload.limit,
            )
        )

    @app.get("/api/projects/{project_id}/diagnostics/presets")
    def diagnostic_presets(project_id: str) -> list[dict[str, Any]]:
        return _guard(lambda: _workspace().diagnostic_presets(project_id))

    @app.post("/api/projects/{project_id}/diagnostics/export")
    def export_diagnostics(
        project_id: str,
        payload: DiagnosticsExportRequest,
    ) -> dict[str, Any]:
        return _guard(
            lambda: _workspace().export_diagnostics(
                project_id,
                recording_ids=payload.recording_ids,
                thresholds=payload.thresholds,
                preset=payload.preset,
                fmt=payload.format,
                output_path=payload.output_path,
                limit=payload.limit,
            )
        )

    @app.get("/api/projects/{project_id}/diagnostics/exports")
    def diagnostic_exports(project_id: str) -> list[dict[str, Any]]:
        return _guard(lambda: _workspace().list_diagnostic_exports(project_id))

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

    @app.get("/api/mapping-templates")
    def list_mapping_templates() -> list[dict[str, Any]]:
        return _guard(lambda: _workspace().list_mapping_templates())

    @app.post("/api/mapping-templates")
    def create_mapping_template(payload: MappingTemplateCreate) -> dict[str, Any]:
        return _guard(
            lambda: _workspace().create_mapping_template(
                payload.name,
                payload.source_id,
                payload.mapping_id,
                template_id=payload.template_id,
            )
        )

    @app.put("/api/mapping-templates/{template_id}")
    def save_mapping_template(template_id: str, payload: MappingTemplateSave) -> dict[str, Any]:
        config = dict(payload.config)
        template = dict(config.get("mapping_template", config))
        template["id"] = template_id
        return _guard(
            lambda: _workspace().save_mapping_template(
                {"mapping_template": template},
                enabled=payload.enabled,
            )
        )

    @app.delete("/api/mapping-templates/{template_id}")
    def delete_mapping_template(template_id: str) -> dict[str, Any]:
        return _guard(lambda: _workspace().delete_mapping_template(template_id))

    @app.post("/api/mapping-templates/import")
    def import_mapping_template(payload: MappingTemplateImport) -> dict[str, Any]:
        return _guard(
            lambda: _workspace().import_mapping_template(payload.path, enabled=payload.enabled)
        )

    @app.post("/api/mapping-templates/{template_id}/export")
    def export_mapping_template(
        template_id: str,
        payload: MappingTemplateExport,
    ) -> dict[str, Any]:
        return _guard(
            lambda: _workspace().export_mapping_template(
                template_id,
                output_path=payload.output_path,
            )
        )

    @app.post("/api/mapping-templates/{template_id}/apply")
    def apply_mapping_template(
        template_id: str,
        payload: MappingTemplateApply,
    ) -> dict[str, Any]:
        return _guard(
            lambda: _workspace().apply_mapping_template(template_id, payload.source_id)
        )

    @app.post("/api/projects/{project_id}/mapping-diff")
    def diff_mapping_template(
        project_id: str,
        payload: MappingTemplateDiff,
    ) -> dict[str, Any]:
        return _guard(
            lambda: _workspace().diff_mapping_template(
                project_id,
                payload.template_id,
                payload.left_source_id,
                payload.right_source_id,
            )
        )

    @app.post("/api/batch/import", status_code=202)
    def batch_import(payload: BatchImportRequest) -> dict[str, Any]:
        def enqueue() -> dict[str, Any]:
            job = _workspace().enqueue_batch_import(
                payload.project_id,
                payload.patterns,
                template_id=payload.template_id,
                output_prefix=payload.output_prefix,
                storage_mode=payload.storage_mode,
            )
            services.supervisor().wake()
            return job

        return _guard(enqueue)

    @app.get("/api/projects/{project_id}/batches")
    def list_batches(
        project_id: str,
        status: str | None = None,
        limit: int = Query(100, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        return _guard(lambda: _workspace().list_batches(project_id, status=status, limit=limit))

    @app.post("/api/projects/{project_id}/estimates/batch-import")
    def estimate_batch_import(
        project_id: str,
        payload: BatchEstimateRequest,
    ) -> dict[str, Any]:
        return _guard(
            lambda: _workspace().estimate_batch_import(
                project_id,
                payload.patterns,
                storage_mode=payload.storage_mode,
            )
        )

    @app.get("/api/batch/{batch_id}")
    def get_batch(batch_id: str) -> dict[str, Any]:
        return _guard(lambda: _workspace().get_batch(batch_id))

    @app.post("/api/batch/{batch_id}/items/{item_id}/retry", status_code=202)
    def retry_batch_item(batch_id: str, item_id: str) -> dict[str, Any]:
        job = _guard(lambda: _workspace().retry_batch_item(batch_id, item_id))
        services.supervisor().wake()
        return job

    @app.post("/api/batch/{batch_id}/items/{item_id}/cancel")
    def cancel_batch_item(batch_id: str, item_id: str) -> dict[str, Any]:
        return _guard(lambda: _workspace().cancel_batch_item(batch_id, item_id))

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

    @app.post("/api/projects/{project_id}/estimates/export")
    def estimate_project_export(
        project_id: str,
        payload: ProjectExportRequest | None = None,
    ) -> dict[str, Any]:
        output_path = payload.output_path if payload else None
        return _guard(
            lambda: _workspace().estimate_project_export(
                project_id,
                output_path=output_path,
            )
        )

    @app.post("/api/projects/import")
    def import_project(payload: ProjectImportRequest) -> dict[str, Any]:
        return _guard(lambda: _workspace().import_project_package(payload.path, project_name=payload.project_name))

    @app.post("/api/viewer/open")
    def viewer_open(payload: ViewerOpenRequest) -> dict[str, str | int]:
        return _guard(lambda: open_recording(payload.recording_path, payload.blueprint_path))

    return app


def _workspace() -> Workspace:
    return services.workspace()


def _guard(operation):
    try:
        return operation()
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "not_found", "message": str(exc)}},
        ) from exc
    except ArtifactConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "artifact_name_conflict",
                    "message": str(exc),
                    "output_name": exc.output_name,
                    "paths": exc.paths,
                }
            },
        ) from exc
    except DiskSpaceError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": exc.code,
                    "message": str(exc),
                    "estimate": exc.estimate,
                }
            },
        ) from exc
    except SourceUnavailableError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": exc.code,
                    "message": str(exc),
                    "source_id": exc.source_id,
                }
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "bad_request", "message": str(exc)}},
        ) from exc
    except MappingValidationError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "mapping_validation_failed",
                    "message": str(exc),
                    "validation": exc.report,
                }
            },
        ) from exc
    except RuntimeError as exc:
        code = getattr(exc, "code", "runtime_error")
        error: dict[str, Any] = {"code": str(code), "message": str(exc)}
        paths = getattr(exc, "paths", None)
        if isinstance(paths, list):
            error["paths"] = paths
        raise HTTPException(
            status_code=409,
            detail={"error": error},
        ) from exc


def _api_error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def _log_text(value: object) -> str:
    return str(value).replace("\r", "\\r").replace("\n", "\\n")


app = create_app()
