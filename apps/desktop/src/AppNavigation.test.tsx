import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppSidebar, AppTopbar } from "./AppNavigation";
import { createTranslator } from "./i18n";
import type { Project } from "./types";

afterEach(() => cleanup());

const t = createTranslator("en");

describe("AppNavigation", () => {
  it("keeps primary topbar actions available with project context", () => {
    render(<AppTopbar {...baseProps()} />);

    expect(screen.getByText("DataScope Studio")).toBeInTheDocument();
    expect(screen.getByText("Robot Run")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh workspace" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Settings" })).toBeInTheDocument();
  });

  it("renders every primary navigation entry with count badges", () => {
    render(<AppSidebar {...baseProps()} />);

    expect(screen.getByRole("navigation", { name: "Primary sections" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import & Mapping" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Recordings & Query/ })).toHaveTextContent("2");
    expect(screen.getByRole("button", { name: "Diagnostics" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Recipes & Extensions/ })).toHaveTextContent("3");
    expect(screen.getByRole("button", { name: "Settings" })).toBeInTheDocument();
  });
});

function baseProps() {
  return {
    activeSection: "dashboard",
    busy: "",
    projects: [project],
    selectedProject: project,
    selectedProjectId: "project",
    projectName: "Robot Run",
    recordingCount: 2,
    jobCount: 1,
    templateCount: 3,
    t,
    onRefreshAll: vi.fn(),
    onSectionChange: vi.fn(),
    onRefreshProjects: vi.fn(),
    onSelectedProjectChange: vi.fn(),
    onProjectNameChange: vi.fn(),
    onCreateProject: vi.fn()
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
