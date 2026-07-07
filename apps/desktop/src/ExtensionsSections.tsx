import {
  Ban,
  Database,
  Download,
  FolderOpen,
  ListChecks,
  RefreshCcw,
  Save,
  Settings,
  Upload,
  X
} from "lucide-react";

import type { ApiError } from "./api";
import { languageOptions, type Language, type TranslationKey } from "./i18n";
import type {
  BatchResult,
  BatchSummary,
  JobSettings,
  MappingTemplateItem,
  Plugin,
  Recipe,
  TemplateRegistryItem
} from "./types";
import { DiagnosticLogPaths } from "./DiagnosticLogPaths";
import {
  CardHeader,
  EmptyState,
  InlineError,
  SectionTitle,
  normalizeSourcePathInput,
  renderLimitText
} from "./app-support";

type Translate = (key: TranslationKey) => string;

type ExtensionsSectionsProps = {
  activeSection: string;
  selectedProjectId: string;
  batchPattern: string;
  batchOutputPrefix: string;
  batchStorageMode: "copy" | "reference";
  batchResult: BatchResult | null;
  batches: BatchSummary[];
  selectedBatch: BatchResult | null;
  batchEstimate: string;
  jobSettings: JobSettings;
  pluginPath: string;
  templatePath: string;
  mappingTemplates: MappingTemplateItem[];
  selectedMappingTemplateId: string;
  mappingTemplatePath: string;
  mappingTemplateExportPath: string;
  mappingTemplateJson: string;
  plugins: Plugin[];
  templateRegistry: TemplateRegistryItem[];
  recipes: Recipe[];
  visiblePlugins: Plugin[];
  visibleTemplateRegistry: TemplateRegistryItem[];
  language: Language;
  defaultExportDir: string;
  defaultArtifactDir: string;
  diagnosticLogDir: string;
  desktopLogPath: string;
  backendLogPath: string;
  isBusy: boolean;
  batchError?: ApiError;
  extensionsError?: ApiError;
  mappingTemplatesError?: ApiError;
  settingsError?: ApiError;
  t: Translate;
  onBatchPatternChange: (value: string) => void;
  onBatchOutputPrefixChange: (value: string) => void;
  onBatchStorageModeChange: (value: "copy" | "reference") => void;
  onRunBatch: () => void;
  onEstimateBatch: () => void;
  onSelectBatch: (batchId: string) => void;
  onRetryBatchItem: (batchId: string, itemId: string) => void;
  onCancelBatchItem: (batchId: string, itemId: string) => void;
  onPluginPathChange: (value: string) => void;
  onInstallPlugin: () => void;
  onTemplatePathChange: (value: string) => void;
  onInstallTemplate: () => void;
  onMappingTemplatePathChange: (value: string) => void;
  onImportMappingTemplate: () => void;
  onSelectedMappingTemplateChange: (value: string) => void;
  onMappingTemplateExportPathChange: (value: string) => void;
  onExportMappingTemplate: () => void;
  onDeleteMappingTemplate: () => void;
  onMappingTemplateJsonChange: (value: string) => void;
  onSaveMappingTemplate: () => void;
  onLanguageChange: (value: Language) => void;
  onDefaultExportDirChange: (value: string) => void;
  onChooseExportFolder: () => void;
  onDefaultArtifactDirChange: (value: string) => void;
  onChooseArtifactFolder: () => void;
  onJobSettingsChange: (maxWorkers: number) => void;
};

export function ExtensionsSections(props: ExtensionsSectionsProps) {
  if (props.activeSection === "templates") return <TemplatesSection {...props} />;
  if (props.activeSection === "settings") return <SettingsSection {...props} />;
  return null;
}

