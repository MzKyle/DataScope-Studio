import { createRef, type ComponentProps } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ImportWorkflowSection } from "./ImportWorkflowSection";
import { createTranslator } from "./i18n";
import type { Job } from "./types";

afterEach(() => cleanup());

const t = createTranslator("en");

describe("ImportWorkflowSection build feedback", () => {
  it("locks only build controls and shows progress while a build job is active", () => {
    renderSection({
      buildJob: makeJob({
        status: "running",
        progress: 0.35,
        stage: "converting"
      })
    });

    expect(screen.getByDisplayValue("run_001")).toBeDisabled();
    expect(screen.getByLabelText("Rerun artifact folder")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Building 35%" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Choose Artifact Folder" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Converting data");
  });

  it("shows immediate submitting feedback before the job is returned", () => {
    renderSection({ isBuildSubmitting: true });

    expect(screen.getByRole("button", { name: "Creating task…" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Submitting the generation task");
  });

  it("unlocks build controls after failure so the user can build again", () => {
    renderSection({
      buildJob: makeJob({
        status: "failed",
        progress: 1,
        stage: "failed",
        error: { code: "conversion_failed", message: "Conversion failed" }
      })
    });

    expect(screen.getByDisplayValue("run_001")).toBeEnabled();
    expect(screen.getByLabelText("Rerun artifact folder")).toBeEnabled();
    expect(screen.getByRole("button", { name: "Build .rrd + .rbl" })).toBeEnabled();
    expect(screen.getByRole("status")).toHaveTextContent("Conversion failed");
  });

  it("enables opening Rerun after a successful build", () => {
    renderSection({
      buildJob: makeJob({
        status: "succeeded",
        progress: 1,
        stage: "completed"
      }),
      buildResult: {
        job_id: "job_build",
        status: "succeeded",
        recording_id: "recording_1",
        recording_path: "/tmp/run_001.rrd",
        blueprint_path: "/tmp/run_001.rbl",
        artifact_info: {
          recording_size_bytes: 2048,
          blueprint_size_bytes: 512,
          app_id: "datascope.sensor_monitor.v1",
          template_id: "sensor_monitor",
          rerun_recording_id: "run_001",
          source_type: "csv",
          converter: "rerun_python_sdk",
          rerun_version: "0.32.0"
        }
      }
    });

    expect(screen.getByRole("button", { name: "Open in Rerun" })).toBeEnabled();
    expect(screen.getByText("/tmp/run_001.rrd")).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getByText("2.0 KiB / 512 B")).toBeInTheDocument();
    expect(screen.getByText("rerun_python_sdk")).toBeInTheDocument();
  });
});

function renderSection(
  overrides: Partial<ComponentProps<typeof ImportWorkflowSection>> = {}
) {
  const props: ComponentProps<typeof ImportWorkflowSection> = {
    selectedTemplateId: "",
    templateOptions: [],
    selectedMappingTemplateId: "",
    mappingTemplates: [],
    mappingTemplateName: "",
    source: null,
    streams: [],
    mapping: null,
    schemaProfile: null,
    mappingValidation: null,
    mappingConfirmed: true,
    savedMappingId: "",
    mappingDiff: null,
    projectSources: [],
    diffLeftSourceId: "",
    diffRightSourceId: "",
    supportedSemanticTypes: [],
    timeUnits: [],
    outputNameRef: createRef<HTMLInputElement>(),
    outputName: "run_001",
    artifactOutputDir: "/tmp/rerun",
    buildResult: null,
    buildJob: null,
    isBuildSubmitting: false,
    previewText: "",
    isBusy: false,
    language: "en",
    errors: {},
    t,
    onTemplateChange: vi.fn(),
    onSelectedMappingTemplateChange: vi.fn(),
    onApplyMappingTemplate: vi.fn(),
    onMappingTemplateNameChange: vi.fn(),
    onCreateMappingTemplate: vi.fn(),
    onUpdateTimeline: vi.fn(),
    onUpdateMappingStream: vi.fn(),
    onApplyMappingSuggestion: vi.fn(async () => undefined),
    onSaveMapping: vi.fn(),
    onValidateMapping: vi.fn(),
    onConfirmMapping: vi.fn(),
    onDiffLeftSourceChange: vi.fn(),
    onDiffRightSourceChange: vi.fn(),
    onRunMappingDiff: vi.fn(),
    onOutputNameChange: vi.fn(),
    onArtifactOutputDirChange: vi.fn(),
    onChooseArtifactOutputFolder: vi.fn(),
    onBuildRecording: vi.fn(),
    onOpenInRerun: vi.fn(),
    ...overrides
  };
  return render(<ImportWorkflowSection {...props} />);
}

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: "job_build",
    project_id: "project",
    type: "conversion",
    status: "pending",
    progress: 0,
    stage: "queued",
    payload: {},
    result: null,
    attempt: 1,
    created_at: "2026-06-23T00:00:00Z",
    updated_at: "2026-06-23T00:00:00Z",
    ...overrides
  };
}
