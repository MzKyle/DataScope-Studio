import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DiagnosticsSection } from "./DiagnosticsSection";
import { createTranslator } from "./i18n";
import type { DiagnosticReport, Recording } from "./types";

const t = createTranslator("en");

afterEach(() => cleanup());

describe("DiagnosticsSection", () => {
  it("renders the empty state when no report is available", () => {
    render(
      <DiagnosticsSection
        selectedProjectId="project"
        recordings={[]}
        report={null}
        isBusy={false}
        errors={{}}
        t={t}
        onRun={vi.fn()}
      />
    );

    expect(screen.getByText("Run Diagnostics")).toBeInTheDocument();
    expect(screen.getByText(/Run diagnostics to see health score/)).toBeInTheDocument();
  });

  it("renders summary checks and findings", () => {
    render(
      <DiagnosticsSection
        selectedProjectId="project"
        recordings={[recording]}
        report={report}
        isBusy={false}
        errors={{}}
        t={t}
        onRun={vi.fn()}
      />
    );

    expect(screen.getByText("76")).toBeInTheDocument();
    expect(screen.getByText("Topic Coverage")).toBeInTheDocument();
    expect(screen.getByText("TF transform topic is missing.")).toBeInTheDocument();
  });

  it("passes selected recordings and thresholds to onRun", () => {
    const onRun = vi.fn();
    render(
      <DiagnosticsSection
        selectedProjectId="project"
        recordings={[recording]}
        report={null}
        isBusy={false}
        errors={{}}
        t={t}
        onRun={onRun}
      />
    );

    fireEvent.click(screen.getAllByLabelText(/Robot Run/)[0]);
    fireEvent.click(screen.getByRole("button", { name: "Run Diagnostics" }));

    expect(onRun).toHaveBeenCalledWith(
      ["recording_1"],
      {
        battery_low: 0.2,
        detection_confidence: 0.5,
        time_sync_warn_s: 0.1,
        time_sync_critical_s: 1.0
      },
      "balanced"
    );
  });

  it("applies presets and persists diagnostic exports", () => {
    const onRun = vi.fn();
    const onExport = vi.fn();
    render(
      <DiagnosticsSection
        selectedProjectId="project"
        recordings={[recording]}
        report={report}
        presets={[
          {
            id: "balanced",
            name: "Balanced",
            description: "",
            thresholds: {
              battery_low: 0.2,
              detection_confidence: 0.5,
              time_sync_warn_s: 0.1,
              time_sync_critical_s: 1
            }
          },
          {
            id: "strict",
            name: "Strict",
            description: "",
            thresholds: {
              battery_low: 0.3,
              detection_confidence: 0.8,
              time_sync_warn_s: 0.05,
              time_sync_critical_s: 0.5
            }
          }
        ]}
        isBusy={false}
        errors={{}}
        t={t}
        onRun={onRun}
        onExport={onExport}
      />
    );

    fireEvent.change(screen.getByLabelText("Diagnostics Preset"), {
      target: { value: "strict" }
    });
    fireEvent.change(screen.getByLabelText("Export format"), {
      target: { value: "html" }
    });
    fireEvent.click(screen.getByRole("button", { name: "Run Diagnostics" }));
    fireEvent.click(screen.getByRole("button", { name: "Persist Export" }));

    expect(onRun).toHaveBeenCalledWith(
      [],
      {
        battery_low: 0.3,
        detection_confidence: 0.8,
        time_sync_warn_s: 0.05,
        time_sync_critical_s: 0.5
      },
      "strict"
    );
    expect(onExport).toHaveBeenCalledWith(
      [],
      {
        battery_low: 0.3,
        detection_confidence: 0.8,
        time_sync_warn_s: 0.05,
        time_sync_critical_s: 0.5
      },
      "strict",
      "html"
    );
  });

  it("filters findings and expands evidence", () => {
    render(
      <DiagnosticsSection
        selectedProjectId="project"
        recordings={[recording]}
        report={report}
        isBusy={false}
        errors={{}}
        t={t}
        onRun={vi.fn()}
      />
    );

    fireEvent.change(screen.getByLabelText("Search recording/source/topic"), {
      target: { value: "/tf" }
    });
    expect(screen.getByText("TF transform topic is missing.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Evidence" }));
    expect(screen.getByText(/expected/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Search recording/source/topic"), {
      target: { value: "camera" }
    });
    expect(screen.queryByText("TF transform topic is missing.")).not.toBeInTheDocument();
  });
});

const recording: Recording = {
  id: "recording_1",
  project_id: "project",
  source_id: "source_1",
  app_id: "datascope.robotics_debug.v1",
  path: "/tmp/run.rrd",
  run_name: "Robot Run",
  tags: [],
  params: {},
  created_at: "2026-06-16T00:00:00Z"
};

const report: DiagnosticReport = {
  project_id: "project",
  thresholds: {
    battery_low: 0.2,
    detection_confidence: 0.5,
    time_sync_warn_s: 0.1,
    time_sync_critical_s: 1
  },
  summary: {
    health_score: 76,
    severity: "warning",
    recording_count: 1,
    source_count: 1,
    topic_count: 3,
    finding_count: 1
  },
  checks: [
    {
      id: "topic_coverage",
      name: "Topic Coverage",
      status: "warn",
      severity: "warning",
      score: 90,
      evidence: {},
      recommendation: "Record /tf."
    }
  ],
  findings: [
    {
      id: "diag_0001",
      category: "topic_coverage",
      severity: "warning",
      recording_id: "recording_1",
      source_id: "source_1",
      topic: "/tf",
      entity_path: "/topics/tf",
      key: "topic_summary",
      message: "TF transform topic is missing.",
      evidence: { expected: "/tf" },
      recommendation: "Record /tf."
    }
  ]
};
