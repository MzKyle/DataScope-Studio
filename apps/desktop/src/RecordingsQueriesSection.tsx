import {
  Activity,
  Download,
  ExternalLink,
  ListChecks,
  Search,
  Tags
} from "lucide-react";

import {
  CardHeader,
  EmptyState,
  InlineError,
  ResultTable,
  SectionTitle,
  formatBytes,
  renderLimitText,
  type AreaErrors
} from "./app-support";
import { JobList } from "./JobList";
import type { Language, TranslationKey } from "./i18n";
import type {
  Job,
  QueryResult,
  QueryTemplate,
  Recording
} from "./types";

type Translate = (key: TranslationKey) => string;

type RecordingsQueriesSectionProps = {
  recordings: Recording[];
  visibleRecordings: Recording[];
  tagInput: string;
  queryTemplates: QueryTemplate[];
  selectedQueryTemplate: string;
  selectedQueryRecording: string;
  queryRecordingOptions: Recording[];
  thresholdTemplates: Set<string>;
  queryThreshold: string;
  selectedProjectId: string;
  exportPath: string;
  queryResult: QueryResult | null;
  compareRecordingIds: string;
  compareMetric: string;
  compareResult: QueryResult | null;
  jobs: Job[];
  visibleJobs: Job[];
  isBusy: boolean;
  language: Language;
  errors: AreaErrors;
  t: Translate;
  onTagInputChange: (value: string) => void;
  onOpenRecording: (recording: Recording) => void;
  onAddTag: (recordingId: string) => void;
  onQueryTemplateChange: (templateId: string) => void;
  onQueryRecordingChange: (recordingId: string) => void;
  onQueryThresholdChange: (value: string) => void;
  onRunQuery: () => void;
  onExportQuery: () => void;
  onCompareRecordingIdsChange: (value: string) => void;
  onCompareMetricChange: (value: string) => void;
  onRunCompare: () => void;
  onCancelJob: (job: Job) => void;
  onRetryJob: (job: Job) => void;
};

