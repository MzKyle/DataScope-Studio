import type { ComponentProps } from "react";
import type { AppSidebar } from "../../AppNavigation";
import { InlineError } from "../../app-support";
import type { TranslationKey } from "../../i18n";
import type { Recording } from "../../types";
import { Tabs, TabsList, TabsTrigger } from "../../ui/tabs";

export type ProjectView = "records" | "import" | "detail" | "checks" | "batch" | "compare" | "jobs";
export type RecordingTab = "overview" | "checks" | "filter";

type Props = ComponentProps<typeof AppSidebar> & {
  view: ProjectView;
  onView: (view: ProjectView) => void;
  onImport: () => void;
  onExport: () => void;
  onOpenPackage: () => void;
  packagePath: string;
  exportPath: string;
};

export function ProjectWorkspace(props: Props) {
  const t = props.t;
  return <section className="card project-workspace">
    <h2>{t("projects")}</h2>
    <div className="inline-actions">
      <label>{t("currentProject")}
        <select aria-label={t("currentProject")} value={props.selectedProjectId}
          onChange={(event) => props.onSelectedProjectChange(event.target.value)}>
          <option value="">{t("selectProject")}</option>
          {props.projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
        </select>
      </label>
      <input aria-label={t("createProject")} value={props.projectName}
        onChange={(event) => props.onProjectNameChange(event.target.value)} />
      <button disabled={Boolean(props.busy) || !props.projectName.trim()} onClick={props.onCreateProject}>{t("createProject")}</button>
      <button disabled={Boolean(props.busy)} onClick={props.onOpenPackage}>{t("openProjectPackage")}</button>
    </div>
    <InlineError error={props.projectError} t={t} />
    {props.selectedProject && <>
      <p className="path-line">{props.selectedProject.workspace_path}</p>
      <div className="inline-actions" role="group" aria-label={t("projectTools")}>
        <button onClick={() => props.onView("records")}>{t("tabRecordings")}</button>
        <button onClick={props.onImport}>{t("importData")}</button>
        <button onClick={() => props.onView("batch")}>{t("batchImport")}</button>
        <button onClick={() => props.onView("jobs")}>{t("jobs")} ({props.jobCount})</button>
        <button disabled={Boolean(props.busy)} onClick={props.onExport}>{t("exportProject")}</button>
      </div>
      <details className="advanced-panel">
        <summary>{t("advancedProjectTools")}</summary>
        <div className="inline-actions">
          <button onClick={() => props.onView("compare")}>{t("runCompare")}</button>
          <button onClick={() => props.onView("checks")}>{t("projectChecks")}</button>
        </div>
      </details>
    </>}
    {props.packagePath && <p className="path-line">{t("importedPackage")}: {props.packagePath}</p>}
    {props.exportPath && <p className="path-line">{t("exported")}: {props.exportPath}</p>}
  </section>;
}

export function RecordingDetails({ recording, tab, onTab, t }: {
  recording: Recording;
  tab: RecordingTab;
  onTab: (tab: RecordingTab) => void;
  t: (key: TranslationKey) => string;
}) {
  const tabs: [RecordingTab, TranslationKey][] = [["overview", "recordOverview"], ["checks", "recordChecks"], ["filter", "recordFilter"]];
  return <section className="card">
    <h2>{recording.run_name}</h2>
    <Tabs value={tab} onValueChange={(value) => onTab(value as RecordingTab)} aria-label={t("recordDetails")}>
      <TabsList>{tabs.map(([value, label]) => <TabsTrigger key={value} value={value} onClick={() => onTab(value)}>{t(label)}</TabsTrigger>)}</TabsList>
    </Tabs>
    {tab === "overview" && <dl className="artifact-details">
      <dt>{t("source")}</dt><dd>{recording.source_type ?? t("unknown")}</dd>
      <dt>{t("artifactStatus")}</dt><dd>{recording.artifact_status?.status ?? t("ready")}</dd>
      <dt>{t("recording")}</dt><dd className="path-line">{recording.path}</dd>
      <dt>{t("blueprint")}</dt><dd className="path-line">{recording.blueprint_path}</dd>
      <dt>{t("tags")}</dt><dd>{recording.tags.join(", ") || "—"}</dd>
    </dl>}
  </section>;
}
