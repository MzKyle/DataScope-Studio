import {
  Activity,
  Database,
  FolderPlus,
  Image,
  LayoutDashboard,
  ListChecks,
  RefreshCcw,
  Settings,
  Upload,
  type LucideIcon
} from "lucide-react";

import type { ApiError } from "./api";
import type { TranslationKey } from "./i18n";
import type { SectionId } from "./stores/ui-store";
import type { Project } from "./types";
import { InlineError, NavButton } from "./app-support";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";

type Translate = (key: TranslationKey) => string;

const navigationItems: {
  badge?: "recordingCount" | "templateCount";
  icon: LucideIcon;
  id: SectionId;
  labelKey: TranslationKey;
}[] = [
  { id: "dashboard", icon: LayoutDashboard, labelKey: "dashboard" },
  { id: "import", icon: Upload, labelKey: "import" },
  { id: "recordings", icon: ListChecks, labelKey: "recordings", badge: "recordingCount" },
  { id: "diagnostics", icon: Activity, labelKey: "diagnostics" },
  { id: "templates", icon: Image, labelKey: "templates", badge: "templateCount" },
  { id: "settings", icon: Settings, labelKey: "settings" }
];

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
  const currentSection =
    navigationItems.find((item) => item.id === props.activeSection)?.labelKey ?? "dashboard";

  return (
    <header className="topbar">
      <div className="brand-mark" aria-hidden="true"><Database size={20} /></div>
      <div className="topbar-title">
        <h1>DataScope Studio</h1>
        <span>{props.t("localCatalog")}</span>
      </div>
      <div className="topbar-context" title={props.selectedProject?.workspace_path}>
        <span>{props.t(currentSection)}</span>
        <strong>{props.selectedProject?.name ?? props.t("selectProject")}</strong>
      </div>
      <div className="topbar-spacer" />
      <Badge className="topbar-online" tone="success">{props.t("online")}</Badge>
      {props.busy && <span className="busy-indicator">{props.busy}</span>}
      <Button
        aria-label={props.t("refreshWorkspace")}
        className="icon-button"
        onClick={props.onRefreshAll}
        size="icon"
        title={props.t("refreshWorkspace")}
        variant="secondary"
      >
        <RefreshCcw size={16} />
      </Button>
      <Button
        aria-label={props.t("settings")}
        className="icon-button"
        onClick={() => props.onSectionChange("settings")}
        size="icon"
        title={props.t("settings")}
        variant="secondary"
      >
        <Settings size={16} />
      </Button>
    </header>
  );
}

export function AppSidebar(props: AppNavigationProps) {
  return (
    <aside className="sidebar">
        <nav className="sidebar-nav" aria-label="Primary sections">
          {navigationItems.map((item) => {
            const Icon = item.icon;
            const badge = item.badge ? props[item.badge] : undefined;
            return (
              <NavButton
                active={props.activeSection === item.id}
                badge={badge}
                icon={<Icon size={17} />}
                key={item.id}
                label={props.t(item.labelKey)}
                onClick={() => props.onSectionChange(item.id)}
              />
            );
          })}
        </nav>

        <section className="sidebar-card">
          <div className="sidebar-card-title">
            <span>{props.t("workspace")}</span>
            <Button
              aria-label={props.t("busyRefreshingProjects")}
              className="mini-button"
              onClick={props.onRefreshProjects}
              size="icon"
              title={props.t("busyRefreshingProjects")}
              variant="ghost"
            >
              <RefreshCcw size={14} />
            </Button>
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
            <Button
              aria-label={props.t("createProject")}
              className="icon-button"
              onClick={props.onCreateProject}
              size="icon"
              title={props.t("createProject")}
              variant="secondary"
            >
              <FolderPlus size={16} />
            </Button>
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
