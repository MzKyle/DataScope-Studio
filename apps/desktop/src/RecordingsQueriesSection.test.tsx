import type { ComponentProps } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RecordingsQueriesSection } from "./RecordingsQueriesSection";
import { createTranslator } from "./i18n";
import type { Recording } from "./types";

afterEach(() => cleanup());

const t = createTranslator("en");

describe("RecordingsQueriesSection", () => {
  it("switches between recording, query, compare, and jobs panels", () => {
    const recording = makeRecording();

    renderSection({ recordings: [recording], visibleRecordings: [recording] });

    expect(screen.getByText("Recording Browser")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Query").closest("button")!);
    expect(screen.getByText("Query Console")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run Query" })).toBeEnabled();

    fireEvent.click(screen.getByText("Compare").closest("button")!);
    expect(screen.getByText("Run Compare")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Jobs").closest("button")!);
    expect(screen.getByText("Conversion and query jobs will appear here.")).toBeInTheDocument();
  });

  it("shows persisted Rerun artifact metadata in the recording list", () => {
    const recording = makeRecording();

    renderSection({ recordings: [recording], visibleRecordings: [recording] });

    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getByText("2.0 KiB / 512 B")).toBeInTheDocument();
  });

  it("disables opening recordings with missing artifacts", () => {
    const recording = makeRecording({
      artifact_status: {
        status: "missing",
        message: "Missing artifact file: /tmp/run.rrd",
        recording_path: "/tmp/run.rrd",
        blueprint_path: "/tmp/run.rbl",
        recording_size_bytes: null,
        blueprint_size_bytes: 512
      }
    });

    renderSection({ recordings: [recording], visibleRecordings: [recording] });

    expect(screen.getByText("Artifact Missing")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open in Rerun" })).toBeDisabled();
  });

  it("keeps ready recording open actions enabled during background busy work", () => {
    const recording = makeRecording();

    renderSection({
      recordings: [recording],
      visibleRecordings: [recording],
      isBusy: true
    });

    expect(screen.getByRole("button", { name: "Open in Rerun" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Add Tag" })).toBeDisabled();
  });

  it("disables only the recording currently opening", () => {
    const opening = makeRecording({ id: "recording_opening", run_name: "opening" });
    const idle = makeRecording({ id: "recording_idle", run_name: "idle" });

    renderSection({
      recordings: [opening, idle],
      visibleRecordings: [opening, idle],
      openingRecordingIds: new Set([opening.id])
    });

    const openButtons = screen.getAllByRole("button", { name: "Open in Rerun" });
    expect(openButtons[0]).toBeDisabled();
    expect(openButtons[1]).toBeEnabled();
  });
});

function renderSection(
  overrides: Partial<ComponentProps<typeof RecordingsQueriesSection>> = {}
) {
  return render(
    <RecordingsQueriesSection
      recordings={[]}
      visibleRecordings={[]}
      tagInput=""
      queryTemplates={[]}
      selectedQueryTemplate="low_battery"
      selectedQueryRecording=""
      queryRecordingOptions={overrides.recordings ?? []}
      thresholdTemplates={new Set()}
      queryThreshold="0.2"
      customQueryEntityPath=""
      customQueryKey=""
      customQueryText=""
      customQuerySemanticTypes="scalar"
      customQueryOperator="any"
      customQueryValue=""
      customQueryTimeStart=""
      customQueryTimeEnd=""
      selectedProjectId="project"
      exportPath=""
      queryResult={null}
      compareRecordingIds=""
      compareMetric=""
      compareResult={null}
      jobs={[]}
      visibleJobs={[]}
      isBusy={false}
      openingRecordingIds={new Set()}
      language="en"
      errors={{}}
      t={t}
      onTagInputChange={vi.fn()}
      onOpenRecording={vi.fn()}
      onAddTag={vi.fn()}
      onQueryTemplateChange={vi.fn()}
      onQueryRecordingChange={vi.fn()}
      onQueryThresholdChange={vi.fn()}
      onRunQuery={vi.fn()}
      onExportQuery={vi.fn()}
      onCustomQueryEntityPathChange={vi.fn()}
      onCustomQueryKeyChange={vi.fn()}
      onCustomQueryTextChange={vi.fn()}
      onCustomQuerySemanticTypesChange={vi.fn()}
      onCustomQueryOperatorChange={vi.fn()}
      onCustomQueryValueChange={vi.fn()}
      onCustomQueryTimeStartChange={vi.fn()}
      onCustomQueryTimeEndChange={vi.fn()}
      onRunCustomQuery={vi.fn()}
      onCompareRecordingIdsChange={vi.fn()}
      onCompareMetricChange={vi.fn()}
      onRunCompare={vi.fn()}
      onCancelJob={vi.fn()}
      onRetryJob={vi.fn()}
      {...overrides}
    />
  );
}

function makeRecording(overrides: Partial<Recording> = {}): Recording {
  return {
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
    params: {
      rerun_artifact: {
        recording_size_bytes: 2048,
        blueprint_size_bytes: 512,
        app_id: "datascope.sensor_monitor.v1",
        template_id: "sensor_monitor",
        rerun_recording_id: "run",
        source_type: "csv",
        converter: "rerun_python_sdk",
        rerun_version: "0.32.0"
      }
    },
    artifact_status: {
      status: "ready",
      message: "",
      recording_path: "/tmp/run.rrd",
      blueprint_path: "/tmp/run.rbl",
      recording_size_bytes: 2048,
      blueprint_size_bytes: 512
    },
    created_at: "2026-06-23T00:00:00Z",
    ...overrides
  };
}
