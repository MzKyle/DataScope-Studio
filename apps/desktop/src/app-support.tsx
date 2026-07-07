import { memo, useState, type ReactNode } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Command,
  Copy,
  RefreshCcw,
  X
} from "lucide-react";

import { ApiError } from "./api";
import type {
  BatchResult,
  BuildResult,
  Job,
  MappingSuggestion,
  MappingValidationIssue,
  Project,
  QueryResult,
  StreamInfo
} from "./types";
import type { Language, TranslationKey } from "./i18n";

export type ErrorArea =
  | "project"
  | "import"
  | "dashboard"
  | "mappingToolbar"
  | "mapping"
  | "mappingDiff"
  | "build"
  | "recordings"
  | "query"
  | "compare"
  | "diagnostics"
  | "batch"
  | "extensions"
  | "mappingTemplates"
  | "settings";

export type GlobalNotification = {
  error: ApiError;
  retry?: () => void;
};

export type AreaErrors = Partial<Record<ErrorArea, ApiError>>;
export type ErrorPresentation = {
  title: string;
  summary: string;
  guidance: string;
  details: string;
  tone: "danger" | "warning" | "neutral";
};
export type ErrorDialogRequest = {
  error: ApiError;
  area: ErrorArea | "global";
  retry?: () => void;
  context?: Record<string, unknown>;
};
type Translate = (key: TranslationKey) => string;

const DEFAULT_EXPORT_DIR_KEY = "datascope.defaultExportDir";
const DEFAULT_ARTIFACT_DIR_KEY = "datascope.defaultArtifactDir";

export const sourceFileExtensions = new Set([
  "csv",
  "tsv",
  "txt",
  "log",
  "dat",
  "lst",
  "list",
  "jsonl",
  "json",
  "mcap",
  "db3",
  "jpg",
  "jpeg",
  "png",
  "bmp",
  "webp",
  "tif",
  "tiff",
  "gif",
  "ply",
  "pcd",
  "npy",
  "npz",
  "xyz",
  "xyzn",
  "xyzrgb",
  "pts",
  "asc"
]);

export const sourceFileDialogFilters = [
  {
    name: "DataScope",
    extensions: [
      "csv",
      "tsv",
      "txt",
      "log",
      "dat",
      "lst",
      "list",
      "jsonl",
      "json",
      "mcap",
      "db3",
      "jpg",
      "jpeg",
      "png",
      "bmp",
      "webp",
      "tif",
      "tiff",
      "gif",
      "ply",
      "pcd",
      "npy",
      "npz",
      "xyz",
      "xyzn",
      "xyzrgb",
      "pts",
      "asc"
    ]
  },
  {
    name: "Tables and logs",
    extensions: ["csv", "tsv", "txt", "log", "dat", "lst", "list", "jsonl", "json"]
  },
  {
    name: "Images",
    extensions: ["jpg", "jpeg", "png", "bmp", "webp", "tif", "tiff", "gif"]
  },
  {
    name: "Point Cloud",
    extensions: ["ply", "pcd", "npy", "npz", "xyz", "xyzn", "xyzrgb", "pts", "asc"]
  },
  {
    name: "MCAP",
    extensions: ["mcap"]
  },
  {
    name: "ROS2 SQLite Bag",
    extensions: ["db3"]
  }
];

export function isTerminalJob(job: Job) {
  return ["cancelled", "succeeded", "failed", "interrupted"].includes(job.status);
}

export function isBuildResult(value: BuildResult | BatchResult): value is BuildResult {
  return "recording_id" in value;
}

export function isBatchResult(value: BuildResult | BatchResult): value is BatchResult {
  return "items" in value;
}

export function clearErrorAreaState(current: AreaErrors, area: ErrorArea): AreaErrors {
  if (!current[area]) return current;
  const next = { ...current };
  delete next[area];
  return next;
}

