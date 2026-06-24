import type { RefObject } from "react";
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
  Save
} from "lucide-react";

import { BuildJobStatus, isActiveBuildJob } from "./BuildJobStatus";
import {
  CardHeader,
  EmptyState,
  InlineError,
  MappingIssueCard,
  SectionTitle,
  StreamTable,
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
  buildResult: BuildResult | null;
  buildJob: Job | null;
  isBuildSubmitting: boolean;
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
  buildResult,
  buildJob,
  isBuildSubmitting,
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
  onChooseArtifactOutputFolder,
  onBuildRecording,
  onOpenInRerun
}: ImportWorkflowSectionProps) {
  const buildJobActive = isActiveBuildJob(buildJob);
  const buildControlsLocked = isBusy || isBuildSubmitting || buildJobActive;
  const buildPercent = Math.round(
    Math.min(1, Math.max(0, buildJob?.progress ?? 0)) * 100
  );

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

      <section className="card mapping-template-toolbar">
        <CardHeader
          icon={<ListChecks size={18} />}
          title={t("mappingTemplates")}
          subtitle={t("mappingTemplatesSubtitle")}
        />
        <div className="inline-actions">
          <select
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
            <pre className="preview">{previewText}</pre>
          ) : (
            <EmptyState text={t("previewEmpty")} />
          )}
        </section>
      </div>
    </section>
  );
}
