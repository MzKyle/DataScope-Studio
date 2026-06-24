import { invoke } from "@tauri-apps/api/core";

import { apiErrorLogContext, logDiagnostic } from "./diagnostic-log";
import type {
  DiagnosticReport,
  DiagnosticThresholds,
  DiskEstimate,
  Job,
  MappingPayload,
  MappingDiff,
  MappingTemplateItem,
  MappingValidation,
  Plugin,
  Project,
  ProjectExportResult,
  ProjectImportResult,
  QueryExportResult,
  QueryResult,
  QueryTemplate,
  Recording,
  Source,
  SchemaProfile,
  StreamInfo,
  TemplateMatch,
  TemplateRegistryItem
} from "./types";

const API_BASE = import.meta.env.VITE_DATASCOPE_API ?? "http://127.0.0.1:8000";
const NETWORK_RETRIES = 2;

type TauriInternalsWindow = Window & {
  __TAURI_INTERNALS__?: unknown;
};

type ApiCommandResponse = {
  status: number;
  body: string;
};

export type ApiStatus = {
  status: string;
  port: number;
  packaged_runtime: boolean;
  runtime_dir: string | null;
  rerun_available: boolean;
  log_dir: string;
  desktop_log_path: string;
  backend_log_path: string;
};

export type ApiErrorDetails = {
  output_name?: string;
  paths?: string[];
  validation?: MappingValidation;
  [key: string]: unknown;
};

export class ApiError extends Error {
  status: number;
  code: string;
  details: ApiErrorDetails;

