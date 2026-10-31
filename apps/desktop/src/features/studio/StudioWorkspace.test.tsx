import React, { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createAppQueryClient } from "../../app/query-client";
import { useImportDraftStore } from "../../stores/import-draft-store";
import { useUiStore } from "../../stores/ui-store";
import { StudioWorkspace } from "./StudioWorkspace";
import { api, ApiError } from "../../api";
import type { Project } from "../../types";

const apiMocks = vi.hoisted(() => ({
  projects: vi.fn(),
  createProject: vi.fn(),
  quickInspect: vi.fn(),
  recordings: vi.fn(),
  jobs: vi.fn(),
  sources: vi.fn(),
  batches: vi.fn(),
  queryTemplates: vi.fn(),
  jobSettings: vi.fn(),
  updateJobSettings: vi.fn(),
  templates: vi.fn(),
  mappingTemplates: vi.fn(),
  recipes: vi.fn(),
  query: vi.fn(),
  diagnosticPresets: vi.fn(),
  diagnosticExports: vi.fn(),
  diagnostics: vi.fn(),
  confirmQuickInspectMapping: vi.fn(),
  buildQuickInspect: vi.fn(),
  clearQuickInspect: vi.fn()
}));

vi.mock("@tauri-apps/plugin-dialog", () => ({
  open: vi.fn()
}));

vi.mock("../../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      ...apiMocks
    }
  };
});

const project: Project = {
  id: "project_1",
  name: "Robot Run",
  description: "",
  workspace_path: "/tmp/datascope/project",
  created_at: "2026-06-23T00:00:00Z",
  updated_at: "2026-06-23T00:00:00Z"
};

