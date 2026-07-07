import { useState } from "react";
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
  SegmentedControl,
  SectionTitle,
  formatBytes,
  renderLimitText,
  type AreaErrors
} from "./app-support";
import { JobList } from "./JobList";
import type { Language, TranslationKey } from "./i18n";
import type {
  CustomQueryFilters,
  Job,
  QueryResult,
  QueryTemplate,
  Recording
} from "./types";

type Translate = (key: TranslationKey) => string;
type RecordingsPanel = "recordings" | "query" | "custom" | "compare" | "jobs";

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
  customQueryEntityPath: string;
  customQueryKey: string;
  customQueryText: string;
  customQuerySemanticTypes: string;
  customQueryOperator: NonNullable<CustomQueryFilters["operator"]>;
  customQueryValue: string;
  customQueryTimeStart: string;
  customQueryTimeEnd: string;
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
  onCustomQueryEntityPathChange: (value: string) => void;
  onCustomQueryKeyChange: (value: string) => void;
  onCustomQueryTextChange: (value: string) => void;
  onCustomQuerySemanticTypesChange: (value: string) => void;
  onCustomQueryOperatorChange: (value: NonNullable<CustomQueryFilters["operator"]>) => void;
  onCustomQueryValueChange: (value: string) => void;
  onCustomQueryTimeStartChange: (value: string) => void;
  onCustomQueryTimeEndChange: (value: string) => void;
  onRunCustomQuery: () => void;
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
  customQueryEntityPath,
  customQueryKey,
  customQueryText,
  customQuerySemanticTypes,
  customQueryOperator,
  customQueryValue,
  customQueryTimeStart,
  customQueryTimeEnd,
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
  onCustomQueryEntityPathChange,
  onCustomQueryKeyChange,
  onCustomQueryTextChange,
  onCustomQuerySemanticTypesChange,
  onCustomQueryOperatorChange,
  onCustomQueryValueChange,
  onCustomQueryTimeStartChange,
  onCustomQueryTimeEndChange,
  onRunCustomQuery,
  onCompareRecordingIdsChange,
  onCompareMetricChange,
  onRunCompare,
  onCancelJob,
  onRetryJob
}: RecordingsQueriesSectionProps) {
  const [activePanel, setActivePanel] = useState<RecordingsPanel>("recordings");
  const panelOptions: { value: RecordingsPanel; label: string; count?: number }[] = [
    { value: "recordings" as const, label: t("tabRecordings"), count: recordings.length },
    { value: "query" as const, label: t("tabQuery"), count: queryResult?.rows.length ?? 0 },
    { value: "custom" as const, label: t("tabCustomQuery") },
    { value: "compare" as const, label: t("tabCompare"), count: compareResult?.rows.length ?? 0 },
    { value: "jobs" as const, label: t("tabJobs"), count: jobs.length }
  ];

  return (
    <section className="section-stack" id="recordings">
      <SectionTitle
        eyebrow={t("workspace")}
        title={t("recordingsQueries")}
        subtitle={t("recordingsQueriesSubtitle")}
      />

      <SegmentedControl
        ariaLabel={t("recordingsQuerySections")}
        value={activePanel}
        options={panelOptions}
        onChange={(value) => setActivePanel(value as RecordingsPanel)}
      />

      {activePanel === "recordings" && (
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
                            <div className="table-actions">
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
                            </div>
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
      )}

      {activePanel === "query" && (
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
      )}

      {activePanel === "custom" && (
        <section className="card">
          <CardHeader icon={<Search size={18} />} title={t("customQueryBuilder")} />
          <div className="custom-query-grid">
            <input
              aria-label={t("entityPath")}
              placeholder={t("entityPath")}
              value={customQueryEntityPath}
              onChange={(event) => onCustomQueryEntityPathChange(event.target.value)}
            />
            <input
              aria-label={t("fieldKey")}
              placeholder={t("fieldKey")}
              value={customQueryKey}
              onChange={(event) => onCustomQueryKeyChange(event.target.value)}
            />
            <input
              aria-label={t("customQueryText")}
              placeholder={t("customQueryText")}
              value={customQueryText}
              onChange={(event) => onCustomQueryTextChange(event.target.value)}
            />
            <input
              aria-label={t("semanticTypes")}
              placeholder="scalar,scalar_group,state"
              value={customQuerySemanticTypes}
              onChange={(event) => onCustomQuerySemanticTypesChange(event.target.value)}
            />
            <select
              aria-label={t("operator")}
              value={customQueryOperator}
              onChange={(event) =>
                onCustomQueryOperatorChange(
                  event.target.value as NonNullable<CustomQueryFilters["operator"]>
                )
              }
            >
              <option value="any">{t("operatorAny")}</option>
              <option value="contains">contains</option>
              <option value="eq">=</option>
              <option value="gt">&gt;</option>
              <option value="gte">&gt;=</option>
              <option value="lt">&lt;</option>
              <option value="lte">&lt;=</option>
            </select>
            <input
              aria-label={t("customQueryValue")}
              placeholder={t("customQueryValue")}
              value={customQueryValue}
              onChange={(event) => onCustomQueryValueChange(event.target.value)}
            />
            <input
              aria-label={t("timeStart")}
              placeholder={t("timeStart")}
              value={customQueryTimeStart}
              onChange={(event) => onCustomQueryTimeStartChange(event.target.value)}
            />
            <input
              aria-label={t("timeEnd")}
              placeholder={t("timeEnd")}
              value={customQueryTimeEnd}
              onChange={(event) => onCustomQueryTimeEndChange(event.target.value)}
            />
          </div>
          <div className="actions">
            <button
              className="button-primary"
              onClick={onRunCustomQuery}
              disabled={!selectedProjectId || isBusy}
            >
              <Search size={16} />
              {t("runCustomQuery")}
            </button>
          </div>
          <InlineError error={errors.query} t={t} />
          <ResultTable result={queryResult} emptyText={t("queryEmpty")} />
        </section>
      )}

      {activePanel === "compare" && (
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
      )}

      {activePanel === "jobs" && (
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
      )}
    </section>
  );
}