function TemplatesSection(props: ExtensionsSectionsProps) {
  return (
    <section className="section-stack" id="templates">
      <SectionTitle
        eyebrow={props.t("workspace")}
        title={props.t("templatesExtensions")}
        subtitle={props.t("templatesExtensionsSubtitle")}
      />
      <div className="two-column balanced">
        <section className="card">
          <CardHeader icon={<FolderOpen size={18} />} title={props.t("batchImport")} />
          <textarea
            placeholder={props.t("batchPlaceholder")}
            value={props.batchPattern}
            onChange={(event) => props.onBatchPatternChange(event.target.value)}
          />
          <div className="inline-actions">
            <input
              value={props.batchOutputPrefix}
              onChange={(event) => props.onBatchOutputPrefixChange(event.target.value)}
            />
            <select
              aria-label={props.t("storageMode")}
              value={props.batchStorageMode}
              onChange={(event) =>
                props.onBatchStorageModeChange(event.target.value as "copy" | "reference")
              }
            >
              <option value="copy">{props.t("storageCopy")}</option>
              <option value="reference">{props.t("storageReference")}</option>
            </select>
            <button
              onClick={props.onRunBatch}
              disabled={!props.selectedProjectId || props.isBusy}
            >
              <Upload size={16} />
              {props.t("runBatch")}
            </button>
            <button
              type="button"
              onClick={props.onEstimateBatch}
              disabled={!props.selectedProjectId || !props.batchPattern.trim() || props.isBusy}
            >
              <Database size={16} />
              {props.t("estimateDisk")}
            </button>
          </div>
          <InlineError error={props.batchError} t={props.t} />
          {props.batchEstimate && (
            <p className="path-line light">
              {props.t("diskEstimate")}: {props.batchEstimate}
            </p>
          )}
          {props.batchResult && (
            <p className="path-line light">
              {props.batchResult.id}: {props.batchResult.succeeded}/{props.batchResult.total} {props.t("succeeded")}
            </p>
          )}
        </section>

        <section className="card">
          <CardHeader
            icon={<Save size={18} />}
            title={props.t("extensionRegistry")}
            subtitle={props.t("extensionRegistrySubtitle")}
          />
          <div className="extension-form">
            <input
              placeholder={props.t("pluginPathPlaceholder")}
              value={props.pluginPath}
              onChange={(event) => props.onPluginPathChange(event.target.value)}
            />
            <button onClick={props.onInstallPlugin} disabled={props.isBusy}>
              <Save size={16} />
              {props.t("installPlugin")}
            </button>
            <input
              placeholder={props.t("templatePathPlaceholder")}
              value={props.templatePath}
              onChange={(event) => props.onTemplatePathChange(event.target.value)}
            />
            <button onClick={props.onInstallTemplate} disabled={props.isBusy}>
              <Save size={16} />
              {props.t("installTemplate")}
            </button>
          </div>
          <InlineError error={props.extensionsError} t={props.t} />
        </section>
      </div>

      <section className="card">
        <CardHeader
          icon={<ListChecks size={18} />}
          title={props.t("batchManagement")}
          subtitle={`${props.batches.length} ${props.t("batches")}`}
        />
        {props.batches.length ? (
          <>
            <div className="batch-manager-controls">
              <select
                aria-label={props.t("batch")}
                value={props.selectedBatch?.id ?? ""}
                onChange={(event) => props.onSelectBatch(event.target.value)}
              >
                <option value="">{props.t("selectBatch")}</option>
                {props.batches.map((batch) => (
                  <option key={batch.id} value={batch.id}>
                    {batch.id} / {batch.status} / {batch.succeeded + batch.failed + batch.cancelled}/{batch.total}
                  </option>
                ))}
              </select>
              {props.selectedBatch && (
                <div className="chip-row">
                  <span className="status-badge neutral">{props.selectedBatch.status}</span>
                  <span className="chip">{props.t("succeeded")}: {props.selectedBatch.succeeded}</span>
                  <span className="chip">{props.t("failed")}: {props.selectedBatch.failed}</span>
                  <span className="chip">{props.t("cancelled")}: {props.selectedBatch.cancelled}</span>
                  {props.selectedBatch.job_id && (
                    <span className="chip">{props.t("job")}: {props.selectedBatch.job_id}</span>
                  )}
                </div>
              )}
            </div>
            {props.selectedBatch ? (
              <div className="table-wrap responsive-table">
                <table>
                  <thead>
                    <tr>
                      <th>{props.t("source")}</th>
                      <th>{props.t("recording")}</th>
                      <th>{props.t("status")}</th>
                      <th>{props.t("attempt")}</th>
                      <th>{props.t("message")}</th>
                      <th>{props.t("action")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {props.selectedBatch.items.map((item) => {
                      const canRetry = item.status === "failed" || item.status === "cancelled";
                      const canCancel = item.status === "pending" || item.status === "running";
                      return (
                        <tr key={item.id}>
                          <td data-label={props.t("source")}>{item.source_path}</td>
                          <td data-label={props.t("recording")}>{item.recording_id ?? "-"}</td>
                          <td data-label={props.t("status")}>{item.status}</td>
                          <td data-label={props.t("attempt")}>{item.attempt}</td>
                          <td data-label={props.t("message")}>{item.error_message ?? "-"}</td>
                          <td data-label={props.t("action")}>
                            <div className="inline-actions compact">
                              <button
                                type="button"
                                disabled={!canRetry || props.isBusy}
                                onClick={() =>
                                  props.onRetryBatchItem(props.selectedBatch!.id, item.id)
                                }
                              >
                                <RefreshCcw size={16} />
                                {props.t("retry")}
                              </button>
                              <button
                                type="button"
                                disabled={!canCancel || props.isBusy}
                                onClick={() =>
                                  props.onCancelBatchItem(props.selectedBatch!.id, item.id)
                                }
                              >
                                <Ban size={16} />
                                {props.t("cancelJob")}
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState text={props.t("selectBatch")} />
            )}
          </>
        ) : (
          <EmptyState text={props.t("batchEmpty")} />
        )}
      </section>

      <section className="card mapping-template-manager">
        <CardHeader
          icon={<ListChecks size={18} />}
          title={props.t("mappingTemplateRegistry")}
          subtitle={`${props.mappingTemplates.length} ${props.t("mappingTemplates")}`}
        />
        <div className="mapping-template-manager-grid">
          <div className="mapping-template-controls">
            <div className="mapping-template-control-row">
              <input
                placeholder={props.t("mappingTemplatePathPlaceholder")}
                value={props.mappingTemplatePath}
                onChange={(event) => props.onMappingTemplatePathChange(event.target.value)}
              />
              <button onClick={props.onImportMappingTemplate} disabled={props.isBusy}>
                <Upload size={16} />
                {props.t("importMappingTemplate")}
              </button>
            </div>
            <select
              value={props.selectedMappingTemplateId}
              onChange={(event) => props.onSelectedMappingTemplateChange(event.target.value)}
            >
              <option value="">{props.t("selectMappingTemplate")}</option>
              {props.mappingTemplates.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} / {item.source_family}
                </option>
              ))}
            </select>
            <div className="mapping-template-control-row">
              <input
                placeholder={props.t("mappingTemplateExportPath")}
                value={props.mappingTemplateExportPath}
                onChange={(event) => props.onMappingTemplateExportPathChange(event.target.value)}
              />
              <button
                onClick={props.onExportMappingTemplate}
                disabled={!props.selectedMappingTemplateId || props.isBusy}
              >
                <Download size={16} />
                {props.t("exportMappingTemplate")}
              </button>
              <button
                className="button-danger"
                onClick={props.onDeleteMappingTemplate}
                disabled={!props.selectedMappingTemplateId || props.isBusy}
              >
                <X size={16} />
                {props.t("deleteMappingTemplate")}
              </button>
            </div>
          </div>
          <div className="mapping-template-rules">
            <label className="field-label">{props.t("mappingTemplateRules")}</label>
            <textarea
              aria-describedby={
                props.mappingTemplatesError ? "mapping-template-error" : undefined
              }
              aria-invalid={Boolean(props.mappingTemplatesError)}
              className="mapping-template-json"
              value={props.mappingTemplateJson}
              onChange={(event) => props.onMappingTemplateJsonChange(event.target.value)}
              placeholder={props.t("mappingTemplateRulesHint")}
            />
            <div className="actions">
              <button
                onClick={props.onSaveMappingTemplate}
                disabled={
                  !props.selectedMappingTemplateId ||
                  !props.mappingTemplateJson.trim() ||
                  props.isBusy
                }
              >
                <Save size={16} />
                {props.t("saveTemplateRules")}
              </button>
            </div>
          </div>
        </div>
        <InlineError
          id="mapping-template-error"
          error={props.mappingTemplatesError}
          t={props.t}
        />
      </section>

      <section className="card registry-card">
        <CardHeader
          icon={<Database size={18} />}
          title={props.t("pluginTemplateRegistry")}
          subtitle={`${props.plugins.length} ${props.t("plugins")} / ${props.templateRegistry.length} ${props.t("templates")}`}
        />
        <div className="table-wrap responsive-table">
          <table>
            <thead>
              <tr>
                <th>{props.t("kind")}</th>
                <th>{props.t("name")}</th>
                <th>{props.t("version")}</th>
                <th>{props.t("status")}</th>
                <th>{props.t("pathApp")}</th>
              </tr>
            </thead>
            <tbody>
              {props.visiblePlugins.map((plugin) => (
                <tr key={`plugin-${plugin.id}`}>
                  <td data-label={props.t("kind")}>{props.t("plugin")}</td>
                  <td data-label={props.t("name")}>{plugin.name}</td>
                  <td data-label={props.t("version")}>{plugin.version}</td>
                  <td data-label={props.t("status")}>{plugin.status}</td>
                  <td data-label={props.t("pathApp")}>{plugin.path}</td>
                </tr>
              ))}
              {props.visibleTemplateRegistry.map((template) => (
                <tr key={`template-${template.id}`}>
                  <td data-label={props.t("kind")}>{props.t("template")}</td>
                  <td data-label={props.t("name")}>{template.name}</td>
                  <td data-label={props.t("version")}>{template.version}</td>
                  <td data-label={props.t("status")}>
                    {template.enabled ? props.t("enabled") : props.t("disabled")}
                  </td>
                  <td data-label={props.t("pathApp")}>{template.app_id}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {props.visiblePlugins.length + props.visibleTemplateRegistry.length <
          props.plugins.length + props.templateRegistry.length && (
          <p className="render-limit-note">
            {renderLimitText(
              props.language,
              props.visiblePlugins.length + props.visibleTemplateRegistry.length,
              props.plugins.length + props.templateRegistry.length
            )}
          </p>
        )}
        {!props.plugins.length && !props.templateRegistry.length && (
          <EmptyState text={props.t("registryEmpty")} />
        )}
      </section>

      <section className="card">
        <CardHeader
          icon={<ListChecks size={18} />}
          title={props.t("recipeRegistry")}
          subtitle={`${props.recipes.length} ${props.t("recipes")}`}
        />
        {props.recipes.length ? (
          <div className="recipe-grid">
            {props.recipes.map((recipe) => (
              <article className="recipe-card" key={recipe.id}>
                <div>
                  <strong>{recipe.name}</strong>
                  <span>{recipe.source_family} / {recipe.visual_template_id}</span>
                </div>
                <p>{recipe.description}</p>
                <div className="chip-row">
                  <span className="chip">{recipe.diagnostic_preset}</span>
                  {recipe.recommended_queries.map((query) => (
                    <span className="chip" key={query}>{query}</span>
                  ))}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState text={props.t("recipeRegistryEmpty")} />
        )}
      </section>
    </section>
  );
}

function SettingsSection(props: ExtensionsSectionsProps) {
  return (
    <section className="section-stack" id="settings">
      <SectionTitle
        eyebrow={props.t("workspace")}
        title={props.t("settings")}
        subtitle={props.t("settingsSubtitle")}
      />
      <section className="card">
        <CardHeader
          icon={<Settings size={18} />}
          title={props.t("preferences")}
          subtitle={props.t("preferencesSubtitle")}
        />
        <div className="settings-block">
          <div>
            <strong>{props.t("language")}</strong>
            <span>{props.t("languageSubtitle")}</span>
          </div>
          <div className="segmented-control" role="group" aria-label={props.t("language")}>
            {languageOptions.map((option) => (
              <button
                key={option.value}
                className={props.language === option.value ? "is-selected" : ""}
                onClick={() => props.onLanguageChange(option.value)}
                type="button"
              >
                {option.value === "zh" ? props.t("chinese") : props.t("english")}
              </button>
            ))}
          </div>
        </div>
        <div className="settings-block">
          <div>
            <strong>{props.t("jobConcurrency")}</strong>
            <span>{props.t("jobConcurrencySubtitle")}</span>
          </div>
          <select
            aria-label={props.t("maxWorkers")}
            value={props.jobSettings.max_workers}
            onChange={(event) => props.onJobSettingsChange(Number(event.target.value))}
          >
            {[1, 2, 3, 4].map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </div>
        <div className="settings-block vertical">
          <div>
            <strong>{props.t("defaultExportPath")}</strong>
            <span>{props.t("defaultExportPathSubtitle")}</span>
          </div>
          <div className="settings-path-control">
            <input
              placeholder={props.t("exportPathPlaceholder")}
              value={props.defaultExportDir}
              onChange={(event) => props.onDefaultExportDirChange(event.target.value)}
              onBlur={(event) =>
                props.onDefaultExportDirChange(normalizeSourcePathInput(event.target.value))
              }
            />
            <button
              type="button"
              onClick={props.onChooseExportFolder}
              disabled={props.isBusy}
            >
              <FolderOpen size={16} />
              {props.t("selectExportFolder")}
            </button>
          </div>
          <InlineError error={props.settingsError} t={props.t} />
        </div>
        <div className="settings-block vertical">
          <div>
            <strong>{props.t("defaultArtifactPath")}</strong>
            <span>{props.t("defaultArtifactPathSubtitle")}</span>
          </div>
          <div className="settings-path-control">
            <input
              placeholder={props.t("artifactOutputPathPlaceholder")}
              value={props.defaultArtifactDir}
              onChange={(event) => props.onDefaultArtifactDirChange(event.target.value)}
              onBlur={(event) =>
                props.onDefaultArtifactDirChange(
                  normalizeSourcePathInput(event.target.value)
                )
              }
            />
            <button
              type="button"
              onClick={props.onChooseArtifactFolder}
              disabled={props.isBusy}
            >
              <FolderOpen size={16} />
              {props.t("selectArtifactFolder")}
            </button>
          </div>
        </div>
      </section>
      <DiagnosticLogPaths
        logDir={props.diagnosticLogDir}
        desktopLogPath={props.desktopLogPath}
        backendLogPath={props.backendLogPath}
        t={props.t}
      />
    </section>
  );
}
