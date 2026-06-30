import { Fragment, useEffect, useMemo, useState } from "react";
import {
  Activity,
  Clipboard,
  Download,
  FileText,
  Gauge,
  ListChecks,
  Search
} from "lucide-react";

import {
  CardHeader,
  EmptyState,
  InlineError,
  SectionTitle,
  type AreaErrors
} from "./app-support";
import type { TranslationKey } from "./i18n";
import type {
  DiagnosticExport,
  DiagnosticExportResult,
  DiagnosticPreset,
  DiagnosticReport,
  DiagnosticThresholds,
  Recording
} from "./types";

type Translate = (key: TranslationKey) => string;

type DiagnosticsSectionProps = {
  selectedProjectId: string;
  recordings: Recording[];
  report: DiagnosticReport | null;
  presets?: DiagnosticPreset[];
  exports?: DiagnosticExport[];
  exportResult?: DiagnosticExportResult | null;
  isBusy: boolean;
  errors: AreaErrors;
  t: Translate;
  onRun: (recordingIds: string[], thresholds: DiagnosticThresholds, preset: string) => void;
  onExport?: (
    recordingIds: string[],
    thresholds: DiagnosticThresholds,
    preset: string,
    format: "json" | "csv" | "html"
  ) => void;
};

const defaultThresholds = {
  battery_low: "0.2",
  detection_confidence: "0.5",
  time_sync_warn_s: "0.1",
  time_sync_critical_s: "1.0"
};

