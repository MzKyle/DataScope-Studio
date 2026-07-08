import type { DragEvent } from "react";
import {
  Activity,
  Download,
  ExternalLink,
  FileSearch,
  FolderOpen,
  Gauge,
  ListChecks,
  Upload,
  Zap
} from "lucide-react";

import type { ApiError } from "./api";
import type { Language, TranslationKey } from "./i18n";
import type {
  BuildResult,
  DiagnosticReport,
  Job,
  Project,
  ProjectExportResult,
  Recording
} from "./types";
import {
  CardHeader,
  EmptyState,
  InlineError,
  ProjectVisual,
  SummaryTile,
  StatusBadge,
  formatDateTime,
  normalizeSourcePathInput
} from "./app-support";

const SUPPORTED_FORMATS = [
  "CSV",
  "TSV/TXT",
  "JSONL",
  "Images",
  "PLY",
  "PCD",
  "XYZ/PTS",
  "NPZ",
  "MCAP",
  "ROS2 DB3"
];

type Translate = (key: TranslationKey) => string;

type DashboardSectionProps = {
  selectedProject: Project | null;
  latestRecording: Recording | null;
  latestJob: Job | null;
  recordings: Recording[];
  streamCount: number;
  jobCount: number;
  sourcePickerOpen: boolean;
  dragActive: boolean;
  sourcePath: string;
  sourceStorageMode: "copy" | "reference";
  csvHeaderMode: "auto" | "header" | "no_header";
  csvColumnNames: string;
  isBusy: boolean;
  importError?: ApiError;
  dashboardError?: ApiError;
  projectExport: ProjectExportResult | null;
  openedPackagePath: string;
  buildResult: BuildResult | null;
  diagnosticReport: DiagnosticReport | null;
  language: Language;
  t: Translate;
  onToggleSourcePicker: () => void;
  onChooseSource: (kind: "file" | "folder") => void;
  onImport: () => void;
  onDragOver: (event: DragEvent<HTMLDivElement>) => void;
  onDragLeave: (event: DragEvent<HTMLDivElement>) => void;
  onDrop: (event: DragEvent<HTMLDivElement>) => void;
  onSourcePathChange: (value: string) => void;
  onStorageModeChange: (value: "copy" | "reference") => void;
  onCsvHeaderModeChange: (value: "auto" | "header" | "no_header") => void;
  onCsvColumnNamesChange: (value: string) => void;
  onRefresh: () => void;
  onExportProject: () => void;
  onOpenPackage: () => void;
  onOpenLatest: () => void;
  onOpenRecording: (recording: Recording) => void;
};