  constructor(message: string, status = 0, code = "request_failed", details: ApiErrorDetails = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function asApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  if (error instanceof Error) return new ApiError(error.message);
  return new ApiError(String(error));
}

function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function fetchWithRetry(url: string, init: RequestInit): Promise<Response> {
  let lastError: unknown;
  for (let attempt = 0; attempt <= NETWORK_RETRIES; attempt += 1) {
    try {
      return await fetch(url, init);
    } catch (err) {
      lastError = err;
      if (attempt < NETWORK_RETRIES) await delay(180 * (attempt + 1));
    }
  }
  throw lastError;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = init?.method ?? "GET";
  try {
    const headers = new Headers(init?.headers);
    if (init?.body && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    if (isTauriRuntime()) {
      const body = typeof init?.body === "string" ? init.body : undefined;
      const result = await invoke<ApiCommandResponse>("api_request", {
        request: {
          method,
          path,
          body
        }
      });
      const parsedBody = parseBody(result.body);
      if (result.status < 200 || result.status >= 300) {
        throw apiErrorFromResponse(parsedBody, result.status, `HTTP ${result.status}`);
      }
      return parsedBody as T;
    }
    const response = await fetchWithRetry(`${API_BASE}${path}`, {
      headers,
      ...init
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw apiErrorFromResponse(body, response.status, response.statusText);
    }
    return body as T;
  } catch (error) {
    const apiError = asApiError(error);
    logDiagnostic(
      apiError.status >= 500 || apiError.status === 0 ? "error" : "warn",
      "frontend.api",
      apiError.message,
      apiErrorLogContext(method, path, apiError.status, apiError.code, apiError.details)
    );
    throw error;
  }
}

function isTauriRuntime() {
  return Boolean((window as TauriInternalsWindow).__TAURI_INTERNALS__);
}

function parseBody(body: string): unknown {
  if (!body) return {};
  return JSON.parse(body);
}

export function apiErrorFromResponse(body: unknown, status: number, fallbackMessage: string) {
  const responseBody = isRecord(body) ? body : {};
  const detail = isRecord(responseBody.detail) ? responseBody.detail : {};
  const rawError = isRecord(responseBody.error)
    ? responseBody.error
    : isRecord(detail.error)
      ? detail.error
      : {};
  const message = typeof rawError.message === "string" ? rawError.message : fallbackMessage;
  const code = typeof rawError.code === "string" ? rawError.code : "http_error";
  const details = Object.fromEntries(
    Object.entries(rawError).filter(([key]) => key !== "message" && key !== "code")
  );
  return new ApiError(message, status, code, details);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export const api = {
  status: () => invoke<ApiStatus>("api_status"),
  projects: () => request<Project[]>("/api/projects"),
  createProject: (name: string) =>
    request<Project>("/api/projects", {
      method: "POST",
      body: JSON.stringify({ name })
    }),
  addSource: (
    projectId: string,
    path: string,
    storageMode: "copy" | "reference" = "copy",
    importOptions: Record<string, unknown> = {}
  ) =>
    request<Source>(`/api/projects/${projectId}/sources`, {
      method: "POST",
      body: JSON.stringify({
        path,
        storage_mode: storageMode,
        import_options: importOptions
      })
    }),
  estimateSourceImport: (
    projectId: string,
    path: string,
    storageMode: "copy" | "reference" = "copy"
  ) =>
    request<DiskEstimate>(`/api/projects/${projectId}/estimates/source-import`, {
      method: "POST",
      body: JSON.stringify({ path, storage_mode: storageMode })
    }),
  inspect: (sourceId: string) =>
    request<{ source: Source; streams: StreamInfo[]; schema_profile: SchemaProfile }>(`/api/sources/${sourceId}/inspect`, {
      method: "POST"
    }),
  sources: (projectId: string) => request<Source[]>(`/api/projects/${projectId}/sources`),
  preview: (sourceId: string, streamId: string) =>
    request<{ columns: string[]; rows: Record<string, unknown>[] }>(
      `/api/sources/${sourceId}/preview?stream_id=${encodeURIComponent(streamId)}&limit=25`
    ),
  suggestMapping: (sourceId: string) =>
    request<MappingPayload>(`/api/sources/${sourceId}/mapping/suggest`),
  suggestMappingForTemplate: (sourceId: string, templateId: string) =>
    request<MappingPayload>(
      `/api/sources/${sourceId}/mapping/suggest?template_id=${encodeURIComponent(templateId)}`
    ),
  suggestTemplates: (sourceId: string) =>
    request<TemplateMatch[]>(`/api/sources/${sourceId}/templates/suggest`),
  previewMapping: (sourceId: string, mapping: MappingPayload["mapping"]) =>
    request<{
      mapping: MappingPayload["mapping"];
      schema_profile: SchemaProfile;
      validation: MappingValidation;
      preview: { columns: string[]; rows: Record<string, unknown>[] };
    }>(`/api/sources/${sourceId}/mapping/preview`, {
      method: "POST",
      body: JSON.stringify({ mapping })
    }),
  validateMapping: (sourceId: string, mapping: MappingPayload["mapping"]) =>
    request<MappingValidation>(`/api/sources/${sourceId}/mapping/validate`, {
      method: "POST",
      body: JSON.stringify({ mapping })
    }),
  saveMapping: (sourceId: string, mapping: MappingPayload["mapping"], confirmed = false) =>
    request<{ id: string; path: string }>(`/api/sources/${sourceId}/mapping`, {
      method: "POST",
      body: JSON.stringify({ mapping, confirmed })
    }),
  confirmMapping: (mappingId: string) =>
    request<{ mapping: { id: string; path: string }; validation: MappingValidation }>(
      `/api/mappings/${mappingId}/confirm`,
      { method: "POST" }
    ),
  build: (
    projectId: string,
    sourceId: string,
    mappingId: string,
    outputName: string,
    templateId: string,
    outputDir?: string
  ) =>
    request<Job>("/api/recordings/build", {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId,
        source_id: sourceId,
        mapping_id: mappingId,
        template_id: templateId,
        output_name: outputName,
        output_dir: outputDir || null
      })
    }),
  estimateBuild: (projectId: string, sourceId: string) =>
    request<DiskEstimate>(`/api/projects/${projectId}/estimates/build/${sourceId}`, {
      method: "POST"
    }),
  open: (recordingPath: string, blueprintPath?: string) =>
    request<{ status: string; pid: number }>("/api/viewer/open", {
      method: "POST",
      body: JSON.stringify({ recording_path: recordingPath, blueprint_path: blueprintPath })
    }),
  recordings: (projectId: string) => request<Recording[]>(`/api/projects/${projectId}/recordings`),
  jobs: (projectId: string) => request<Job[]>(`/api/projects/${projectId}/jobs`),
  job: (jobId: string) => request<Job>(`/api/jobs/${jobId}`),
  cancelJob: (jobId: string) =>
    request<Job>(`/api/jobs/${jobId}/cancel`, { method: "POST" }),
  retryJob: (jobId: string) =>
    request<Job>(`/api/jobs/${jobId}/retry`, { method: "POST" }),
  patchRecording: (recordingId: string, payload: Partial<Pick<Recording, "run_name" | "tags" | "params">> & { add_tags?: string[]; remove_tags?: string[] }) =>
    request<Recording>(`/api/recordings/${recordingId}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  queryTemplates: (projectId: string) =>
    request<QueryTemplate[]>(`/api/projects/${projectId}/query/templates`),
  query: (
    projectId: string,
    templateId: string,
    recordingIds: string[],
    params: Record<string, unknown>,
    limit = 1000
  ) =>
    request<QueryResult>(`/api/projects/${projectId}/query`, {
      method: "POST",
      body: JSON.stringify({
        template_id: templateId,
        recording_ids: recordingIds.length ? recordingIds : null,
        params,
        limit
      })
    }),
  exportQuery: (
    projectId: string,
    templateId: string,
    recordingIds: string[],
    params: Record<string, unknown>,
    format = "csv",
    limit = 1000
  ) =>
    request<QueryExportResult>(`/api/projects/${projectId}/query/export`, {
      method: "POST",
      body: JSON.stringify({
        template_id: templateId,
        recording_ids: recordingIds.length ? recordingIds : null,
        params,
        format,
        limit
      })
    }),
  diagnostics: (
    projectId: string,
    recordingIds: string[],
    thresholds: DiagnosticThresholds,
    limit = 1000
  ) =>
    request<DiagnosticReport>(`/api/projects/${projectId}/diagnostics`, {
      method: "POST",
      body: JSON.stringify({
        recording_ids: recordingIds.length ? recordingIds : null,
        thresholds,
        limit
      })
    }),
  plugins: () => request<Plugin[]>("/api/plugins"),
  installPlugin: (path: string) =>
    request<Plugin>("/api/plugins/install", {
      method: "POST",
      body: JSON.stringify({ path })
    }),
  templates: () => request<TemplateRegistryItem[]>("/api/templates"),
  installTemplate: (path: string) =>
    request<TemplateRegistryItem>("/api/templates/install", {
      method: "POST",
      body: JSON.stringify({ path })
    }),
  mappingTemplates: () => request<MappingTemplateItem[]>("/api/mapping-templates"),
  createMappingTemplate: (
    name: string,
    sourceId: string,
    mappingId: string,
    templateId?: string
  ) =>
    request<MappingTemplateItem>("/api/mapping-templates", {
      method: "POST",
      body: JSON.stringify({
        name,
        source_id: sourceId,
        mapping_id: mappingId,
        template_id: templateId || null
      })
    }),
  saveMappingTemplate: (templateId: string, config: MappingTemplateItem["config"]) =>
    request<MappingTemplateItem>(`/api/mapping-templates/${templateId}`, {
      method: "PUT",
      body: JSON.stringify({ config, enabled: true })
    }),
  deleteMappingTemplate: (templateId: string) =>
    request<{ deleted: string }>(`/api/mapping-templates/${templateId}`, {
      method: "DELETE"
    }),
  importMappingTemplate: (path: string) =>
    request<MappingTemplateItem>("/api/mapping-templates/import", {
      method: "POST",
      body: JSON.stringify({ path, enabled: true })
    }),
  exportMappingTemplate: (templateId: string, outputPath?: string) =>
    request<{ template_id: string; path: string }>(
      `/api/mapping-templates/${templateId}/export`,
      {
        method: "POST",
        body: JSON.stringify({ output_path: outputPath || null })
      }
    ),
  applyMappingTemplate: (templateId: string, sourceId: string) =>
    request<{
      mapping: MappingPayload["mapping"];
      validation: MappingValidation;
      match_issues: MappingValidation["issues"];
    }>(`/api/mapping-templates/${templateId}/apply`, {
      method: "POST",
      body: JSON.stringify({ source_id: sourceId })
    }),
  diffMappingTemplate: (
    projectId: string,
    templateId: string,
    leftSourceId: string,
    rightSourceId: string
  ) =>
    request<MappingDiff>(`/api/projects/${projectId}/mapping-diff`, {
      method: "POST",
      body: JSON.stringify({
        template_id: templateId,
        left_source_id: leftSourceId,
        right_source_id: rightSourceId
      })
    }),
  batchImport: (
    projectId: string,
    patterns: string[],
    templateId: string,
    outputPrefix: string,
    storageMode: "copy" | "reference" = "copy"
  ) =>
    request<Job>("/api/batch/import", {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId,
        patterns,
        template_id: templateId,
        output_prefix: outputPrefix,
        storage_mode: storageMode
      })
    }),
  compare: (
    projectId: string,
    recordingIds: string[],
    metricKeys: string[],
    mode = "summary",
    limit = 1000
  ) =>
    request<QueryResult>("/api/compare", {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId,
        recording_ids: recordingIds,
        metric_keys: metricKeys,
        mode,
        limit
      })
    }),
  exportProject: (projectId: string, outputPath?: string) =>
    request<ProjectExportResult>(`/api/projects/${projectId}/export`, {
      method: "POST",
      body: JSON.stringify({ output_path: outputPath || null })
    }),
  estimateProjectExport: (projectId: string, outputPath?: string) =>
    request<DiskEstimate>(`/api/projects/${projectId}/estimates/export`, {
      method: "POST",
      body: JSON.stringify({ output_path: outputPath || null })
    }),
  importProjectPackage: (path: string) =>
    request<ProjectImportResult>("/api/projects/import", {
      method: "POST",
      body: JSON.stringify({ path })
    })
};
