import { invoke } from "@tauri-apps/api/core";

import { apiErrorLogContext, logDiagnostic } from "./diagnostic-log";
import type {
  DiagnosticReport,
  DiagnosticExport,
  DiagnosticExportResult,
  DiagnosticPreset,
  DiagnosticThresholds,
  CustomQueryFilters,
  DiskEstimate,
  Job,
  JobSettings,
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
  Recipe,
  Recording,
  Source,
  SchemaProfile,
  StreamInfo,
  BatchResult,
  BatchSummary,
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

type JobListOptions = {
  activeOnly?: boolean;
  limit?: number;
};

type ImportWorkflowResult = {
  source: Source;
  streams: StreamInfo[];
  template_matches: TemplateMatch[];
  template_id: string;
  mapping: MappingPayload;
  saved_mapping: { id: string; path: string };
  preview: { columns: string[]; rows: Record<string, unknown>[] };
  schema_profile: SchemaProfile;
  validation: MappingValidation;
};

export type ApiStatus = {
  status: string;
  port: number;
  packaged_runtime: boolean;
  runtime_dir: string | null;
  rerun_available: boolean;
  rerun_version?: string | null;
  rerun_features?: RerunFeatures;
  log_dir: string;
  desktop_log_path: string;
  backend_log_path: string;
};

export type RerunFeatures = {
  rerun_033: boolean;
  mcap_decoders: boolean;
  rrd_optimize: boolean;
  artifact_verify: boolean;
  headless_screenshot: boolean;
  catalog: boolean;
  legacy_intel_mac: boolean;
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

let tauriApiBasePromise: Promise<string> | null = null;

function setTauriApiBase(status: ApiStatus) {
  tauriApiBasePromise = Promise.resolve(`http://127.0.0.1:${status.port}`);
}

function getTauriApiBase() {
  if (!tauriApiBasePromise) {
    tauriApiBasePromise = invoke<ApiStatus>("api_status").then((status) => {
      setTauriApiBase(status);
      return `http://127.0.0.1:${status.port}`;
    });
  }
  return tauriApiBasePromise;
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
    const requestInit = {
      ...init,
      headers
    };
    if (isTauriRuntime()) {
      try {
        return await requestWithFetch<T>(`${await getTauriApiBase()}${path}`, requestInit);
      } catch (error) {
        if (error instanceof ApiError) throw error;
        return await requestWithTauriProxy<T>(path, method, init);
      }
    }
    return await requestWithFetch<T>(`${API_BASE}${path}`, requestInit);
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

async function requestWithFetch<T>(url: string, init: RequestInit): Promise<T> {
  const response = await fetchWithRetry(url, init);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw apiErrorFromResponse(body, response.status, response.statusText);
  }
  return body as T;
}

async function requestWithTauriProxy<T>(
  path: string,
  method: string,
  init?: RequestInit
): Promise<T> {
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

function jobListQuery(options: JobListOptions): string {
  const params = new URLSearchParams();
  if (options.activeOnly) params.set("active_only", "true");
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  const query = params.toString();
  return query ? `?${query}` : "";
}

export const api = {
  status: async () => {
    const status = await invoke<ApiStatus>("api_status");
    setTauriApiBase(status);
    return status;
  },
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
  importWorkflow: (
    projectId: string,
    path: string,
    storageMode: "copy" | "reference" = "copy",
    importOptions: Record<string, unknown> = {},
    templateId?: string
  ) =>
    request<ImportWorkflowResult>(`/api/projects/${projectId}/sources/import-workflow`, {
      method: "POST",
      body: JSON.stringify({
        path,
        storage_mode: storageMode,
        import_options: importOptions,
        template_id: templateId || null
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
    outputDir?: string,
    options?: {
      mcap_decoders?: string[] | null;
      rrd_optimize_profile?: string;
      artifact_validation?: string;
      catalog_registration?: Record<string, unknown> | null;
    }
  ) =>
    request<Job>("/api/recordings/build", {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId,
        source_id: sourceId,
        mapping_id: mappingId,
        template_id: templateId,
        output_name: outputName,
        output_dir: outputDir || null,
        mcap_decoders: options?.mcap_decoders ?? null,
        rrd_optimize_profile: options?.rrd_optimize_profile ?? "none",
        artifact_validation: options?.artifact_validation ?? "basic",
        catalog_registration: options?.catalog_registration ?? null
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
  jobs: (projectId: string, options: JobListOptions = {}) =>
    request<Job[]>(`/api/projects/${projectId}/jobs${jobListQuery(options)}`),
  job: (jobId: string) => request<Job>(`/api/jobs/${jobId}`),
  jobSettings: () => request<JobSettings>("/api/jobs/settings"),
  updateJobSettings: (maxWorkers: number) =>
    request<JobSettings>("/api/jobs/settings", {
      method: "PATCH",
      body: JSON.stringify({ max_workers: maxWorkers })
    }),
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
  customQuery: (
    projectId: string,
    recordingIds: string[],
    semanticTypes: string[],
    filters: CustomQueryFilters,
    limit = 1000
  ) =>
    request<QueryResult>(`/api/projects/${projectId}/query/custom`, {
      method: "POST",
      body: JSON.stringify({
        recording_ids: recordingIds.length ? recordingIds : null,
        semantic_types: semanticTypes.length ? semanticTypes : null,
        filters,
        limit
      })
    }),
  diagnostics: (
    projectId: string,
    recordingIds: string[],
    thresholds: DiagnosticThresholds,
    preset = "balanced",
    limit = 1000
  ) =>
    request<DiagnosticReport>(`/api/projects/${projectId}/diagnostics`, {
      method: "POST",
      body: JSON.stringify({
        recording_ids: recordingIds.length ? recordingIds : null,
        thresholds,
        preset,
        limit
      })
    }),
  diagnosticPresets: (projectId: string) =>
    request<DiagnosticPreset[]>(`/api/projects/${projectId}/diagnostics/presets`),
  diagnosticExports: (projectId: string) =>
    request<DiagnosticExport[]>(`/api/projects/${projectId}/diagnostics/exports`),
  exportDiagnostics: (
    projectId: string,
    recordingIds: string[],
    thresholds: DiagnosticThresholds,
    preset = "balanced",
    format = "json",
    limit = 1000
  ) =>
    request<DiagnosticExportResult>(`/api/projects/${projectId}/diagnostics/export`, {
      method: "POST",
      body: JSON.stringify({
        recording_ids: recordingIds.length ? recordingIds : null,
        thresholds,
        preset,
        format,
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
  recipes: () => request<Recipe[]>("/api/recipes"),
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
  batches: (projectId: string) =>
    request<BatchSummary[]>(`/api/projects/${projectId}/batches`),
  batch: (batchId: string) => request<BatchResult>(`/api/batch/${batchId}`),
  estimateBatchImport: (
    projectId: string,
    patterns: string[],
    storageMode: "copy" | "reference" = "copy"
  ) =>
    request<DiskEstimate>(`/api/projects/${projectId}/estimates/batch-import`, {
      method: "POST",
      body: JSON.stringify({ patterns, storage_mode: storageMode })
    }),
  retryBatchItem: (batchId: string, itemId: string) =>
    request<Job>(`/api/batch/${batchId}/items/${itemId}/retry`, {
      method: "POST"
    }),
  cancelBatchItem: (batchId: string, itemId: string) =>
    request<BatchResult>(`/api/batch/${batchId}/items/${itemId}/cancel`, {
      method: "POST"
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
