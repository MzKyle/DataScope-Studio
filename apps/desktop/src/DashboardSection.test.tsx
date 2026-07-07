import type { ComponentProps } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DashboardSection } from "./DashboardSection";
import { createTranslator } from "./i18n";
import type { Project, Recording } from "./types";

afterEach(() => cleanup());

const t = createTranslator("en");

describe("DashboardSection", () => {
  it("guides the user to create or select a project when none is active", () => {
    renderSection();

    expect(screen.getByText("Select or create a project")).toBeInTheDocument();
    expect(screen.getByText("Create or select a project")).toBeInTheDocument();
    screen
      .getAllByRole("button", { name: "Open in Rerun" })
      .forEach((button) => expect(button).toBeDisabled());
  });

  it("enables import actions when a source path is ready", () => {
    renderSection({
      selectedProject: project,
      sourcePath: "/tmp/run.csv"
    });

    expect(screen.getByText("Import a data source")).toBeInTheDocument();
    expect(
      screen
        .getAllByRole("button", { name: "Import & Auto Map" })
        .some((button) => !button.hasAttribute("disabled"))
    ).toBe(true);
  });

  it("enables Rerun actions when a latest recording exists", () => {
    renderSection({
      selectedProject: project,
      latestRecording: recording,
      recordings: [recording]
    });

    expect(screen.getByText("Review the latest recording")).toBeInTheDocument();
    expect(
      screen
        .getAllByRole("button", { name: "Open in Rerun" })
        .some((button) => !button.hasAttribute("disabled"))
    ).toBe(true);
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
