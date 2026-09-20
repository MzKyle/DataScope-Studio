import React, { StrictMode } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createAppQueryClient } from "../../app/query-client";
import { useImportDraftStore } from "../../stores/import-draft-store";
import { useUiStore } from "../../stores/ui-store";
import { StudioWorkspace } from "./StudioWorkspace";
import { api } from "../../api";
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
  recipes: vi.fn()
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
    useUiStore.setState({ activeSection: "recordings", busy: "", sourcePickerOpen: false });
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
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
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
    useUiStore.setState({ activeSection: "dashboard", busy: "", sourcePickerOpen: false });
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
    expect(screen.getByText("Quick Inspect")).toBeInTheDocument();
    expect(screen.queryByText("Quick Inspect Project")).not.toBeInTheDocument();
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
