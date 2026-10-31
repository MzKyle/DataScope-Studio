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
  NextAction,
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
  isLatestRecordingOpening: boolean;
  openingRecordingIds: Set<string>;
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
  onProjectImport: () => void;
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
  const nextAction = props.t("nextQuickInspect");

  return (
    <section className="dashboard" id="dashboard">
      <div className="card quick-inspect-intro">
        <span className="eyebrow">{props.t("quickInspectEyebrow")}</span>
        <h2>{props.t("quickInspectHeroTitle")}</h2>
        <p>{props.t("quickInspectHeroSubtitle")}</p>
      </div>

      <section className="card import-card">
        <CardHeader
          icon={<Upload size={18} />}
          title={props.t("quickInspectDropTitle")}
          subtitle={props.t("quickInspectDropSubtitle")}
        />
        <div className="source-picker-toolbar responsive-actions">
          <button
            className="button-primary"
            disabled={props.isBusy}
            onClick={() => props.onChooseSource("file")}
            type="button"
          >
            <FileSearch size={16} />
            {props.t("chooseFile")}
          </button>
          <button disabled={props.isBusy} onClick={() => props.onChooseSource("folder")} type="button">
            <FolderOpen size={16} />
            {props.t("chooseFolder")}
          </button>
          <button disabled={props.isBusy || !props.sourcePath.trim()} onClick={props.onImport} type="button">
            <FileSearch size={16} />
            {props.t("quickInspectStart")}
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

    </section>
  );
}