describe("StudioWorkspace job polling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    window.scrollTo = vi.fn();
    useUiStore.setState({ activeSection: "projects", busy: "", sourcePickerOpen: false });
    useImportDraftStore.setState({
      sourcePath: "",
      sourceStorageMode: "copy",
      csvHeaderMode: "auto",
      csvColumnNames: "",
      outputName: ""
    });
    apiMocks.projects.mockResolvedValue([project]);
    apiMocks.createProject.mockResolvedValue(project);
    apiMocks.quickInspect.mockResolvedValue(quickInspectResult());
    apiMocks.recordings.mockResolvedValue([]);
    apiMocks.jobs.mockResolvedValue([]);
    apiMocks.sources.mockResolvedValue([]);
    apiMocks.batches.mockResolvedValue([]);
    apiMocks.queryTemplates.mockResolvedValue([]);
    apiMocks.jobSettings.mockResolvedValue({ max_workers: 1 });
    apiMocks.updateJobSettings.mockResolvedValue({ max_workers: 1 });
    apiMocks.templates.mockResolvedValue([]);
    apiMocks.mappingTemplates.mockResolvedValue([]);
    apiMocks.recipes.mockResolvedValue([]);
    apiMocks.query.mockResolvedValue({ columns: [], rows: [] });
    apiMocks.diagnosticPresets.mockResolvedValue([]);
    apiMocks.diagnosticExports.mockResolvedValue([]);
    apiMocks.diagnostics.mockResolvedValue(null);
    apiMocks.confirmQuickInspectMapping.mockResolvedValue({ mapping: { id: "mapping_1" }, validation: quickInspectResult().validation });
    apiMocks.buildQuickInspect.mockResolvedValue({ job_id: "", recording_id: "recording_1", status: "succeeded", recording_path: "/quick/run.rrd", blueprint_path: "/quick/run.rbl", query_index: { storage: "none", status: "skipped" } });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("keeps one idle job poll loop under React StrictMode", async () => {
    render(
      <StrictMode>
        <QueryClientProvider client={createAppQueryClient()}>
          <StudioWorkspace />
        </QueryClientProvider>
      </StrictMode>
    );

    await flushEffects();
    expect(api.projects).toHaveBeenCalled();
    expect(api.recordings).toHaveBeenCalled();
    expect(api.jobs).toHaveBeenCalled();

    apiMocks.jobs.mockClear();
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    await flushEffects();
    expect(api.jobs).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(14_000);
    });
    await flushEffects();
    expect(api.jobs).toHaveBeenCalledTimes(1);
  });

  it("starts quick inspect from the dashboard without creating a project", async () => {
    useUiStore.setState({ activeSection: "inspect", busy: "", sourcePickerOpen: false });
    useImportDraftStore.setState({ sourcePath: "/tmp/run.csv" });
    apiMocks.projects.mockResolvedValue([]);

    render(
      <QueryClientProvider client={createAppQueryClient()}>
        <StudioWorkspace />
      </QueryClientProvider>
    );

    await flushEffects();
    fireEvent.click(screen.getAllByRole("button", { name: "Inspect" })[0]);
    await flushEffects();

    expect(api.quickInspect).toHaveBeenCalledWith(
      "/tmp/run.csv",
      "copy",
      { csv: { header_mode: "auto", column_names: [] } }
    );
    expect(api.createProject).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Quick Inspect" })).toBeInTheDocument();
    expect(screen.queryByText("Quick Inspect Project")).not.toBeInTheDocument();
  });

  it("skips the query index in desktop quick inspect and preserves its draft across navigation", async () => {
    useUiStore.setState({ activeSection: "inspect" });
    useImportDraftStore.setState({ sourcePath: "/tmp/run.csv" });
    render(<QueryClientProvider client={createAppQueryClient()}><StudioWorkspace /></QueryClientProvider>);
    await flushEffects();
    fireEvent.click(screen.getAllByRole("button", { name: "Inspect" })[0]);
    await flushEffects();
    fireEvent.click(screen.getAllByRole("button", { name: "Generate Visualization" })[0]);
    await flushEffects();
    expect(api.buildQuickInspect).toHaveBeenCalledWith("session_1", expect.any(String), "sensor_monitor", undefined,
      expect.objectContaining({ build_query_index: false }));
    fireEvent.click(screen.getByRole("button", { name: /Projects/ }));
    await flushEffects();
    fireEvent.click(screen.getByRole("button", { name: "Quick Inspect" }));
    await flushEffects();
    expect(screen.getByRole("heading", { name: "Quick Inspect" })).toBeInTheDocument();
    expect(api.quickInspect).toHaveBeenCalledTimes(1);
    expect(api.clearQuickInspect).not.toHaveBeenCalled();
  });

  it("discards a delayed query response after another recording is selected", async () => {
    const rows = ["first", "second"].map((name) => ({ id: name, project_id: project.id, source_id: `source_${name}`,
      app_id: "test", path: `/tmp/${name}.rrd`, blueprint_id: "sensor_monitor", blueprint_path: `/tmp/${name}.rbl`,
      run_name: name, tags: [], params: {}, created_at: project.created_at }));
    apiMocks.recordings.mockResolvedValue(rows);
    let resolveQuery!: (value: unknown) => void;
    apiMocks.query.mockImplementation(() => new Promise((resolve) => { resolveQuery = resolve; }));
    render(<QueryClientProvider client={createAppQueryClient()}><StudioWorkspace /></QueryClientProvider>);
    await flushEffects();
    fireEvent.click(screen.getByRole("button", { name: "first" }));
    fireEvent.click(screen.getByRole("tab", { name: "Filter" }));
    await flushEffects();
    fireEvent.click(screen.getByRole("button", { name: "Run Query" }));
    await flushEffects();
    expect(api.query).toHaveBeenCalledWith(project.id, expect.any(String), ["first"], expect.any(Object));
    fireEvent.click(screen.getByRole("button", { name: "Recordings" }));
    fireEvent.click(screen.getByRole("button", { name: "second" }));
    fireEvent.click(screen.getByRole("tab", { name: "Filter" }));
    await act(async () => { resolveQuery({ columns: ["value"], rows: [{ value: "stale-first-result" }] }); });
    await flushEffects();
    expect(screen.queryByText("stale-first-result")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "second" })).toBeInTheDocument();
  });

  it("keeps the saved project when temporary cleanup fails and treats an expired session as cleaned", async () => {
    useUiStore.setState({ activeSection: "inspect" });
    useImportDraftStore.setState({ sourcePath: "/tmp/run.csv" });
    const imported = quickInspectResult();
    imported.source.id = "source_target"; imported.source.project_id = project.id;
    imported.mapping.mapping.id = "mapping_target";
    imported.mapping.mapping.source = "source_target";
    imported.mapping.mapping.recording_id = "recording_target";
    imported.saved_mapping.id = "mapping_target";
    vi.spyOn(api, "importWorkflow").mockResolvedValue(imported);
    vi.spyOn(api, "saveMapping").mockResolvedValue(imported.saved_mapping);
    vi.spyOn(api, "previewMapping").mockResolvedValue({ ...imported, mapping: imported.mapping.mapping });
    apiMocks.clearQuickInspect.mockRejectedValueOnce(new ApiError("cleanup failed", 500, "cleanup_failed"));
    render(<QueryClientProvider client={createAppQueryClient()}><StudioWorkspace /></QueryClientProvider>);
    await flushEffects();
    fireEvent.click(screen.getAllByRole("button", { name: "Inspect" })[0]);
    await flushEffects();
    fireEvent.click(screen.getByText("Move to project", { selector: "summary" }));
    fireEvent.click(screen.getByRole("button", { name: "Move to project" }));
    await flushEffects();
    expect(screen.getByRole("heading", { name: "Projects" })).toBeInTheDocument();
    expect(screen.getByText("Saved to project; temporary cleanup failed. Retry cleanup.")).toBeInTheDocument();
    expect(api.buildQuickInspect).not.toHaveBeenCalled();
    apiMocks.clearQuickInspect.mockRejectedValueOnce(new ApiError("already expired", 404, "not_found"));
    fireEvent.click(screen.getByRole("button", { name: "Retry cleanup" }));
    await flushEffects();
    expect(screen.queryByText("Saved to project; temporary cleanup failed. Retry cleanup.")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Projects" })).toBeInTheDocument();
  });
});

