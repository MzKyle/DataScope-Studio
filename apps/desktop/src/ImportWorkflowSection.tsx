import { useState, type RefObject } from "react";
import {
  Activity,
  CheckCircle2,
  ExternalLink,
  FileSearch,
  FolderOpen,
  Image,
  ListChecks,
  LoaderCircle,
  Play,
  Save,
  SlidersHorizontal
} from "lucide-react";

import { BuildJobStatus, isActiveBuildJob } from "./BuildJobStatus";
import {
  CardHeader,
  EmptyState,
  InlineError,
  MappingIssueCard,
  SectionTitle,
  StreamTable,
  WorkflowSteps,
  formatBytes,
  type AreaErrors
} from "./app-support";
import type { Language, TranslationKey } from "./i18n";
import type {
  BuildResult,
  Job,
  MappingDiff,
  MappingPayload,
  MappingSuggestion,
  MappingTemplateItem,
  MappingValidation,
  SchemaProfile,
  Source,
  StreamInfo,
  TemplateMatch
} from "./types";

type Translate = (key: TranslationKey) => string;
type MappingStreamKey = "entity_path" | "semantic_type" | "source_fields" | "enabled";
type TimelineKey = "source_field" | "unit" | "sort";

type ImportWorkflowSectionProps = {
  selectedTemplateId: string;
  templateOptions: TemplateMatch[];
  selectedMappingTemplateId: string;
  mappingTemplates: MappingTemplateItem[];
  mappingTemplateName: string;
  source: Source | null;
  streams: StreamInfo[];
  mapping: MappingPayload | null;
  schemaProfile: SchemaProfile | null;
  mappingValidation: MappingValidation | null;
  mappingConfirmed: boolean;
  savedMappingId: string;
  mappingDiff: MappingDiff | null;
  projectSources: Source[];
  diffLeftSourceId: string;
  diffRightSourceId: string;
  supportedSemanticTypes: string[];
  timeUnits: string[];
  outputNameRef: RefObject<HTMLInputElement | null>;
  outputName: string;
  artifactOutputDir: string;
  mcapDecoders: string;
  rrdOptimizeProfile: string;
  artifactValidation: string;
  catalogEnabled: boolean;
  catalogDataset: string;
  catalogManagedLocal: boolean;
  catalogServerUrl: string;
  rerun033Available: boolean;
  buildResult: BuildResult | null;
  buildJob: Job | null;
  isBuildSubmitting: boolean;
  previewRows: Record<string, unknown>[];
  previewText: string;
  isBusy: boolean;
  language: Language;
  errors: AreaErrors;
  t: Translate;
  onTemplateChange: (templateId: string) => void;
  onSelectedMappingTemplateChange: (templateId: string) => void;
  onApplyMappingTemplate: () => void;
  onMappingTemplateNameChange: (name: string) => void;
  onCreateMappingTemplate: () => void;
  onUpdateTimeline: (key: TimelineKey, value: string) => void;
  onUpdateMappingStream: (
    index: number,
    key: MappingStreamKey,
    value: string | boolean
  ) => void;
  onApplyMappingSuggestion: (suggestion: MappingSuggestion) => Promise<void>;
  onSaveMapping: () => void;
  onValidateMapping: () => void;
  onConfirmMapping: () => void;
  onDiffLeftSourceChange: (sourceId: string) => void;
  onDiffRightSourceChange: (sourceId: string) => void;
  onRunMappingDiff: () => void;
  onOutputNameChange: (name: string) => void;
  onArtifactOutputDirChange: (path: string) => void;
  onMcapDecodersChange: (value: string) => void;
  onRrdOptimizeProfileChange: (value: string) => void;
  onArtifactValidationChange: (value: string) => void;
  onCatalogEnabledChange: (value: boolean) => void;
  onCatalogDatasetChange: (value: string) => void;
  onCatalogManagedLocalChange: (value: boolean) => void;
  onCatalogServerUrlChange: (value: string) => void;
  onChooseArtifactOutputFolder: () => void;
  onBuildRecording: () => void;
  onOpenInRerun: () => void;
};