export function DashboardSection(props: DashboardSectionProps) {
  const recentRecordings = props.recordings.slice(0, 4);
  const latestJobStatus = props.latestJob
    ? `${props.latestJob.type} / ${props.latestJob.status}`
    : props.t("localArtifacts");
  const healthLabel = props.diagnosticReport
    ? props.diagnosticReport.summary.severity
    : props.t("notRun");
  const nextAction = !props.selectedProject
    ? props.t("nextCreateProject")
    : props.recordings.length
      ? props.t("nextReviewRecording")
      : props.t("nextImportSource");

  return (
    <section className="dashboard" id="dashboard">
      <div className="hero-card project-summary-card">
        <div className="project-summary-main">
          <div>
            <span className="eyebrow">{props.t("currentProjectEyebrow")}</span>
            <h2>{props.selectedProject?.name ?? props.t("selectOrCreateProject")}</h2>
            <p>
              {props.selectedProject
                ? props.t("projectReadyDescription")
                : props.t("projectEmptyDescription")}
            </p>
          </div>
          <div className="hero-actions responsive-actions">
            <button
              className="button-primary"
              type="button"
              onClick={props.onImport}
              disabled={props.isBusy || !props.sourcePath.trim()}
            >
              <FileSearch size={16} />
              {props.t("inspectSource")}
            </button>
            <button
              type="button"
              onClick={props.onOpenLatest}
              disabled={(!props.buildResult && !props.latestRecording) || props.isBusy}
            >
              <ExternalLink size={16} />
              {props.t("openInRerun")}
            </button>
          </div>
          <div className="project-meta-list">
            <span className="project-meta-item">
              <FolderOpen size={14} />
              {props.selectedProject?.workspace_path ?? props.t("createProject")}
            </span>
            <span className="project-meta-item">
              <ListChecks size={14} />
              {props.latestRecording
                ? `${props.t("latestRun")}: ${props.latestRecording.run_name}`
                : props.t("noLatestRun")}
            </span>
            <span className="project-meta-item">
              <Activity size={14} />
              {latestJobStatus}
            </span>
          </div>
          <div className="summary-strip">
            <SummaryTile label={props.t("runs")} value={props.recordings.length} />
            <SummaryTile label={props.t("streams")} value={props.streamCount} />
            <SummaryTile label={props.t("jobs")} value={props.jobCount} />
            <SummaryTile
              label={props.t("health")}
              value={healthLabel}
              tone={props.diagnosticReport?.summary.severity === "critical" ? "danger" : "neutral"}
            />
          </div>
        </div>
        <div className="next-action-panel">
          <div>
            <span className="eyebrow">{props.t("nextStep")}</span>
            <strong>{nextAction}</strong>
            <p>{props.t("dashboardNextStepHint")}</p>
          </div>
          <ProjectVisual
            recordings={props.recordings.length}
            streams={props.streamCount}
            jobs={props.jobCount}
          />
        </div>
      </div>

      <section className="card import-card">
        <CardHeader
          icon={<Upload size={18} />}
          title={props.t("importData")}
          subtitle={props.t("importDataSubtitle")}
        />
        <div className="source-picker-toolbar responsive-actions">
          <div className="source-picker-wrap">
            <button
              className="button-primary source-picker-button"
              disabled={props.isBusy}
              onClick={props.onToggleSourcePicker}
              type="button"
            >
              <FolderOpen size={16} />
              {props.t("chooseSource")}
            </button>
            {props.sourcePickerOpen && (
              <div className="source-picker-popover" role="menu">
                <button type="button" onClick={() => props.onChooseSource("file")}>
                  <FileSearch size={16} />
                  <span>
                    <strong>{props.t("selectSourceFile")}</strong>
                    <small>{props.t("selectSourceFileHint")}</small>
                  </span>
                </button>
                <button type="button" onClick={() => props.onChooseSource("folder")}>
                  <FolderOpen size={16} />
                  <span>
                    <strong>{props.t("selectSourceFolder")}</strong>
                    <small>{props.t("selectSourceFolderHint")}</small>
                  </span>
                </button>
              </div>
            )}
          </div>
          <button disabled={props.isBusy} onClick={props.onImport} type="button">
            <FileSearch size={16} />
            {props.t("inspectSource")}
          </button>
        </div>
        <div
          className={`drop-zone compact-drop-zone ${props.dragActive ? "is-dragging" : ""}`}
          onDragOver={props.onDragOver}
          onDragLeave={props.onDragLeave}
          onDrop={props.onDrop}
        >
          <div className="drop-icon"><Upload size={22} /></div>
          <div>
            <strong>{props.t("dragSourceHere")}</strong>
            <span>{props.t("supportedSources")}</span>
          </div>
        </div>
        <div className="chip-row">
          {SUPPORTED_FORMATS.map((format) => <span className="chip" key={format}>{format}</span>)}
        </div>
        <div className="source-options">
          <input
            aria-describedby={props.importError ? "import-error" : undefined}
            aria-invalid={Boolean(props.importError)}
            placeholder={props.t("sourcePathPlaceholder")}
            value={props.sourcePath}
            onChange={(event) => props.onSourcePathChange(event.target.value)}
            onBlur={(event) =>
              props.onSourcePathChange(normalizeSourcePathInput(event.target.value))
            }
          />
          <label>
            <span>{props.t("storageMode")}</span>
            <select
              value={props.sourceStorageMode}
              onChange={(event) =>
                props.onStorageModeChange(event.target.value as "copy" | "reference")
              }
            >
              <option value="copy">{props.t("storageCopy")}</option>
              <option value="reference">{props.t("storageReference")}</option>
            </select>
          </label>
        </div>
        {props.sourcePath.trim().toLowerCase().endsWith(".csv") && (
          <div className="csv-source-options">
            <label>
              <span>{props.t("csvHeaderMode")}</span>
              <select
                value={props.csvHeaderMode}
                onChange={(event) =>
                  props.onCsvHeaderModeChange(
                    event.target.value as "auto" | "header" | "no_header"
                  )
                }
              >
                <option value="auto">{props.t("csvHeaderAuto")}</option>
                <option value="header">{props.t("csvHasHeader")}</option>
                <option value="no_header">{props.t("csvNoHeader")}</option>
              </select>
            </label>
            <label>
              <span>{props.t("csvColumnNames")}</span>
              <input
                placeholder={props.t("csvColumnNamesPlaceholder")}
                value={props.csvColumnNames}
                onChange={(event) => props.onCsvColumnNamesChange(event.target.value)}
              />
            </label>
            <span className="field-hint">{props.t("csvColumnNamesHint")}</span>
          </div>
        )}
        <InlineError id="import-error" error={props.importError} t={props.t} />
      </section>

      <section className="card quick-actions-card">
        <CardHeader
          icon={<Zap size={18} />}
          title={props.t("workspaceActions")}
          subtitle={props.t("workspaceActionsSubtitle")}
        />
        <div className="quick-actions">
          <button onClick={props.onRefresh} disabled={!props.selectedProject || props.isBusy}>
            <Activity size={16} />
            {props.t("refreshRuns")}
          </button>
          <button onClick={props.onExportProject} disabled={!props.selectedProject || props.isBusy}>
            <Download size={16} />
            {props.t("exportProject")}
          </button>
          <button onClick={props.onOpenPackage} disabled={props.isBusy}>
            <FolderOpen size={16} />
            {props.t("openProjectPackage")}
          </button>
          <button
            onClick={props.onOpenLatest}
            disabled={(!props.buildResult && !props.latestRecording) || props.isBusy}
          >
            <ExternalLink size={16} />
            {props.t("openInRerun")}
          </button>
        </div>
        <InlineError error={props.dashboardError} t={props.t} />
        {props.projectExport && (
          <p className="path-line light">{props.t("packagePath")}: {props.projectExport.path}</p>
        )}
        {props.openedPackagePath && (
          <p className="path-line light">
            {props.t("importedPackage")}: {props.openedPackagePath}
          </p>
        )}
        {props.latestJob && (
          <div className="soft-status">
            <span>{props.latestJob.type}</span>
            <StatusBadge
              tone={props.latestJob.status === "failed" ? "danger" : "neutral"}
              label={props.latestJob.status}
            />
          </div>
        )}
      </section>

      <section className="card recent-runs-card">
        <CardHeader
          icon={<ListChecks size={18} />}
          title={props.t("recentRuns")}
          subtitle={
            props.latestRecording
              ? `${props.t("latest")}: ${props.latestRecording.run_name}`
              : props.t("noRecordingsYet")
          }
        />
        {props.recordings.length ? (
          <div className="compact-list">
            {recentRecordings.map((recording) => (
              <div className="run-row" key={recording.id}>
                <div>
                  <strong>{recording.run_name}</strong>
                  <span>
                    {recording.source_type ?? props.t("unknown")} ·{" "}
                    {formatDateTime(recording.created_at, props.language)}
                  </span>
                </div>
                <div className="run-row-actions">
                  <StatusBadge
                    tone="neutral"
                    label={recording.blueprint_id ?? props.t("recording")}
                  />
                  <button
                    className="mini-button"
                    onClick={() => props.onOpenRecording(recording)}
                    disabled={props.isBusy}
                    title={props.t("openInRerun")}
                  >
                    <ExternalLink size={15} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState text={props.t("recordingsWillAppear")} />
        )}
      </section>

      {props.diagnosticReport && (
        <section className={`card health-card severity-${props.diagnosticReport.summary.severity}`}>
          <CardHeader icon={<Gauge size={18} />} title={props.t("dataHealthCard")} />
          <div className="health-card-grid">
            <div>
              <span>{props.t("healthScore")}</span>
              <strong>{props.diagnosticReport.summary.health_score}</strong>
            </div>
            <div>
              <span>{props.t("severity")}</span>
              <strong>{props.diagnosticReport.summary.severity}</strong>
            </div>
            <div>
              <span>{props.t("findings")}</span>
              <strong>{props.diagnosticReport.summary.finding_count}</strong>
            </div>
          </div>
          <p className="path-line light">
            {props.diagnosticReport.findings[0]
              ? `${props.t("topFinding")}: ${props.diagnosticReport.findings[0].message}`
              : props.t("noTopFinding")}
          </p>
        </section>
      )}
    </section>
  );
}
