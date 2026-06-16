import { useMemo, useState } from "react";
import {
  Activity,
  Clipboard,
  Download,
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
  DiagnosticReport,
  DiagnosticThresholds,
  Recording
} from "./types";

type Translate = (key: TranslationKey) => string;

type DiagnosticsSectionProps = {
  selectedProjectId: string;
  recordings: Recording[];
  report: DiagnosticReport | null;
  isBusy: boolean;
  errors: AreaErrors;
  t: Translate;
  onRun: (recordingIds: string[], thresholds: DiagnosticThresholds) => void;
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
  isBusy,
  errors,
  t,
  onRun
}: DiagnosticsSectionProps) {
  const [selectedRecordingIds, setSelectedRecordingIds] = useState<string[]>([]);
  const [thresholds, setThresholds] = useState(defaultThresholds);
  const effectiveRecordingCount = selectedRecordingIds.length || recordings.length;
  const reportJson = useMemo(
    () => (report ? JSON.stringify(report, null, 2) : ""),
    [report]
  );

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
      {
        battery_low: Number(thresholds.battery_low),
        detection_confidence: Number(thresholds.detection_confidence),
        time_sync_warn_s: Number(thresholds.time_sync_warn_s),
        time_sync_critical_s: Number(thresholds.time_sync_critical_s)
      }
    );
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
              <div className="table-wrap responsive-table">
                <table>
                  <thead>
                    <tr>
                      <th>{t("severity")}</th>
                      <th>{t("category")}</th>
                      <th>{t("recording")}</th>
                      <th>{t("message")}</th>
                      <th>{t("recommendation")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.findings.map((finding) => (
                      <tr key={finding.id}>
                        <td data-label={t("severity")}>{finding.severity}</td>
                        <td data-label={t("category")}>{finding.category}</td>
                        <td data-label={t("recording")}>{finding.recording_id ?? "-"}</td>
                        <td data-label={t("message")}>{finding.message}</td>
                        <td data-label={t("recommendation")}>{finding.recommendation}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
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
    </section>
  );
}
