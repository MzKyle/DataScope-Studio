import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { BuildJobStatus, buildStageLabel } from "./BuildJobStatus";
import { createTranslator } from "./i18n";
import type { Job } from "./types";

afterEach(() => cleanup());

const t = createTranslator("en");

describe("BuildJobStatus", () => {
  it("shows immediate feedback while the task is being submitted", () => {
    render(<BuildJobStatus job={null} isSubmitting t={t} />);

    expect(screen.getByRole("status")).toHaveTextContent("Creating task");
    expect(screen.getByRole("status")).toHaveTextContent("Submitting the generation task");
  });

  it("shows the current stage, progress, and task id for a running job", () => {
    render(
      <BuildJobStatus
        job={makeJob({
          status: "running",
          progress: 0.35,
          stage: "converting"
        })}
        isSubmitting={false}
        t={t}
      />
    );

    expect(screen.getByRole("status")).toHaveTextContent("Building 35%");
    expect(screen.getByRole("status")).toHaveTextContent("Converting data");
    expect(screen.getByRole("status")).toHaveTextContent("job_build");
    expect(screen.getByRole("progressbar")).toHaveAttribute("value", "0.35");
  });

  it("shows terminal success and failure feedback", () => {
    const { rerender } = render(
      <BuildJobStatus
        job={makeJob({ status: "succeeded", progress: 1, stage: "completed" })}
        isSubmitting={false}
        t={t}
      />
    );
    expect(screen.getByRole("status")).toHaveTextContent("Build complete");

    rerender(
      <BuildJobStatus
        job={makeJob({
          status: "failed",
          progress: 1,
          stage: "failed",
          error: { code: "conversion_failed", message: "Invalid point cloud" }
        })}
        isSubmitting={false}
        t={t}
      />
    );
    expect(screen.getByRole("status")).toHaveTextContent("Build failed");
    expect(screen.getByRole("status")).toHaveTextContent("Invalid point cloud");
  });

  it("localizes known stages and preserves unknown adapter stages", () => {
    expect(buildStageLabel("blueprint", t)).toBe("Generating Blueprint");
    expect(buildStageLabel("custom_adapter_stage", t)).toBe("custom_adapter_stage");
    expect(buildStageLabel("converting", createTranslator("zh"))).toBe("正在转换数据");
  });
});

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