async function flushEffects() {
  for (let index = 0; index < 10; index += 1) {
    await act(async () => {
      await Promise.resolve();
    });
  }
}

function quickInspectResult() {
  return {
    session_id: "session_1",
    source: {
      id: "source_1",
      project_id: "project_tmp",
      type: "csv",
      uri: "/tmp/run.csv",
      storage_mode: "copy" as const,
      checksum: "checksum",
      size_bytes: 10,
      status: "inspected",
      metadata: {}
    },
    streams: [
      {
        stream_id: "stream_1",
        name: "temperature",
        semantic_type: "scalar",
        fields: ["temperature"],
        time_key: "timestamp",
        confidence: 0.9,
        metadata: {}
      }
    ],
    template_matches: [{ template_id: "sensor_monitor", name: "Sensor Monitor", score: 1 }],
    template_id: "sensor_monitor",
    mapping: {
      mapping: {
        schema_version: 2,
        id: "mapping_1",
        source: "source_1",
        app_id: "datascope.sensor_monitor.v1",
        recording_id: "recording_1",
        template_id: "sensor_monitor",
        status: "draft" as const,
        timelines: {
          primary: {
            name: "timestamp",
            source_field: "timestamp",
            unit: "auto",
            sort: "source" as const
          }
        },
        streams: [
          {
            stream_id: "stream_1",
            source_fields: ["temperature"],
            semantic_type: "scalar",
            entity_path: "/temperature",
            archetype: "Scalar",
            view: "time_series",
            confidence: 0.9,
            enabled: true,
            required: false,
            origin: "inferred",
            rule_key: "inferred:stream_1"
          }
        ]
      }
    },
    saved_mapping: { id: "mapping_1", path: "/tmp/mapping.yaml" },
    preview: { columns: ["timestamp", "temperature"], rows: [{ timestamp: 1, temperature: 20 }] },
    schema_profile: {
      schema_version: 1,
      source_id: "source_1",
      source_type: "csv",
      source_family: "tabular",
      field_names: ["timestamp", "temperature"],
      fields: [],
      timeline: {},
      adapter_metadata: {}
    },
    validation: {
      valid: true,
      errors: [],
      warnings: [],
      issues: [],
      summary: { errors: 0, warnings: 0 },
      effective_timeline_unit: "seconds"
    }
  };
}
