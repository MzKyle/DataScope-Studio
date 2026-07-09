import React, { StrictMode } from "react";
import { act, cleanup, render } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createAppQueryClient } from "../../app/query-client";
import { useUiStore } from "../../stores/ui-store";
import { StudioWorkspace } from "./StudioWorkspace";
import { api } from "../../api";
import type { Project } from "../../types";

const apiMocks = vi.hoisted(() => ({
  projects: vi.fn(),
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
    apiMocks.projects.mockResolvedValue([project]);
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
});

async function flushEffects() {
  for (let index = 0; index < 10; index += 1) {
    await act(async () => {
      await Promise.resolve();
    });
  }
}
