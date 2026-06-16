import {
  Activity,
  Database,
  FolderPlus,
  Image,
  LayoutDashboard,
  ListChecks,
  RefreshCcw,
  Settings,
  Upload
} from "lucide-react";

import type { ApiError } from "./api";
import type { TranslationKey } from "./i18n";
import type { Project } from "./types";
import { InlineError, NavButton, StatusBadge } from "./app-support";

type Translate = (key: TranslationKey) => string;

type AppNavigationProps = {
  activeSection: string;
  busy: string;
  projects: Project[];
  selectedProject: Project | null;
  selectedProjectId: string;
  projectName: string;
  projectError?: ApiError;
  recordingCount: number;
  jobCount: number;
  templateCount: number;
  t: Translate;
  onRefreshAll: () => void;
  onSectionChange: (section: string) => void;
  onRefreshProjects: () => void;
  onSelectedProjectChange: (projectId: string) => void;
  onProjectNameChange: (name: string) => void;
  onCreateProject: () => void;
};

export function AppTopbar(props: AppNavigationProps) {
  return (
    <header className="topbar">
      <div className="brand-mark" aria-hidden="true"><Database size={20} /></div>
      <div className="topbar-title">
        <h1>DataScope Studio</h1>
        <span>{props.t("localCatalog")}</span>
      </div>
      <div className="topbar-spacer" />
      <StatusBadge tone="success" label={props.t("online")} />
      {props.busy && <span className="busy-indicator">{props.busy}</span>}
      <button
        className="icon-button"
        onClick={props.onRefreshAll}
        title={props.t("refreshWorkspace")}
      >
        <RefreshCcw size={16} />
      </button>
      <button
        className="icon-button"
        onClick={() => props.onSectionChange("settings")}
        title={props.t("settings")}
      >
        <Settings size={16} />
      </button>
    </header>
  );
}

export function AppSidebar(props: AppNavigationProps) {
  return (
    <aside className="sidebar">
        <nav className="sidebar-nav" aria-label="Primary">
          <NavButton
            active={props.activeSection === "dashboard"}
            icon={<LayoutDashboard size={17} />}
            label={props.t("dashboard")}
            onClick={() => props.onSectionChange("dashboard")}
          />
          <NavButton
            active={props.activeSection === "import"}
            icon={<Upload size={17} />}
            label={props.t("import")}
            onClick={() => props.onSectionChange("import")}
          />
          <NavButton
            active={props.activeSection === "recordings"}
            icon={<ListChecks size={17} />}
            label={props.t("recordings")}
            onClick={() => props.onSectionChange("recordings")}
          />
          <NavButton
            active={props.activeSection === "diagnostics"}
            icon={<Activity size={17} />}
            label={props.t("diagnostics")}
            onClick={() => props.onSectionChange("diagnostics")}
          />
          <NavButton
            active={props.activeSection === "templates"}
            icon={<Image size={17} />}
            label={props.t("templates")}
            onClick={() => props.onSectionChange("templates")}
          />
          <NavButton
            active={props.activeSection === "settings"}
            icon={<Settings size={17} />}
            label={props.t("settings")}
            onClick={() => props.onSectionChange("settings")}
          />
        </nav>

        <section className="sidebar-card">
          <div className="sidebar-card-title">
            <span>{props.t("workspace")}</span>
            <button
              className="mini-button"
              onClick={props.onRefreshProjects}
              title={props.t("busyRefreshingProjects")}
            >
              <RefreshCcw size={14} />
            </button>
          </div>
          <label className="field-label" htmlFor="project-select">
            {props.t("currentProject")}
          </label>
          <select
            id="project-select"
            value={props.selectedProjectId}
            onChange={(event) => props.onSelectedProjectChange(event.target.value)}
          >
            <option value="">{props.t("selectProject")}</option>
            {props.projects.map((project) => (
              <option key={project.id} value={project.id}>{project.name}</option>
            ))}
          </select>
          <div className="compact-form">
            <input
              aria-label={props.t("createProject")}
              value={props.projectName}
              onChange={(event) => props.onProjectNameChange(event.target.value)}
            />
            <button
              className="icon-button"
              onClick={props.onCreateProject}
              title={props.t("createProject")}
            >
              <FolderPlus size={16} />
            </button>
          </div>
          <InlineError error={props.projectError} t={props.t} />
          {props.selectedProject && (
            <p className="path-line">{props.selectedProject.workspace_path}</p>
          )}
        </section>

        <section className="sidebar-card subtle">
          <div className="mini-stat">
            <span>{props.t("recordings")}</span><strong>{props.recordingCount}</strong>
          </div>
          <div className="mini-stat">
            <span>{props.t("jobs")}</span><strong>{props.jobCount}</strong>
          </div>
          <div className="mini-stat">
            <span>{props.t("templates")}</span><strong>{props.templateCount}</strong>
          </div>
        </section>
    </aside>
  );
}
