import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RecordingsQueriesSection } from "./RecordingsQueriesSection";
import { createTranslator } from "./i18n";
import type { Recording } from "./types";

afterEach(() => cleanup());

const t = createTranslator("en");

describe("RecordingsQueriesSection", () => {
  it("shows persisted Rerun artifact metadata in the recording list", () => {
    const recording = makeRecording();

    render(
      <RecordingsQueriesSection
        recordings={[recording]}
        visibleRecordings={[recording]}
        tagInput=""
        queryTemplates={[]}
        selectedQueryTemplate="low_battery"
        selectedQueryRecording=""
        queryRecordingOptions={[recording]}
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
      />
    );

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

    render(
      <RecordingsQueriesSection
        recordings={[recording]}
        visibleRecordings={[recording]}
        tagInput=""
        queryTemplates={[]}
        selectedQueryTemplate="low_battery"
        selectedQueryRecording=""
        queryRecordingOptions={[recording]}
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
      />
    );

    expect(screen.getByText("Artifact Missing")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open in Rerun" })).toBeDisabled();
  });
});

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
