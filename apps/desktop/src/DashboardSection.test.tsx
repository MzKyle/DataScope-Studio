import type { ComponentProps } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DashboardSection } from "./DashboardSection";
import { createTranslator } from "./i18n";
import type { Project, Recording } from "./types";

afterEach(() => cleanup());

const t = createTranslator("en");

describe("Quick Inspect entry", () => {
  it("offers data selection without requiring or exposing project setup", () => {
    renderSection();
    expect(screen.getAllByRole("button", { name: "Choose File" }).length).toBeGreaterThan(0);
    expect(screen.getByText("Drop a file or folder here")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Import into Project" })).not.toBeInTheDocument();
  });
  it("enables inspection for a path even when another project exists", () => {
    renderSection({ selectedProject: project, sourcePath: "/tmp/run.csv", latestRecording: recording, recordings: [recording] });
    expect(screen.getAllByRole("button", { name: "Inspect" })[0]).toBeEnabled();
    expect(screen.queryByText("Current Project: Robot Run")).not.toBeInTheDocument();
    expect(screen.queryByText("Recent Runs")).not.toBeInTheDocument();
  });
});

function renderSection(overrides: Partial<ComponentProps<typeof DashboardSection>> = {}) {
  return render(<DashboardSection {...baseProps(overrides)} />);
}

function baseProps(
  overrides: Partial<ComponentProps<typeof DashboardSection>> = {}
): ComponentProps<typeof DashboardSection> {
  return {
    selectedProject: null,
    latestRecording: null,
    latestJob: null,
    recordings: [],
    streamCount: 0,
    jobCount: 0,
    sourcePickerOpen: false,
    dragActive: false,
    sourcePath: "",
    sourceStorageMode: "copy",
    csvHeaderMode: "auto",
    csvColumnNames: "",
    isBusy: false,
    isLatestRecordingOpening: false,
    openingRecordingIds: new Set(),
    importError: undefined,
    dashboardError: undefined,
    projectExport: null,
    openedPackagePath: "",
    buildResult: null,
    diagnosticReport: null,
    language: "en",
    t,
    onToggleSourcePicker: vi.fn(),
    onChooseSource: vi.fn(),
    onImport: vi.fn(),
    onDragOver: vi.fn(),
    onDragLeave: vi.fn(),
    onDrop: vi.fn(),
    onSourcePathChange: vi.fn(),
    onStorageModeChange: vi.fn(),
    onCsvHeaderModeChange: vi.fn(),
    onCsvColumnNamesChange: vi.fn(),
    onProjectImport: vi.fn(),
    onRefresh: vi.fn(),
    onExportProject: vi.fn(),
    onOpenPackage: vi.fn(),
    onOpenLatest: vi.fn(),
    onOpenRecording: vi.fn(),
    ...overrides
  };
}

const project: Project = {
  id: "project",
  name: "Robot Run",
  description: "",
  workspace_path: "/tmp/datascope/project",
  created_at: "2026-06-23T00:00:00Z",
  updated_at: "2026-06-23T00:00:00Z"
};

const recording: Recording = {
  id: "recording_1",
  project_id: "project",
  source_id: "source_1",
  source_type: "csv",
  source_uri: "/tmp/source.csv",
  app_id: "datascope.sensor_monitor.v1",
  path: "/tmp/run.rrd",
  blueprint_id: "sensor_monitor",
  blueprint_path: "/tmp/run.rbl",
  run_name: "run",
  tags: [],
  params: {},
  created_at: "2026-06-23T00:00:00Z"
};