export function DiagnosticsSection({
  selectedProjectId,
  recordings,
  report,
  presets = [],
  exports = [],
  exportResult = null,
  isBusy,
  errors,
  t,
  onRun,
  onExport = () => undefined
}: DiagnosticsSectionProps) {
  const [selectedRecordingIds, setSelectedRecordingIds] = useState<string[]>([]);
  const [thresholds, setThresholds] = useState(defaultThresholds);
  const [selectedPreset, setSelectedPreset] = useState("balanced");
  const [exportFormat, setExportFormat] = useState<"json" | "csv" | "html">("json");
  const [severityFilter, setSeverityFilter] = useState("all");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [locatorFilter, setLocatorFilter] = useState("");
  const [expandedFindingId, setExpandedFindingId] = useState("");
  const effectiveRecordingCount = selectedRecordingIds.length || recordings.length;
  const reportJson = useMemo(
    () => (report ? JSON.stringify(report, null, 2) : ""),
    [report]
  );
  const categories = useMemo(
    () => Array.from(new Set(report?.findings.map((finding) => finding.category) ?? [])).sort(),
    [report]
  );
  const filteredFindings = useMemo(() => {
    const locator = locatorFilter.trim().toLowerCase();
    return (report?.findings ?? []).filter((finding) => {
      if (severityFilter !== "all" && finding.severity !== severityFilter) return false;
      if (categoryFilter !== "all" && finding.category !== categoryFilter) return false;
      if (!locator) return true;
      return [
        finding.recording_id,
        finding.source_id,
        finding.topic,
        finding.entity_path,
        finding.key,
        finding.message
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(locator));
    });
  }, [categoryFilter, locatorFilter, report, severityFilter]);

  useEffect(() => {
    const preset = presets.find((item) => item.id === selectedPreset);
    if (!preset) return;
    setThresholds({
      battery_low: String(preset.thresholds.battery_low),
      detection_confidence: String(preset.thresholds.detection_confidence),
      time_sync_warn_s: String(preset.thresholds.time_sync_warn_s),
      time_sync_critical_s: String(preset.thresholds.time_sync_critical_s)
    });
  }, [presets, selectedPreset]);

  function toggleRecording(recordingId: string) {
    setSelectedRecordingIds((current) =>
      current.includes(recordingId)
        ? current.filter((item) => item !== recordingId)
        : [...current, recordingId]
    );
  }

  function runDiagnostics() {
    onRun(
      selectedRecordingIds,
      parsedThresholds(),
      selectedPreset
    );
  }

  function exportDiagnostics() {
    onExport(selectedRecordingIds, parsedThresholds(), selectedPreset, exportFormat);
  }

  function parsedThresholds(): DiagnosticThresholds {
    return {
      battery_low: Number(thresholds.battery_low),
      detection_confidence: Number(thresholds.detection_confidence),
      time_sync_warn_s: Number(thresholds.time_sync_warn_s),
      time_sync_critical_s: Number(thresholds.time_sync_critical_s)
    };
  }

  function exportJson() {
    if (!reportJson) return;
    const blob = new Blob([reportJson], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `datascope-diagnostics-${report?.project_id ?? "project"}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function copyJson() {
    if (!reportJson) return;
    await window.navigator.clipboard?.writeText(reportJson);
  }

  return (
    <section className="section-stack" id="diagnostics">
      <SectionTitle
        eyebrow={t("workspace")}
        title={t("diagnostics")}
        subtitle={t("diagnosticsSubtitle")}
      />

      <div className="two-column">
        <section className="card">
          <CardHeader
            icon={<Search size={18} />}
            title={t("diagnosticsControls")}
            subtitle={t("diagnosticsControlsSubtitle")}
          />
          <label className="field-label">
            {t("diagnosticPreset")}
            <select
              value={selectedPreset}
              onChange={(event) => setSelectedPreset(event.target.value)}
            >
              {(presets.length
                ? presets
                : [{ id: "balanced", name: "Balanced", description: "", thresholds: {
                    battery_low: 0.2,
                    detection_confidence: 0.5,
                    time_sync_warn_s: 0.1,
                    time_sync_critical_s: 1.0
                  } }]
              ).map((preset) => (
                <option key={preset.id} value={preset.id}>
                  {preset.name}
                </option>
              ))}
            </select>
          </label>
          <div className="diagnostics-thresholds">
            <label>
              <span>{t("batteryLowThreshold")}</span>
              <input
                value={thresholds.battery_low}
                onChange={(event) =>
                  setThresholds((current) => ({ ...current, battery_low: event.target.value }))
                }
              />
            </label>
            <label>
              <span>{t("detectionConfidenceThreshold")}</span>
              <input
                value={thresholds.detection_confidence}
                onChange={(event) =>
                  setThresholds((current) => ({
                    ...current,
                    detection_confidence: event.target.value
                  }))
                }
              />
            </label>
            <label>
              <span>{t("timeSyncWarnThreshold")}</span>
              <input
                value={thresholds.time_sync_warn_s}
                onChange={(event) =>
                  setThresholds((current) => ({
                    ...current,
                    time_sync_warn_s: event.target.value
                  }))
                }
              />
            </label>
            <label>
              <span>{t("timeSyncCriticalThreshold")}</span>
              <input
                value={thresholds.time_sync_critical_s}
                onChange={(event) =>
                  setThresholds((current) => ({
                    ...current,
                    time_sync_critical_s: event.target.value
                  }))
                }
              />
            </label>
          </div>
          <div className="actions">
            <button
              className="button-primary"
              onClick={runDiagnostics}
              disabled={!selectedProjectId || isBusy}
            >
              <Activity size={16} />
              {t("runDiagnostics")}
            </button>
            <select
              aria-label={t("exportFormat")}
              value={exportFormat}
              onChange={(event) =>
                setExportFormat(event.target.value as "json" | "csv" | "html")
              }
            >
              <option value="json">JSON</option>
              <option value="csv">CSV</option>
              <option value="html">HTML</option>
            </select>
            <button onClick={exportDiagnostics} disabled={!selectedProjectId || isBusy}>
              <FileText size={16} />
              {t("exportDiagnostics")}
            </button>
            <button onClick={exportJson} disabled={!report || isBusy}>
              <Download size={16} />
              {t("exportJson")}
            </button>
            <button onClick={() => void copyJson()} disabled={!report || isBusy}>
              <Clipboard size={16} />
              {t("copyJson")}
            </button>
          </div>
          <InlineError error={errors.diagnostics} t={t} />
          <p className="path-line light">
            {t("diagnosticsRecordingScope")}: {effectiveRecordingCount}
          </p>
          {exportResult && (
            <p className="path-line light">
              {t("lastDiagnosticExport")}: {exportResult.path}
            </p>
          )}
        </section>

        <section className="card">
          <CardHeader
            icon={<ListChecks size={18} />}
            title={t("diagnosticsRecordings")}
            subtitle={t("diagnosticsRecordingsSubtitle")}
          />
          {recordings.length ? (
            <div className="diagnostics-recordings">
              {recordings.map((recording) => (
                <label key={recording.id} className="diagnostic-recording-option">
                  <input
                    type="checkbox"
                    checked={selectedRecordingIds.includes(recording.id)}
                    onChange={() => toggleRecording(recording.id)}
                  />
                  <span>
                    <strong>{recording.run_name}</strong>
                    <small>{recording.id}</small>
                  </span>
                </label>
              ))}
            </div>
          ) : (
            <EmptyState text={t("diagnosticsNoRecordings")} />
          )}
        </section>
      </div>

      {report ? (
        <>
          <section className={`card diagnostics-summary severity-${report.summary.severity}`}>
            <CardHeader icon={<Gauge size={18} />} title={t("diagnosticsSummary")} />
            <div className="diagnostics-score">
              <strong>{report.summary.health_score}</strong>
              <span>{report.summary.severity.toUpperCase()}</span>
            </div>
            <dl className="meta-grid">
              <div>
                <dt>{t("recordings")}</dt>
                <dd>{report.summary.recording_count}</dd>
              </div>
              <div>
                <dt>{t("source")}</dt>
                <dd>{report.summary.source_count}</dd>
              </div>
              <div>
                <dt>{t("topics")}</dt>
                <dd>{report.summary.topic_count}</dd>
              </div>
              <div>
                <dt>{t("findings")}</dt>
                <dd>{report.summary.finding_count}</dd>
              </div>
            </dl>
          </section>

          <section className="diagnostic-check-grid">
            {report.checks.map((check) => (
              <article key={check.id} className={`card diagnostic-check severity-${check.severity}`}>
                <div className="diagnostic-check-heading">
                  <strong>{check.name}</strong>
                  <span>{check.status}</span>
                </div>
                <p>{t("score")}: {check.score}</p>
                <p className="path-line light">{check.recommendation}</p>
              </article>
            ))}
          </section>

          <section className="card">
            <CardHeader icon={<Activity size={18} />} title={t("findings")} />
            {report.findings.length ? (
              <>
                <div className="diagnostics-filters">
                  <select
                    aria-label={t("severity")}
                    value={severityFilter}
                    onChange={(event) => setSeverityFilter(event.target.value)}
                  >
                    <option value="all">{t("allSeverities")}</option>
                    <option value="critical">critical</option>
                    <option value="warning">warning</option>
                    <option value="info">info</option>
                  </select>
                  <select
                    aria-label={t("category")}
                    value={categoryFilter}
                    onChange={(event) => setCategoryFilter(event.target.value)}
                  >
                    <option value="all">{t("allCategories")}</option>
                    {categories.map((category) => (
                      <option key={category} value={category}>
                        {category}
                      </option>
                    ))}
                  </select>
                  <input
                    aria-label={t("findingLocator")}
                    placeholder={t("findingLocator")}
                    value={locatorFilter}
                    onChange={(event) => setLocatorFilter(event.target.value)}
                  />
                </div>
                <div className="table-wrap responsive-table">
                  <table>
                    <thead>
                      <tr>
                        <th>{t("severity")}</th>
                        <th>{t("category")}</th>
                        <th>{t("recording")}</th>
                        <th>{t("source")}</th>
                        <th>{t("topics")}</th>
                        <th>{t("message")}</th>
                        <th>{t("recommendation")}</th>
                        <th>{t("action")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredFindings.map((finding) => (
                        <Fragment key={finding.id}>
                          <tr>
                            <td data-label={t("severity")}>{finding.severity}</td>
                            <td data-label={t("category")}>{finding.category}</td>
                            <td data-label={t("recording")}>{finding.recording_id ?? "-"}</td>
                            <td data-label={t("source")}>{finding.source_id ?? "-"}</td>
                            <td data-label={t("topics")}>{finding.topic ?? "-"}</td>
                            <td data-label={t("message")}>{finding.message}</td>
                            <td data-label={t("recommendation")}>{finding.recommendation}</td>
                            <td data-label={t("action")}>
                              <button
                                type="button"
                                onClick={() =>
                                  setExpandedFindingId((current) =>
                                    current === finding.id ? "" : finding.id
                                  )
                                }
                              >
                                <ListChecks size={16} />
                                {t("evidence")}
                              </button>
                            </td>
                          </tr>
                          {expandedFindingId === finding.id && (
                            <tr>
                              <td colSpan={8}>
                                <pre className="diagnostic-evidence">
                                  {JSON.stringify(finding.evidence, null, 2)}
                                </pre>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      ))}
                    </tbody>
                  </table>
                </div>
                {!filteredFindings.length && <EmptyState text={t("diagnosticsNoFindings")} />}
              </>
            ) : (
              <EmptyState text={t("diagnosticsNoFindings")} />
            )}
          </section>
        </>
      ) : (
        <section className="card">
          <EmptyState text={t("diagnosticsEmpty")} />
        </section>
      )}

      <section className="card">
        <CardHeader icon={<FileText size={18} />} title={t("persistentExports")} />
        {exports.length ? (
          <div className="table-wrap responsive-table">
            <table>
              <thead>
                <tr>
                  <th>{t("createdAt")}</th>
                  <th>{t("type")}</th>
                  <th>{t("findings")}</th>
                  <th>{t("pathApp")}</th>
                </tr>
              </thead>
              <tbody>
                {exports.map((item) => (
                  <tr key={item.id}>
                    <td data-label={t("createdAt")}>{item.created_at}</td>
                    <td data-label={t("type")}>{item.format}</td>
                    <td data-label={t("findings")}>{item.summary.finding_count}</td>
                    <td data-label={t("pathApp")}>{item.path}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState text={t("noDiagnosticExports")} />
        )}
      </section>
    </section>
  );
}