export function normalizeDroppedPath(value: string) {
  const firstLine = value.trim().split(/\r?\n/)[0];
  if (!firstLine) return "";
  return normalizeSourcePathInput(decodeURIComponent(firstLine.replace(/^file:\/\//, "")));
}

export function normalizeSourcePathInput(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return "";
  const roots = ["/home/", "/mnt/", "/media/", "/tmp/", "/var/", "/opt/"];
  for (const root of roots) {
    let index = trimmed.indexOf(root, 1);
    while (index > 0) {
      const prefix = trimmed.slice(0, index);
      const suffix = trimmed.slice(index);
      if (prefix === suffix || prefix.endsWith(suffix)) return suffix;
      index = trimmed.indexOf(root, index + root.length);
    }
  }
  return trimmed;
}

export function defaultOutputName(value: string, kind?: "file" | "folder") {
  const normalized = normalizeSourcePathInput(value).replace(/[\\/]+$/, "");
  const name = normalized.split(/[\\/]/).pop() ?? "";
  if (!name || kind === "folder") return name;
  const extensionIndex = name.lastIndexOf(".");
  const extension = extensionIndex >= 0 ? name.slice(extensionIndex + 1).toLowerCase() : "";
  const isFile = kind === "file" || sourceFileExtensions.has(extension);
  return isFile && extensionIndex > 0 ? name.slice(0, extensionIndex) : name;
}

export function isTauriRuntime() {
  return Boolean((window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__);
}

export function getInitialDefaultExportDir() {
  return window.localStorage.getItem(DEFAULT_EXPORT_DIR_KEY) ?? "";
}

export function saveDefaultExportDir(value: string) {
  window.localStorage.setItem(DEFAULT_EXPORT_DIR_KEY, value.trim());
}

export function getInitialDefaultArtifactDir() {
  return window.localStorage.getItem(DEFAULT_ARTIFACT_DIR_KEY) ?? "";
}

export function saveDefaultArtifactDir(value: string) {
  window.localStorage.setItem(DEFAULT_ARTIFACT_DIR_KEY, value.trim());
}

export function upsertProject(projects: Project[], project: Project) {
  return [project, ...projects.filter((item) => item.id !== project.id)];
}

export function formatDateTime(value: string, language: Language) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(language === "zh" ? "zh-CN" : "en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

export function formatBytes(value: number) {
  if (!Number.isFinite(value) || value < 0) return "-";
  if (value < 1024) return `${value} B`;
  let current = value;
  for (const unit of ["KiB", "MiB", "GiB", "TiB"]) {
    current /= 1024;
    if (current < 1024 || unit === "TiB") return `${current.toFixed(1)} ${unit}`;
  }
  return `${value} B`;
}

export function renderLimitText(language: Language, shown: number, total: number) {
  return language === "zh" ? `已显示 ${shown} / 共 ${total} 条` : `Showing ${shown} of ${total}`;
}

export function derivedMappingFields(semanticType: string) {
  const archetypes: Record<string, string> = {
    scalar: "Scalars",
    scalar_group: "Scalars",
    state: "StateChange",
    text_log: "TextLog",
    image: "EncodedImage",
    points2d: "Points2D",
    segmentation: "SegmentationImage",
    points3d: "Points3D",
    asset3d: "Asset3D",
    trajectory3d: "LineStrips3D",
    boxes2d: "Boxes2D",
    transform3d: "Transform3D",
    mcap: "AnyValues"
  };
  const view =
    ["image", "points2d", "boxes2d", "segmentation"].includes(semanticType)
      ? "Spatial2DView"
      : ["points3d", "trajectory3d", "transform3d"].includes(semanticType)
        ? "Spatial3DView"
        : ["scalar", "scalar_group"].includes(semanticType)
          ? "TimeSeriesView"
          : semanticType === "text_log"
            ? "TextLogView"
            : semanticType === "state"
              ? "StateTimelineView"
              : "DataframeView";
  return { archetype: archetypes[semanticType] ?? "AnyValues", view };
}

export function createErrorPresentation(
  error: ApiError,
  area: ErrorArea | "global",
  t: Translate,
  context: Record<string, unknown> = {}
): ErrorPresentation {
  const paths = Array.isArray(error.details.paths) ? error.details.paths : [];
  const outputName =
    typeof error.details.output_name === "string" ? error.details.output_name : "";
  let title = t("operationFailed");
  let summary = compactErrorMessage(error.message);
  let guidance = t("errorGuidanceTryAgain");
  let tone: ErrorPresentation["tone"] = "danger";

  if (error.code === "artifact_name_conflict") {
    title = t("artifactNameConflict");
    summary = outputName
      ? `${t("artifactNameConflictHint")} (${outputName})`
      : t("artifactNameConflictHint");
    guidance = t("errorGuidanceRenameOutput");
  } else if (error.code === "mapping_validation_failed") {
    title = t("mappingInvalid");
    summary = t("errorMappingDialogSummary");
    guidance = t("errorGuidanceReviewMapping");
    tone = "warning";
  } else if (error.code === "client_validation") {
    summary = compactErrorMessage(error.message);
    guidance = t("errorGuidanceFixInput");
    tone = "warning";
  } else if (area === "global" || ["backend_unavailable", "request_failed"].includes(error.code)) {
    title = t("workspaceError");
    guidance = t("errorGuidanceCheckBackend");
  } else if (area === "build") {
    title = t("buildFailed");
    summary = t("buildFailedHint");
    guidance = t("errorGuidanceReviewBuild");
  } else if (area === "import") {
    title = t("importFailed");
    guidance = t("errorGuidanceReviewSource");
  }

  const details = JSON.stringify(
    {
      area,
      code: error.code,
      status: error.status,
      message: error.message,
      details: error.details,
      paths,
      context
    },
    null,
    2
  );
  return { title, summary, guidance, details, tone };
}

function compactErrorMessage(message: string) {
  const normalized = message.trim().replace(/\s+/g, " ");
  if (normalized.length <= 180) return normalized;
  return `${normalized.slice(0, 177)}...`;
}

export function InlineError({
  id,
  error,
  t,
  area,
  onDetails
}: {
  id?: string;
  error?: ApiError;
  t: Translate;
  area?: ErrorArea | "global";
  onDetails?: (error: ApiError, area: ErrorArea | "global") => void;
}) {
  if (!error) return null;
  const presentation = createErrorPresentation(error, area ?? "global", t);
  return (
    <div className="inline-error" id={id} role="alert">
      <AlertCircle size={17} aria-hidden="true" />
      <div>
        <strong>{presentation.title}</strong>
        <p>{presentation.summary}</p>
        <span className="inline-error-code">{presentation.guidance}</span>
        {onDetails && (
          <button
            className="inline-link-button"
            type="button"
            onClick={() => onDetails(error, area ?? "global")}
          >
            {t("viewDetails")}
          </button>
        )}
      </div>
    </div>
  );
}

export function GlobalErrorToast({
  notification,
  t,
  onDismiss,
  onRetry,
  onDetails
}: {
  notification: GlobalNotification;
  t: Translate;
  onDismiss: () => void;
  onRetry: () => void;
  onDetails?: (error: ApiError) => void;
}) {
  const presentation = createErrorPresentation(notification.error, "global", t);
  return (
    <aside className="error-toast" role="alert" aria-live="assertive">
      <AlertCircle size={19} aria-hidden="true" />
      <div className="error-toast-content">
        <strong>{presentation.title}</strong>
        <p>{presentation.summary}</p>
        <span>{presentation.guidance}</span>
        <div className="toast-actions">
          {notification.retry && (
            <button type="button" onClick={onRetry}>
              <RefreshCcw size={14} />
              {t("retry")}
            </button>
          )}
          {onDetails && (
            <button type="button" onClick={() => onDetails(notification.error)}>
              <AlertCircle size={14} />
              {t("viewDetails")}
            </button>
          )}
        </div>
      </div>
      <button
        className="error-toast-close"
        type="button"
        onClick={onDismiss}
        title={t("close")}
        aria-label={t("close")}
      >
        <X size={16} />
      </button>
    </aside>
  );
}

export function ErrorDialog({
  request,
  t,
  onClose,
  onRetry
}: {
  request: ErrorDialogRequest | null;
  t: Translate;
  onClose: () => void;
  onRetry?: (request: ErrorDialogRequest) => void;
}) {
  const [copied, setCopied] = useState(false);
  if (!request) return null;
  const presentation = createErrorPresentation(request.error, request.area, t, request.context);

  async function copyDetails() {
    await window.navigator.clipboard?.writeText(presentation.details);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  }

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className={`error-dialog is-${presentation.tone}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="error-dialog-title"
        aria-describedby="error-dialog-summary"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="error-dialog-header">
          <div className="error-dialog-icon" aria-hidden="true">
            <AlertCircle size={20} />
          </div>
          <div>
            <h2 id="error-dialog-title">{presentation.title}</h2>
            <p id="error-dialog-summary">{presentation.summary}</p>
          </div>
          <button
            className="error-toast-close"
            type="button"
            onClick={onClose}
            title={t("close")}
            aria-label={t("close")}
          >
            <X size={16} />
          </button>
        </header>
        <div className="error-dialog-guidance">
          <strong>{t("recommendedAction")}</strong>
          <span>{presentation.guidance}</span>
        </div>
        <details className="error-dialog-details">
          <summary>{t("viewDetails")}</summary>
          <pre>{presentation.details}</pre>
        </details>
        <footer className="error-dialog-actions">
          <button type="button" onClick={() => void copyDetails()}>
            <Copy size={15} />
            {copied ? t("copied") : t("copyDetails")}
          </button>
          {request.retry && (
            <button
              className="button-primary"
              type="button"
              onClick={() => onRetry?.(request)}
            >
            <RefreshCcw size={14} />
            {t("retry")}
          </button>
          )}
          <button type="button" onClick={onClose}>{t("close")}</button>
        </footer>
      </section>
    </div>
  );
}

const validationIssueKeys: Record<string, TranslationKey> = {
  missing_time_column: "issueMissingTimeColumn",
  non_monotonic_time: "issueNonMonotonicTime",
  time_nulls: "issueTimeNulls",
  time_parse_failure: "issueTimeParseFailure",
  mixed_time_units: "issueMixedTimeUnits",
  time_unit_mismatch: "issueTimeUnitMismatch",
  invalid_timeline_sort: "issueInvalidTimelineSort",
  unsupported_semantic_type: "issueUnsupportedSemanticType",
  required_field_missing: "issueRequiredFieldMissing",
  field_missing: "issueFieldMissing",
  ambiguous_field_match: "issueAmbiguousFieldMatch",
  ambiguous_time_match: "issueAmbiguousTimeMatch",
  required_fields_empty: "issueRequiredFieldsEmpty",
  fields_empty: "issueFieldsEmpty",
  field_nulls: "issueFieldNulls",
  invalid_entity_path: "issueInvalidEntityPath",
  duplicate_entity_path: "issueDuplicateEntityPath",
  missing_coordinate_axes: "issueMissingCoordinateAxes",
  incomplete_rotation: "issueIncompleteRotation",
  field_unit_mismatch: "issueFieldUnitMismatch",
  mcap_summary_unavailable: "issueMcapSummaryUnavailable",
  mcap_topics_unavailable: "issueMcapTopicsUnavailable",
  ros2_distro_fallback: "issueRos2DistroFallback",
  ros2_topics_skipped: "issueRos2TopicsSkipped",
  ros2_no_convertible_topics: "issueRos2NoConvertibleTopics",
  point_cloud_sample_warning: "issuePointCloudSampleWarning",
  point_cloud_coordinates_missing: "issuePointCloudCoordinatesMissing",
  image_stream_required: "issueImageStreamRequired",
  no_enabled_streams: "issueNoEnabledStreams"
};

const validationRecommendationKeys: Record<string, TranslationKey> = {
  missing_time_column: "recommendMissingTimeColumn",
  non_monotonic_time: "recommendNonMonotonicTime",
  time_nulls: "recommendTimeNulls",
  time_parse_failure: "recommendTimeParseFailure",
  mixed_time_units: "recommendMixedTimeUnits",
  time_unit_mismatch: "recommendTimeUnitMismatch",
  invalid_timeline_sort: "recommendInvalidTimelineSort",
  unsupported_semantic_type: "recommendUnsupportedSemanticType",
  required_field_missing: "recommendRequiredFieldMissing",
  field_missing: "recommendFieldMissing",
  ambiguous_field_match: "recommendAmbiguousFieldMatch",
  ambiguous_time_match: "recommendAmbiguousTimeMatch",
  required_fields_empty: "recommendRequiredFieldsEmpty",
  fields_empty: "recommendFieldsEmpty",
  field_nulls: "recommendFieldNulls",
  invalid_entity_path: "recommendInvalidEntityPath",
  duplicate_entity_path: "recommendDuplicateEntityPath",
  missing_coordinate_axes: "recommendMissingCoordinateAxes",
  incomplete_rotation: "recommendIncompleteRotation",
  field_unit_mismatch: "recommendFieldUnitMismatch",
  mcap_summary_unavailable: "recommendMcapSummaryUnavailable",
  mcap_topics_unavailable: "recommendMcapTopicsUnavailable",
  ros2_distro_fallback: "recommendRos2DistroFallback",
  ros2_topics_skipped: "recommendRos2TopicsSkipped",
  ros2_no_convertible_topics: "recommendRos2NoConvertibleTopics",
  point_cloud_sample_warning: "recommendPointCloudSampleWarning",
  point_cloud_coordinates_missing: "recommendPointCloudCoordinatesMissing",
  image_stream_required: "recommendImageStreamRequired",
  no_enabled_streams: "recommendNoEnabledStreams"
};

export function MappingIssueCard({
  issue,
  language,
  t,
  isBusy,
  onApply
}: {
  issue: MappingValidationIssue;
  language: Language;
  t: Translate;
  isBusy: boolean;
  onApply: (suggestion: MappingSuggestion) => Promise<void>;
}) {
  const suggestions = issue.suggestions ?? [];
  const useSelector =
    suggestions.length > 2 &&
    new Set(suggestions.map((suggestion) => suggestion.action)).size === 1;
  const location = [issue.stream_id, issue.field].filter(Boolean).join(" / ");
  return (
    <article className={`validation-issue is-${issue.severity}`}>
      <div className="validation-issue-heading">
        <span className="validation-severity">{issue.severity.toUpperCase()}</span>
        <strong>{validationIssueKeys[issue.code] ? t(validationIssueKeys[issue.code]) : issue.code}</strong>
        <code>{issue.code}</code>
      </div>
      {location && <span className="validation-location">{location}</span>}
      {issue.message && <p className="validation-message">{issue.message}</p>}
      <p className="validation-recommendation">
        <b>{t("repairSuggestion")}</b>{" "}
        {validationRecommendationKeys[issue.code]
          ? t(validationRecommendationKeys[issue.code])
          : issue.recommendation ?? issue.message ?? issue.code}
      </p>
      {suggestions.length > 0 && (
        <div className="validation-fixes">
          {useSelector ? (
            <select
              value=""
              aria-label={t("chooseRepair")}
              disabled={isBusy}
              onChange={(event) => {
                const suggestion = suggestions[Number(event.target.value)];
                if (suggestion) void onApply(suggestion);
              }}
            >
              <option value="">{t("chooseRepair")}</option>
              {suggestions.map((suggestion, index) => (
                <option key={`${suggestion.action}-${index}`} value={index}>
                  {mappingSuggestionLabel(suggestion, language)}
                </option>
              ))}
            </select>
          ) : (
            suggestions.map((suggestion, index) => (
              <button
                type="button"
                key={`${suggestion.action}-${index}`}
                disabled={isBusy}
                onClick={() => void onApply(suggestion)}
              >
                {mappingSuggestionLabel(suggestion, language)}
              </button>
            ))
          )}
        </div>
      )}
    </article>
  );
}

function mappingSuggestionLabel(suggestion: MappingSuggestion, language: Language) {
  const params = suggestion.params;
  const zh = language === "zh";
  switch (suggestion.action) {
    case "set_timeline_field":
      return params.field
        ? zh ? `使用 ${params.field} 作为时间字段` : `Use ${params.field} as time`
        : zh ? "使用行序列" : "Use row sequence";
    case "set_timeline_unit":
      return zh ? `时间单位设为 ${params.unit}` : `Use ${params.unit}`;
    case "set_timeline_sort":
      return params.sort === "ascending"
        ? zh ? "按时间升序排序" : "Sort by time ascending"
        : zh ? "保持源顺序" : "Keep source order";
    case "replace_source_field":
      return zh ? `改用字段 ${params.new_field}` : `Use field ${params.new_field}`;
    case "set_source_fields":
      return zh
        ? `使用字段 ${(params.fields ?? []).join(", ")}`
        : `Use fields ${(params.fields ?? []).join(", ")}`;
    case "set_entity_path":
      return zh ? `改为 ${params.entity_path}` : `Use ${params.entity_path}`;
    case "set_semantic_type":
      return zh ? `类型改为 ${params.semantic_type}` : `Use ${params.semantic_type}`;
    case "set_stream_enabled":
      return params.enabled
        ? zh ? "启用该流" : "Enable stream"
        : zh ? "禁用可选流" : "Disable optional stream";
    default:
      return suggestion.label;
  }
}

export const NavButton = memo(function NavButton({
  active,
  icon,
  label,
  onClick
}: {
  active: boolean;
  icon: ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button className={`nav-item ${active ? "is-active" : ""}`} onClick={onClick}>
      {icon}
      <span>{label}</span>
    </button>
  );
});

export const StatusBadge = memo(function StatusBadge({
  tone,
  label
}: {
  tone: "success" | "danger" | "neutral";
  label: string;
}) {
  return (
    <span className={`status-badge ${tone}`}>
      {tone === "success" ? <CheckCircle2 size={13} /> : <span className="status-dot" />}
      {label}
    </span>
  );
});

export const Metric = memo(function Metric({
  label,
  value
}: {
  label: string;
  value: string | number;
}) {
  return <div className="metric"><strong>{value}</strong><span>{label}</span></div>;
});

export const ProjectVisual = memo(function ProjectVisual({
  recordings,
  streams,
  jobs
}: {
  recordings: number;
  streams: number;
  jobs: number;
}) {
  const total = Math.max(1, recordings + streams + jobs);
  const values = [
    { label: "Runs", value: recordings, ratio: Math.max(recordings / total, 0.08) },
    { label: "Streams", value: streams, ratio: Math.max(streams / total, 0.08) },
    { label: "Jobs", value: jobs, ratio: Math.max(jobs / total, 0.08) }
  ];
  return (
    <div className="project-visual" aria-hidden="true">
      <div className="visual-card">
        {values.map((item) => (
          <div className="visual-meter" key={item.label}>
            <div><strong>{item.value}</strong><span>{item.label}</span></div>
            <span className="visual-track">
              <span style={{ width: `${Math.round(item.ratio * 100)}%` }} />
            </span>
          </div>
        ))}
        <div className="visual-foot"><span /><span /><span /></div>
      </div>
    </div>
  );
});

export const CardHeader = memo(function CardHeader({
  icon,
  title,
  subtitle
}: {
  icon: ReactNode;
  title: string;
  subtitle?: string;
}) {
  return (
    <div className="card-header">
      <div className="card-icon">{icon}</div>
      <div><h3>{title}</h3>{subtitle && <p>{subtitle}</p>}</div>
    </div>
  );
});

export const SectionTitle = memo(function SectionTitle({
  eyebrow,
  title,
  subtitle,
  action
}: {
  eyebrow: string;
  title: string;
  subtitle: string;
  action?: ReactNode;
}) {
  return (
    <div className="section-title">
      <div><span className="eyebrow">{eyebrow}</span><h2>{title}</h2><p>{subtitle}</p></div>
      {action}
    </div>
  );
});

export const SegmentedControl = memo(function SegmentedControl<T extends string>({
  ariaLabel,
  value,
  options,
  onChange
}: {
  ariaLabel: string;
  value: T;
  options: { value: T; label: string; count?: number }[];
  onChange: (value: T) => void;
}) {
  return (
    <div className="segmented-control app-segmented-control" role="tablist" aria-label={ariaLabel}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="tab"
          aria-selected={value === option.value}
          className={value === option.value ? "is-selected" : ""}
          onClick={() => onChange(option.value)}
        >
          <span>{option.label}</span>
          {typeof option.count === "number" && <em>{option.count}</em>}
        </button>
      ))}
    </div>
  );
});

export const WorkflowSteps = memo(function WorkflowSteps({
  steps
}: {
  steps: { label: string; state: "done" | "active" | "pending" }[];
}) {
  return (
    <ol className="workflow-steps" aria-label="Workflow">
      {steps.map((step, index) => (
        <li className={`workflow-step is-${step.state}`} key={step.label}>
          <span>
            {step.state === "done" ? <CheckCircle2 size={14} /> : index + 1}
          </span>
          <strong>{step.label}</strong>
        </li>
      ))}
    </ol>
  );
});

export const SummaryTile = memo(function SummaryTile({
  label,
  value,
  detail,
  tone = "neutral"
}: {
  label: string;
  value: string | number;
  detail?: string;
  tone?: "neutral" | "success" | "danger" | "primary";
}) {
  return (
    <div className={`summary-tile ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {detail && <small>{detail}</small>}
    </div>
  );
});

export const StreamTable = memo(function StreamTable({
  streams,
  labels
}: {
  streams: StreamInfo[];
  labels: {
    empty: string;
    name: string;
    semanticType: string;
    fields: string;
    time: string;
    confidence: string;
  };
}) {
  if (!streams.length) return <EmptyState text={labels.empty} />;
  return (
    <div className="table-wrap responsive-table">
      <table>
        <thead><tr>
          <th>{labels.name}</th><th>{labels.semanticType}</th><th>{labels.fields}</th>
          <th>{labels.time}</th><th>{labels.confidence}</th>
        </tr></thead>
        <tbody>
          {streams.map((stream) => (
            <tr key={stream.stream_id}>
              <td data-label={labels.name}>{stream.name}</td>
              <td data-label={labels.semanticType}>{stream.semantic_type}</td>
              <td data-label={labels.fields}>{stream.fields.join(", ")}</td>
              <td data-label={labels.time}>{stream.time_key ?? "row"}</td>
              <td data-label={labels.confidence}>{Math.round(stream.confidence * 100)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
});

export const ResultTable = memo(function ResultTable({
  result,
  emptyText
}: {
  result: QueryResult | null;
  emptyText: string;
}) {
  if (!result?.rows.length) return <EmptyState text={emptyText} />;
  return (
    <div className="table-wrap responsive-table">
      <table>
        <thead><tr>{result.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
        <tbody>
          {result.rows.slice(0, 50).map((row, index) => (
            <tr key={index}>
              {result.columns.map((column) => (
                <td key={column} data-label={column}>{formatCell(row[column])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
});

export const EmptyState = memo(function EmptyState({ text }: { text: string }) {
  return <div className="empty-state"><Command size={17} /><span>{text}</span></div>;
});

function formatCell(value: unknown) {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
