import { invoke } from "@tauri-apps/api/core";

import type {
  BuildResult,
  BatchResult,
  Job,
  MappingPayload,
  Plugin,
  Project,
  ProjectExportResult,
  ProjectImportResult,
  QueryExportResult,
  QueryResult,
  QueryTemplate,
  Recording,
  Source,
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
};

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
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (isTauriRuntime()) {
    const body = typeof init?.body === "string" ? init.body : undefined;
    const result = await invoke<ApiCommandResponse>("api_request", {
      request: {
        method: init?.method ?? "GET",
        path,
        body
      }
    });
    const parsedBody = parseBody(result.body);
    if (result.status < 200 || result.status >= 300) {
      const message =
        parsedBody?.error?.message ?? parsedBody?.detail?.error?.message ?? `HTTP ${result.status}`;
      throw new Error(message);
    }
    return parsedBody as T;
  }
  const response = await fetchWithRetry(`${API_BASE}${path}`, {
    headers,
    ...init
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = body?.error?.message ?? body?.detail?.error?.message ?? response.statusText;
    throw new Error(message);
  }
  return body as T;
}

function isTauriRuntime() {
  return Boolean((window as TauriInternalsWindow).__TAURI_INTERNALS__);
}

function parseBody(body: string) {
  if (!body) return {};
  return JSON.parse(body);
}

export const api = {
  status: () => invoke<ApiStatus>("api_status"),
  projects: () => request<Project[]>("/api/projects"),
  createProject: (name: string) =>
    request<Project>("/api/projects", {
      method: "POST",
      body: JSON.stringify({ name })
    }),
  addSource: (projectId: string, path: string) =>
    request<Source>(`/api/projects/${projectId}/sources`, {
      method: "POST",
      body: JSON.stringify({ path })
    }),
  inspect: (sourceId: string) =>
    request<{ source: Source; streams: StreamInfo[] }>(`/api/sources/${sourceId}/inspect`, {
      method: "POST"
    }),
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
  saveMapping: (sourceId: string, mapping: MappingPayload["mapping"]) =>
    request<{ id: string; path: string }>(`/api/sources/${sourceId}/mapping`, {
      method: "POST",
      body: JSON.stringify({ mapping })
    }),
  build: (
    projectId: string,
    sourceId: string,
    mappingId: string,
    outputName: string,
    templateId: string
  ) =>
    request<BuildResult>("/api/recordings/build", {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId,
        source_id: sourceId,
        mapping_id: mappingId,
        template_id: templateId,
        output_name: outputName
      })
    }),
  open: (recordingPath: string, blueprintPath?: string) =>
    request<{ status: string; pid: number }>("/api/viewer/open", {
      method: "POST",
      body: JSON.stringify({ recording_path: recordingPath, blueprint_path: blueprintPath })
    }),
  recordings: (projectId: string) => request<Recording[]>(`/api/projects/${projectId}/recordings`),
  jobs: (projectId: string) => request<Job[]>(`/api/projects/${projectId}/jobs`),
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
  batchImport: (projectId: string, patterns: string[], templateId: string, outputPrefix: string) =>
    request<BatchResult>("/api/batch/import", {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId,
        patterns,
        template_id: templateId,
        output_prefix: outputPrefix
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
  importProjectPackage: (path: string) =>
    request<ProjectImportResult>("/api/projects/import", {
      method: "POST",
      body: JSON.stringify({ path })
    })
};