export function RecordingsQueriesSection({
  recordings,
  visibleRecordings,
  tagInput,
  queryTemplates,
  selectedQueryTemplate,
  selectedQueryRecording,
  queryRecordingOptions,
  thresholdTemplates,
  queryThreshold,
  selectedProjectId,
  exportPath,
  queryResult,
  compareRecordingIds,
  compareMetric,
  compareResult,
  jobs,
  visibleJobs,
  isBusy,
  language,
  errors,
  t,
  onTagInputChange,
  onOpenRecording,
  onAddTag,
  onQueryTemplateChange,
  onQueryRecordingChange,
  onQueryThresholdChange,
  onRunQuery,
  onExportQuery,
  onCompareRecordingIdsChange,
  onCompareMetricChange,
  onRunCompare,
  onCancelJob,
  onRetryJob
}: RecordingsQueriesSectionProps) {
  return (
    <section className="section-stack" id="recordings">
      <SectionTitle
        eyebrow={t("workspace")}
        title={t("recordingsQueries")}
        subtitle={t("recordingsQueriesSubtitle")}
      />
      <div className="two-column">
        <section className="card">
          <CardHeader icon={<ListChecks size={18} />} title={t("recordingBrowser")} />
          {recordings.length ? (
            <>
              <div className="tag-row">
                <input
                  placeholder={t("tagPlaceholder")}
                  value={tagInput}
                  onChange={(event) => onTagInputChange(event.target.value)}
                />
              </div>
              <InlineError error={errors.recordings} t={t} />
              <div className="table-wrap responsive-table">
                <table>
                  <thead>
                    <tr>
                      <th>{t("run")}</th>
                      <th>{t("template")}</th>
                      <th>{t("source")}</th>
                      <th>{t("artifactStatus")}</th>
                      <th>{t("tags")}</th>
                      <th>{t("action")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleRecordings.map((recording) => {
                      const artifact = recording.params.rerun_artifact;
                      const artifactStatus = recording.artifact_status;
                      const artifactReady = !artifactStatus || artifactStatus.status === "ready";
                      const recordingSize =
                        artifact?.recording_size_bytes ?? artifactStatus?.recording_size_bytes;
                      const blueprintSize =
                        artifact?.blueprint_size_bytes ?? artifactStatus?.blueprint_size_bytes;
                      return (
                        <tr key={recording.id}>
                          <td data-label={t("run")}>
                            <strong>{recording.run_name}</strong>
                            <span className="subline">{recording.id}</span>
                          </td>
                          <td data-label={t("template")}>{recording.blueprint_id}</td>
                          <td data-label={t("source")}>{recording.source_type ?? t("unknown")}</td>
                          <td data-label={t("artifactStatus")}>
                            {artifactReady ? (
                              <>
                                <strong>{t("ready")}</strong>
                                {typeof recordingSize === "number" &&
                                typeof blueprintSize === "number" ? (
                                  <span className="subline">
                                    {formatBytes(recordingSize)} / {formatBytes(blueprintSize)}
                                  </span>
                                ) : null}
                              </>
                            ) : artifactStatus?.status === "empty" ? (
                              <>
                                <strong>{t("artifactEmpty")}</strong>
                                <span className="subline">{artifactStatus.message}</span>
                              </>
                            ) : (
                              <>
                                <strong>{t("artifactMissing")}</strong>
                                <span className="subline">{artifactStatus?.message}</span>
                              </>
                            )}
                          </td>
                          <td data-label={t("tags")}>{recording.tags.join(", ") || "-"}</td>
                          <td data-label={t("action")}>
                            <button
                              onClick={() => onOpenRecording(recording)}
                              disabled={isBusy || !artifactReady}
                            >
                              <ExternalLink size={16} />
                              {t("openInRerun")}
                            </button>
                            <button onClick={() => onAddTag(recording.id)} disabled={isBusy}>
                              <Tags size={16} />
                              {t("addTag")}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {visibleRecordings.length < recordings.length && (
                <p className="render-limit-note">
                  {renderLimitText(language, visibleRecordings.length, recordings.length)}
                </p>
              )}
            </>
          ) : (
            <EmptyState text={t("recordingBrowserEmpty")} />
          )}
        </section>

        <section className="card">
          <CardHeader icon={<Search size={18} />} title={t("queryConsole")} />
          <div className="query-controls">
            <select
              value={selectedQueryTemplate}
              onChange={(event) => onQueryTemplateChange(event.target.value)}
            >
              {queryTemplates.length ? (
                queryTemplates.map((template) => (
                  <option key={template.template_id} value={template.template_id}>
                    {template.name}
                  </option>
                ))
              ) : (
                <option value="low_battery">{t("lowBattery")}</option>
              )}
            </select>
            <select
              value={selectedQueryRecording}
              onChange={(event) => onQueryRecordingChange(event.target.value)}
            >
              <option value="">{t("allRecordings")}</option>
              {queryRecordingOptions.map((recording) => (
                <option key={recording.id} value={recording.id}>
                  {recording.run_name}
                </option>
              ))}
            </select>
            {queryRecordingOptions.length < recordings.length && (
              <span className="field-hint">
                {renderLimitText(language, queryRecordingOptions.length, recordings.length)}
              </span>
            )}
            {thresholdTemplates.has(selectedQueryTemplate) && (
              <input
                aria-label={t("queryThreshold")}
                value={queryThreshold}
                onChange={(event) => onQueryThresholdChange(event.target.value)}
              />
            )}
            <button
              className="button-primary"
              onClick={onRunQuery}
              disabled={!selectedProjectId || isBusy}
            >
              <Search size={16} />
              {t("runQuery")}
            </button>
            <button onClick={onExportQuery} disabled={!selectedProjectId || isBusy}>
              <Download size={16} />
              {t("exportCsv")}
            </button>
          </div>
          <InlineError error={errors.query} t={t} />
          {exportPath && <p className="path-line light">{t("exported")}: {exportPath}</p>}
          <ResultTable result={queryResult} emptyText={t("queryEmpty")} />
        </section>
      </div>

      <div className="two-column balanced">
        <section className="card">
          <CardHeader icon={<Search size={18} />} title={t("runCompare")} />
          <div className="query-controls">
            <input
              placeholder={t("recordingIdsPlaceholder")}
              value={compareRecordingIds}
              onChange={(event) => onCompareRecordingIdsChange(event.target.value)}
            />
            <input
              placeholder={t("metricPlaceholder")}
              value={compareMetric}
              onChange={(event) => onCompareMetricChange(event.target.value)}
            />
            <button
              className="button-primary"
              onClick={onRunCompare}
              disabled={!selectedProjectId || isBusy}
            >
              <Search size={16} />
              {t("compare")}
            </button>
          </div>
          <InlineError error={errors.compare} t={t} />
          <ResultTable result={compareResult} emptyText={t("compareEmpty")} />
        </section>

        <section className="card">
          <CardHeader icon={<Activity size={18} />} title={t("jobs")} />
          {jobs.length ? (
            <JobList
              jobs={visibleJobs}
              disabled={isBusy}
              onCancel={onCancelJob}
              onRetry={onRetryJob}
              t={t}
            />
          ) : (
            <EmptyState text={t("jobsEmpty")} />
          )}
        </section>
      </div>
    </section>
  );
}