export function ImportWorkflowSection({
  selectedTemplateId,
  templateOptions,
  selectedMappingTemplateId,
  mappingTemplates,
  mappingTemplateName,
  source,
  streams,
  mapping,
  schemaProfile,
  mappingValidation,
  mappingConfirmed,
  savedMappingId,
  mappingDiff,
  projectSources,
  diffLeftSourceId,
  diffRightSourceId,
  supportedSemanticTypes,
  timeUnits,
  outputNameRef,
  outputName,
  artifactOutputDir,
  mcapDecoders,
  rrdOptimizeProfile,
  artifactValidation,
  catalogEnabled,
  catalogDataset,
  catalogManagedLocal,
  catalogServerUrl,
  rerun033Available,
  buildResult,
  buildJob,
  isBuildSubmitting,
  previewRows,
  previewText,
  isBusy,
  language,
  errors,
  t,
  onTemplateChange,
  onSelectedMappingTemplateChange,
  onApplyMappingTemplate,
  onMappingTemplateNameChange,
  onCreateMappingTemplate,
  onUpdateTimeline,
  onUpdateMappingStream,
  onApplyMappingSuggestion,
  onSaveMapping,
  onValidateMapping,
  onConfirmMapping,
  onDiffLeftSourceChange,
  onDiffRightSourceChange,
  onRunMappingDiff,
  onOutputNameChange,
  onArtifactOutputDirChange,
  onMcapDecodersChange,
  onRrdOptimizeProfileChange,
  onArtifactValidationChange,
  onCatalogEnabledChange,
  onCatalogDatasetChange,
  onCatalogManagedLocalChange,
  onCatalogServerUrlChange,
  onChooseArtifactOutputFolder,
  onBuildRecording,
  onOpenInRerun
}: ImportWorkflowSectionProps) {
  const [advancedBuildOpen, setAdvancedBuildOpen] = useState(false);
  const buildJobActive = isActiveBuildJob(buildJob);
  const buildControlsLocked = isBusy || isBuildSubmitting || buildJobActive;
  const sourceUsesMcapImporter = source?.type === "mcap" || source?.type === "ros2_db3";
  const buildPercent = Math.round(
    Math.min(1, Math.max(0, buildJob?.progress ?? 0)) * 100
  );
  const workflowSteps: { label: string; state: "done" | "active" | "pending" }[] = [
    { label: t("stepSource"), state: source ? "done" : "active" },
    { label: t("stepSchema"), state: source ? "done" : "pending" },
    {
      label: t("stepMapping"),
      state: mappingConfirmed ? "done" : mapping ? "active" : "pending"
    },
    {
      label: t("stepArtifacts"),
      state: buildResult ? "done" : mappingConfirmed ? "active" : "pending"
    }
  ];

  return (
    <section className="section-stack" id="import">
      <SectionTitle
        eyebrow={t("workspace")}
        title={t("importWorkflow")}
        subtitle={t("importWorkflowSubtitle")}
        action={
          <div className="template-control">
            <Image size={16} />
            <select
              value={selectedTemplateId}
              onChange={(event) => onTemplateChange(event.target.value)}
            >
              {templateOptions.map((template) => (
                <option key={template.template_id} value={template.template_id}>
                  {template.name} ({Math.round(template.score * 100)}%)
                </option>
              ))}
            </select>
          </div>
        }
      />

      <section className="card workflow-card">
        <WorkflowSteps steps={workflowSteps} />
        <div className="workflow-card-copy">
          <strong>{t("importWorkflowPrimary")}</strong>
          <span>{t("importWorkflowPrimaryHint")}</span>
        </div>
      </section>

      <div className="two-column">
        <section className="card">
          <CardHeader icon={<FileSearch size={18} />} title={t("schemaInspector")} />
          {source ? (
            <>
              <dl className="meta-grid">
                <div>
                  <dt>{t("type")}</dt>
                  <dd>{source.type}</dd>
                </div>
                <div>
                  <dt>{t("status")}</dt>
                  <dd>{source.status}</dd>
                </div>
                <div>
                  <dt>{t("size")}</dt>
                  <dd>{source.size_bytes.toLocaleString()} {t("bytes")}</dd>
                </div>
                <div>
                  <dt>{t("streams")}</dt>
                  <dd>{streams.length}</dd>
                </div>
              </dl>
              <StreamTable
                streams={streams}
                labels={{
                  empty: t("noStreams"),
                  name: t("streamName"),
                  semanticType: t("semanticType"),
                  fields: t("fields"),
                  time: t("time"),
                  confidence: t("confidence")
                }}
              />
            </>
          ) : (
            <EmptyState text={t("sourceEmpty")} />
          )}
        </section>

        <section className="card">
          <CardHeader icon={<Save size={18} />} title={t("mappingEditor")} />
          <div className="mapping-template-toolbar inline-panel">
            <div className="inline-panel-title">
              <strong>{t("mappingTemplates")}</strong>
              <span>{t("mappingTemplatesSubtitle")}</span>
            </div>
            <div className="inline-actions">
              <select
                aria-label={t("mappingTemplates")}
                value={selectedMappingTemplateId}
                onChange={(event) => onSelectedMappingTemplateChange(event.target.value)}
              >
                <option value="">{t("automaticMapping")}</option>
                {mappingTemplates.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} ({item.source_family})
                  </option>
                ))}
              </select>
              <button
                onClick={onApplyMappingTemplate}
                disabled={!source || !selectedMappingTemplateId || isBusy}
              >
                {t("applyMappingTemplate")}
              </button>
              <input
                aria-label={t("mappingTemplateName")}
                value={mappingTemplateName}
                onChange={(event) => onMappingTemplateNameChange(event.target.value)}
                placeholder={t("mappingTemplateName")}
              />
              <button
                onClick={onCreateMappingTemplate}
                disabled={!mapping || !mappingTemplateName.trim() || isBusy}
              >
                <Save size={16} />
                {t("saveAsMappingTemplate")}
              </button>
            </div>
            <InlineError error={errors.mappingToolbar} t={t} />
          </div>
          {mapping ? (
            <>
              <div className="mapping-meta">
                <span>{mapping.mapping.app_id}</span>
                <span>
                  {mapping.mapping.status} / {mapping.mapping.schema_version === 2 ? "v2" : "v1"}
                </span>
              </div>
              <div className="timeline-editor">
                <label>
                  <span>{t("timeField")}</span>
                  <select
                    value={mapping.mapping.timelines.primary.source_field}
                    onChange={(event) => onUpdateTimeline("source_field", event.target.value)}
                  >
                    <option value="">{t("rowSequence")}</option>
                    {(schemaProfile?.field_names ?? []).map((field) => (
                      <option key={field} value={field}>{field}</option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>{t("timeUnit")}</span>
                  <select
                    value={mapping.mapping.timelines.primary.unit}
                    onChange={(event) => onUpdateTimeline("unit", event.target.value)}
                  >
                    {timeUnits.map((unit) => (
                      <option key={unit} value={unit}>{unit}</option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>{t("timeSort")}</span>
                  <select
                    value={mapping.mapping.timelines.primary.sort ?? "source"}
                    onChange={(event) => onUpdateTimeline("sort", event.target.value)}
                  >
                    <option value="source">{t("sourceOrder")}</option>
                    <option value="ascending">{t("sortAscending")}</option>
                  </select>
                </label>
                <span className="soft-status">
                  {t("effectiveUnit")}: {mappingValidation?.effective_timeline_unit ?? "pending"}
                </span>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>{t("enabled")}</th>
                      <th>{t("fields")}</th>
                      <th>{t("semanticType")}</th>
                      <th>{t("entityPath")}</th>
                      <th>{t("archetype")}</th>
                      <th>{t("view")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {mapping.mapping.streams.map((stream, index) => (
                      <tr key={stream.stream_id}>
                        <td>
                          <input
                            type="checkbox"
                            checked={stream.enabled}
                            onChange={(event) =>
                              onUpdateMappingStream(index, "enabled", event.target.checked)
                            }
                          />
                        </td>
                        <td>
                          <input
                            value={stream.source_fields.join(", ")}
                            onChange={(event) =>
                              onUpdateMappingStream(index, "source_fields", event.target.value)
                            }
                          />
                          <span className="subline">
                            {stream.rule_key} / {stream.origin}
                          </span>
                        </td>
                        <td>
                          <select
                            value={stream.semantic_type}
                            disabled={source?.type === "mcap" || source?.type === "ros2_db3"}
                            onChange={(event) =>
                              onUpdateMappingStream(index, "semantic_type", event.target.value)
                            }
                          >
                            {supportedSemanticTypes.map((type) => (
                              <option key={type} value={type}>{type}</option>
                            ))}
                            {!supportedSemanticTypes.includes(stream.semantic_type) && (
                              <option value={stream.semantic_type}>{stream.semantic_type}</option>
                            )}
                          </select>
                        </td>
                        <td>
                          <input
                            value={stream.entity_path}
                            disabled={source?.type === "mcap" || source?.type === "ros2_db3"}
                            title={
                              source?.type === "mcap" || source?.type === "ros2_db3"
                                ? t("mcapPathManaged")
                                : undefined
                            }
                            onChange={(event) =>
                              onUpdateMappingStream(index, "entity_path", event.target.value)
                            }
                          />
                          {(source?.type === "mcap" || source?.type === "ros2_db3") && (
                            <span className="subline">{t("mcapPathManaged")}</span>
                          )}
                        </td>
                        <td>{stream.archetype}</td>
                        <td>{stream.view}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {mappingValidation && (
                <div className={`validation-panel ${mappingValidation.valid ? "is-valid" : "has-errors"}`}>
                  <div className="validation-summary">
                    <strong>
                      {mappingValidation.valid ? t("mappingValid") : t("mappingInvalid")}
                    </strong>
                    <span>
                      {mappingValidation.summary.errors} {t("errors")} /{" "}
                      {mappingValidation.summary.warnings} {t("warnings")}
                    </span>
                  </div>
                  {mappingValidation.issues.map((issue, index) => (
                    <MappingIssueCard
                      key={`${issue.code}-${issue.stream_id ?? issue.field ?? index}-${index}`}
                      issue={issue}
                      language={language}
                      t={t}
                      isBusy={isBusy}
                      onApply={onApplyMappingSuggestion}
                    />
                  ))}
                </div>
              )}
              <div className="actions">
                <button onClick={onSaveMapping} disabled={isBusy || Boolean(savedMappingId)}>
                  <Save size={16} />
                  {savedMappingId ? t("draftSaved") : t("saveDraft")}
                </button>
                <button onClick={onValidateMapping} disabled={isBusy}>
                  <ListChecks size={16} />
                  {t("validateMapping")}
                </button>
                <button
                  className="button-primary"
                  onClick={onConfirmMapping}
                  disabled={isBusy || Boolean(mappingValidation && !mappingValidation.valid)}
                >
                  <CheckCircle2 size={16} />
                  {mappingConfirmed ? t("mappingConfirmed") : t("confirmMapping")}
                </button>
                <span className={mappingConfirmed ? "success" : "pending"}>
                  {mappingConfirmed ? t("mappingConfirmed") : t("mappingDraft")}
                </span>
              </div>
              <InlineError error={errors.mapping} t={t} />
            </>
          ) : (
            <EmptyState text={t("mappingEmpty")} />
          )}
        </section>
      </div>

      <section className="card">
        <CardHeader
          icon={<Activity size={18} />}
          title={t("mappingDiff")}
          subtitle={t("mappingDiffSubtitle")}
        />
        <div className="diff-controls">
          <select
            value={diffLeftSourceId}
            onChange={(event) => onDiffLeftSourceChange(event.target.value)}
          >
            <option value="">{t("leftSource")}</option>
            {projectSources.map((item) => (
              <option key={item.id} value={item.id}>{item.id} / {item.type}</option>
            ))}
          </select>
          <select
            value={diffRightSourceId}
            onChange={(event) => onDiffRightSourceChange(event.target.value)}
          >
            <option value="">{t("rightSource")}</option>
            {projectSources.map((item) => (
              <option key={item.id} value={item.id}>{item.id} / {item.type}</option>
            ))}
          </select>
          <button
            onClick={onRunMappingDiff}
            disabled={
              isBusy ||
              !selectedMappingTemplateId ||
              !diffLeftSourceId ||
              !diffRightSourceId ||
              diffLeftSourceId === diffRightSourceId
            }
          >
            {t("compareMappings")}
          </button>
        </div>
        <InlineError error={errors.mappingDiff} t={t} />
        {mappingDiff ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t("rule")}</th>
                  <th>{t("status")}</th>
                  <th>{t("changes")}</th>
                  <th>{t("leftSource")}</th>
                  <th>{t("rightSource")}</th>
                </tr>
              </thead>
              <tbody>
                {mappingDiff.rows.map((row) => (
                  <tr key={row.rule_key}>
                    <td>{row.rule_key}</td>
                    <td>{row.status}</td>
                    <td>{row.changes.join(", ") || "-"}</td>
                    <td>{row.left?.source_fields.join(", ") || "-"}</td>
                    <td>{row.right?.source_fields.join(", ") || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState text={t("mappingDiffEmpty")} />
        )}
      </section>

      <div className="two-column balanced">
        <section className="card">
          <CardHeader icon={<Play size={18} />} title={t("conversionJob")} />
          <div className="build-row">
            <input
              ref={outputNameRef}
              aria-describedby={errors.build ? "build-error" : undefined}
              aria-invalid={Boolean(errors.build)}
              value={outputName}
              onChange={(event) => onOutputNameChange(event.target.value)}
              disabled={buildControlsLocked}
            />
            <button
              className="button-primary"
              disabled={buildControlsLocked || !mappingConfirmed}
              onClick={onBuildRecording}
            >
              {isBuildSubmitting || buildJobActive ? (
                <LoaderCircle className="build-status-spinner" size={16} />
              ) : (
                <Play size={16} />
              )}
              {isBuildSubmitting
                ? t("buildSubmitting")
                : buildJobActive
                  ? `${t("buildRunning")} ${buildPercent}%`
                  : t("buildArtifacts")}
            </button>
            <button
              disabled={!buildResult || buildControlsLocked}
              onClick={onOpenInRerun}
            >
              <ExternalLink size={16} />
              {t("openInRerun")}
            </button>
          </div>
          <div className="artifact-output-control">
            <label>
              <span>{t("artifactOutputPath")}</span>
              <input
                placeholder={t("artifactOutputPathPlaceholder")}
                value={artifactOutputDir}
                onChange={(event) => onArtifactOutputDirChange(event.target.value)}
                disabled={buildControlsLocked}
              />
            </label>
            <button
              type="button"
              onClick={onChooseArtifactOutputFolder}
              disabled={buildControlsLocked}
            >
              <FolderOpen size={16} />
              {t("selectArtifactFolder")}
            </button>
          </div>
          <p className="field-hint">{t("artifactOutputPathHint")}</p>
          <details
            className="advanced-build-details"
            open={advancedBuildOpen}
            onToggle={(event) => setAdvancedBuildOpen(event.currentTarget.open)}
          >
            <summary>
              <SlidersHorizontal size={16} />
              <span>{t("advancedBuildOptions")}</span>
            </summary>
            <div className="advanced-build-options">
              {sourceUsesMcapImporter && (
                <label>
                  <span>{t("mcapDecoders")}</span>
                  <input
                    placeholder={t("mcapDecodersPlaceholder")}
                    value={mcapDecoders}
                    onChange={(event) => onMcapDecodersChange(event.target.value)}
                    disabled={buildControlsLocked || !rerun033Available}
                  />
                </label>
              )}
              <label>
                <span>{t("rrdOptimizeProfile")}</span>
                <select
                  value={rrdOptimizeProfile}
                  onChange={(event) => onRrdOptimizeProfileChange(event.target.value)}
                  disabled={buildControlsLocked || !rerun033Available}
                >
                  <option value="none">{t("none")}</option>
                  <option value="live">live</option>
                  <option value="object-store">object-store</option>
                </select>
              </label>
              <label>
                <span>{t("artifactValidation")}</span>
                <select
                  value={artifactValidation}
                  onChange={(event) => onArtifactValidationChange(event.target.value)}
                  disabled={buildControlsLocked || !rerun033Available}
                >
                  <option value="basic">basic</option>
                  <option value="verify">verify</option>
                  <option value="strict">strict</option>
                </select>
              </label>
              <label className="checkbox-line">
                <input
                  type="checkbox"
                  checked={catalogEnabled}
                  onChange={(event) => onCatalogEnabledChange(event.target.checked)}
                  disabled={buildControlsLocked || !rerun033Available}
                />
                <span>{t("catalogRegistration")}</span>
              </label>
              {catalogEnabled && (
                <>
                  <label>
                    <span>{t("catalogDataset")}</span>
                    <input
                      value={catalogDataset}
                      onChange={(event) => onCatalogDatasetChange(event.target.value)}
                      disabled={buildControlsLocked || !rerun033Available}
                    />
                  </label>
                  <label className="checkbox-line">
                    <input
                      type="checkbox"
                      checked={catalogManagedLocal}
                      onChange={(event) => onCatalogManagedLocalChange(event.target.checked)}
                      disabled={buildControlsLocked || !rerun033Available}
                    />
                    <span>{t("managedLocalCatalog")}</span>
                  </label>
                  {!catalogManagedLocal && (
                    <label>
                      <span>{t("catalogServerUrl")}</span>
                      <input
                        value={catalogServerUrl}
                        onChange={(event) => onCatalogServerUrlChange(event.target.value)}
                        disabled={buildControlsLocked || !rerun033Available}
                        placeholder="rerun+http://127.0.0.1:51234"
                      />
                    </label>
                  )}
                </>
              )}
              {!rerun033Available && (
                <p className="field-hint">{t("rerun033Unavailable")}</p>
              )}
            </div>
          </details>
          <BuildJobStatus job={buildJob} isSubmitting={isBuildSubmitting} t={t} />
          <InlineError id="build-error" error={errors.build} t={t} />
          {buildResult ? (
            <dl className="artifact-list">
              <div>
                <dt>{t("recording")}</dt>
                <dd>{buildResult.recording_path}</dd>
              </div>
              <div>
                <dt>{t("blueprint")}</dt>
                <dd>{buildResult.blueprint_path}</dd>
              </div>
              {buildResult.artifact_info ? (
                <>
                  <div>
                    <dt>{t("artifactStatus")}</dt>
                    <dd>{t("ready")}</dd>
                  </div>
                  <div>
                    <dt>{t("artifactSizes")}</dt>
                    <dd>
                      {formatBytes(buildResult.artifact_info.recording_size_bytes)} /{" "}
                      {formatBytes(buildResult.artifact_info.blueprint_size_bytes)}
                    </dd>
                  </div>
                  <div>
                    <dt>{t("converter")}</dt>
                    <dd>{buildResult.artifact_info.converter}</dd>
                  </div>
                  <div>
                    <dt>{t("artifactValidation")}</dt>
                    <dd>{buildResult.artifact_info.artifact_validation ?? "basic"}</dd>
                  </div>
                  <div>
                    <dt>{t("rrdOptimizeProfile")}</dt>
                    <dd>{buildResult.artifact_info.rrd_optimize_profile ?? "none"}</dd>
                  </div>
                  {buildResult.artifact_info.catalog_registration?.enabled ? (
                    <div>
                      <dt>{t("catalogRegistration")}</dt>
                      <dd>{buildResult.artifact_info.catalog_registration.status}</dd>
                    </div>
                  ) : null}
                </>
              ) : null}
              <div>
                <dt>{t("job")}</dt>
                <dd>
                  {buildResult.job_id} / {buildResult.status}
                </dd>
              </div>
            </dl>
          ) : !isBuildSubmitting && !buildJob ? (
            <EmptyState text={t("buildEmpty")} />
          ) : null}
        </section>

        <section className="card">
          <CardHeader icon={<FileSearch size={18} />} title={t("preview")} />
          {previewText ? (
            <>
              <PreviewVisuals schemaProfile={schemaProfile} rows={previewRows} t={t} />
              <pre className="preview">{previewText}</pre>
            </>
          ) : (
            <EmptyState text={t("previewEmpty")} />
          )}
        </section>
      </div>
    </section>
  );
}

function PreviewVisuals({
  schemaProfile,
  rows,
  t
}: {
  schemaProfile: SchemaProfile | null;
  rows: Record<string, unknown>[];
  t: Translate;
}) {
  const fields = schemaProfile?.fields ?? [];
  const missingFields = fields
    .filter((field) => typeof field.null_ratio === "number" && field.null_ratio > 0)
    .slice(0, 5);
  const numericSeries = firstNumericSeries(rows);
  const stateCounts = firstStateCounts(rows, numericSeries?.field);
  return (
    <div className="preview-visuals">
      <div className="preview-panel">
        <strong>{t("missingValues")}</strong>
        {missingFields.length ? (
          <div className="mini-bars">
            {missingFields.map((field) => (
              <div className="mini-bar-row" key={field.name}>
                <span>{field.name}</span>
                <div>
                  <i style={{ width: `${Math.min(100, field.null_ratio * 100)}%` }} />
                </div>
                <em>{Math.round(field.null_ratio * 100)}%</em>
              </div>
            ))}
          </div>
        ) : (
          <small>{t("noMissingPreview")}</small>
        )}
      </div>
      <div className="preview-panel">
        <strong>{t("numericTrend")}</strong>
        {numericSeries ? (
          <div className="sparkline" aria-label={numericSeries.field}>
            {numericSeries.values.map((value, index) => (
              <i
                key={`${numericSeries.field}-${index}`}
                style={{ height: `${scaledHeight(value, numericSeries.values)}%` }}
              />
            ))}
          </div>
        ) : (
          <small>{t("noNumericPreview")}</small>
        )}
      </div>
      <div className="preview-panel">
        <strong>{t("stateFrequency")}</strong>
        {stateCounts ? (
          <div className="mini-bars">
            {stateCounts.values.map(([value, count]) => (
              <div className="mini-bar-row" key={value}>
                <span>{value}</span>
                <div>
                  <i style={{ width: `${Math.max(8, (count / stateCounts.max) * 100)}%` }} />
                </div>
                <em>{count}</em>
              </div>
            ))}
          </div>
        ) : (
          <small>{t("noStatePreview")}</small>
        )}
      </div>
    </div>
  );
}

function firstNumericSeries(rows: Record<string, unknown>[]) {
  if (!rows.length) return null;
  for (const field of Object.keys(rows[0])) {
    const values = rows
      .map((row) => row[field])
      .filter((value): value is number => typeof value === "number" && Number.isFinite(value));
    if (values.length >= 2) return { field, values };
  }
  return null;
}

function firstStateCounts(rows: Record<string, unknown>[], excludedField?: string) {
  if (!rows.length) return null;
  for (const field of Object.keys(rows[0])) {
    if (field === excludedField) continue;
    const values = rows
      .map((row) => row[field])
      .filter((value) => typeof value === "string" && value.length > 0)
      .map(String);
    const unique = Array.from(new Set(values));
    if (values.length >= 2 && unique.length > 0 && unique.length <= 8) {
      const counts = unique
        .map((value) => [value, values.filter((item) => item === value).length] as [string, number])
        .sort((left, right) => right[1] - left[1])
        .slice(0, 5);
      return { values: counts, max: Math.max(...counts.map(([, count]) => count)) };
    }
  }
  return null;
}

function scaledHeight(value: number, values: number[]) {
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (max === min) return 60;
  return 20 + ((value - min) / (max - min)) * 80;
}
