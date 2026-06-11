import { memo, type DragEvent, type ReactNode, useEffect, useMemo, useState } from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Command,
  Database,
  Download,
  ExternalLink,
  FileSearch,
  FolderOpen,
  FolderPlus,
  Image,
  LayoutDashboard,
  ListChecks,
  Play,
  RefreshCcw,
  Save,
  Search,
  Settings,
  Tags,
  Upload,
  Zap
} from "lucide-react";

import { api } from "./api";
import {
  createTranslator,
  getInitialLanguage,
  languageOptions,
  saveLanguage,
  type Language,
  type TranslationKey
} from "./i18n";
import type {
  BatchResult,
  BuildResult,
  Job,
  MappingPayload,
  MappingDiff,
  MappingSuggestion,
  MappingTemplateItem,
  MappingValidation,
  MappingValidationIssue,
  Plugin,
  Project,
  ProjectExportResult,
  QueryResult,
  QueryTemplate,
  Recording,
  Source,
  SchemaProfile,
  StreamInfo,
  TemplateMatch,
  TemplateRegistryItem
} from "./types";

const supportedFormats = ["CSV", "JSONL", "Images", "PLY", "PCD", "NPZ", "MCAP", "ROS2"];
const thresholdTemplates = new Set(["low_battery", "detection_failure"]);
const TABLE_RENDER_LIMIT = 100;
const DEFAULT_EXPORT_DIR_KEY = "datascope.defaultExportDir";
const semanticTypesByFamily: Record<string, string[]> = {
  tabular: [
    "scalar",
    "scalar_group",
    "state",
    "text_log",
    "points2d",
    "points3d",
    "trajectory3d",
    "boxes2d",
    "transform3d"
  ],
  image_folder: ["image", "boxes2d", "points2d", "segmentation", "scalar"],
  point_cloud: ["points3d"],
  mcap: [
    "mcap",
    "image",
    "points3d",
    "transform3d",
    "trajectory3d",
    "asset3d",
    "scalar_group",
    "text_log"
  ]
};
const timeUnits = ["auto", "relative_s", "unix_s", "unix_ms", "unix_us", "unix_ns", "datetime"];

function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectName, setProjectName] = useState("Sensor Run");
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [sourcePath, setSourcePath] = useState("");
  const [outputName, setOutputName] = useState("run_001");
  const [source, setSource] = useState<Source | null>(null);
  const [streams, setStreams] = useState<StreamInfo[]>([]);
  const [mapping, setMapping] = useState<MappingPayload | null>(null);
  const [schemaProfile, setSchemaProfile] = useState<SchemaProfile | null>(null);
  const [mappingValidation, setMappingValidation] = useState<MappingValidation | null>(null);
  const [mappingConfirmed, setMappingConfirmed] = useState(false);
  const [projectSources, setProjectSources] = useState<Source[]>([]);
  const [mappingTemplates, setMappingTemplates] = useState<MappingTemplateItem[]>([]);
  const [selectedMappingTemplateId, setSelectedMappingTemplateId] = useState("");
  const [mappingTemplateName, setMappingTemplateName] = useState("My Mapping Template");
  const [mappingTemplatePath, setMappingTemplatePath] = useState("");
  const [mappingTemplateJson, setMappingTemplateJson] = useState("");
  const [mappingTemplateExportPath, setMappingTemplateExportPath] = useState("");
  const [diffLeftSourceId, setDiffLeftSourceId] = useState("");
  const [diffRightSourceId, setDiffRightSourceId] = useState("");
  const [mappingDiff, setMappingDiff] = useState<MappingDiff | null>(null);
  const [templates, setTemplates] = useState<TemplateMatch[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState("sensor_monitor");
  const [savedMappingId, setSavedMappingId] = useState("");
  const [buildResult, setBuildResult] = useState<BuildResult | null>(null);
  const [previewRows, setPreviewRows] = useState<Record<string, unknown>[]>([]);
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [plugins, setPlugins] = useState<Plugin[]>([]);
  const [templateRegistry, setTemplateRegistry] = useState<TemplateRegistryItem[]>([]);
  const [queryTemplates, setQueryTemplates] = useState<QueryTemplate[]>([]);
  const [selectedQueryTemplate, setSelectedQueryTemplate] = useState("low_battery");
  const [selectedQueryRecording, setSelectedQueryRecording] = useState("");
  const [queryThreshold, setQueryThreshold] = useState("0.5");
  const [queryResult, setQueryResult] = useState<QueryResult | null>(null);
  const [compareRecordingIds, setCompareRecordingIds] = useState("");
  const [compareMetric, setCompareMetric] = useState("battery");
  const [compareResult, setCompareResult] = useState<QueryResult | null>(null);
  const [batchPattern, setBatchPattern] = useState("");
  const [batchOutputPrefix, setBatchOutputPrefix] = useState("batch_run");
  const [batchResult, setBatchResult] = useState<BatchResult | null>(null);
  const [pluginPath, setPluginPath] = useState("");
  const [templatePath, setTemplatePath] = useState("");
  const [exportPath, setExportPath] = useState("");
  const [projectExport, setProjectExport] = useState<ProjectExportResult | null>(null);
  const [openedPackagePath, setOpenedPackagePath] = useState("");
  const [defaultExportDir, setDefaultExportDir] = useState(getInitialDefaultExportDir);
  const [tagInput, setTagInput] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [activeSection, setActiveSection] = useState("dashboard");
  const [dragActive, setDragActive] = useState(false);
  const [sourcePickerOpen, setSourcePickerOpen] = useState(false);
  const [language, setLanguage] = useState<Language>(getInitialLanguage);
  const t = useMemo(() => createTranslator(language), [language]);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) ?? null,
    [projects, selectedProjectId]
  );

  const templateOptions = useMemo(
    () =>
      templates.length
        ? templates
        : [{ template_id: "sensor_monitor", name: t("sensorMonitor"), score: 1 }],
    [templates, t]
  );

  const latestRecording = recordings[0] ?? null;
  const latestJob = jobs[0] ?? null;
  const recentRecordings = useMemo(() => recordings.slice(0, 4), [recordings]);
  const visibleRecordings = useMemo(() => recordings.slice(0, TABLE_RENDER_LIMIT), [recordings]);
  const queryRecordingOptions = useMemo(() => recordings.slice(0, TABLE_RENDER_LIMIT), [recordings]);
  const visibleJobs = useMemo(() => jobs.slice(0, 8), [jobs]);
  const visiblePlugins = useMemo(() => plugins.slice(0, TABLE_RENDER_LIMIT), [plugins]);
  const visibleTemplateRegistry = useMemo(
    () => templateRegistry.slice(0, TABLE_RENDER_LIMIT),
    [templateRegistry]
  );
  const previewText = useMemo(
    () => (previewRows.length ? JSON.stringify(previewRows.slice(0, 8), null, 2) : ""),
    [previewRows]
  );
  const supportedSemanticTypes =
    mappingValidation?.supported_semantic_types ??
    semanticTypesByFamily[schemaProfile?.source_family ?? "tabular"] ??
    semanticTypesByFamily.tabular;
  const isBusy = Boolean(busy);

  useEffect(() => {
    window.scrollTo(0, 0);
    refreshProjects();
    refreshTemplateRegistry();
  }, []);

  useEffect(() => {
    if (selectedProjectId) {
      refreshProjectData(selectedProjectId, activeSection === "recordings");
    }
  }, [selectedProjectId]);

  useEffect(() => {
    if (selectedProjectId && activeSection === "recordings") {
      refreshProjectData(selectedProjectId, true);
    }
    if (activeSection === "templates") {
      refreshExtensionData();
    }
  }, [activeSection]);

  useEffect(() => {
    saveLanguage(language);
  }, [language]);

  useEffect(() => {
    window.localStorage.setItem(DEFAULT_EXPORT_DIR_KEY, defaultExportDir.trim());
  }, [defaultExportDir]);

  useEffect(() => {
    const selected = mappingTemplates.find((item) => item.id === selectedMappingTemplateId);
    setMappingTemplateJson(selected ? JSON.stringify(selected.config, null, 2) : "");
  }, [mappingTemplates, selectedMappingTemplateId]);

  async function run<T>(label: string, task: () => Promise<T>): Promise<T | null> {
    setBusy(label);
    setError("");
    try {
      return await task();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return null;
    } finally {
      setBusy("");
    }
  }

  async function refreshProjects() {
    const result = await run(t("busyRefreshingProjects"), () => api.projects());
    if (result) {
      setProjects(result);
      if (!selectedProjectId && result[0]) {
        setSelectedProjectId(result[0].id);
      }
    }
  }

  async function refreshProjectData(projectId = selectedProjectId, includeQueryTemplates = false) {
    if (!projectId) return;
    const result = await run(t("busyRefreshingWorkspace"), async () => {
      const [recordingRows, jobRows, sourceRows] = await Promise.all([
        api.recordings(projectId),
        api.jobs(projectId),
        api.sources(projectId)
      ]);
      const templatesRows = includeQueryTemplates ? await api.queryTemplates(projectId) : null;
      return { recordingRows, jobRows, sourceRows, templatesRows };
    });
    if (result) {
      setRecordings(result.recordingRows);
      setJobs(result.jobRows);
      setProjectSources(result.sourceRows);
      setDiffLeftSourceId((current) =>
        result.sourceRows.some((item) => item.id === current)
          ? current
          : result.sourceRows[0]?.id || ""
      );
      setDiffRightSourceId((current) =>
        result.sourceRows.some((item) => item.id === current)
          ? current
          : result.sourceRows[1]?.id || ""
      );
      if (result.templatesRows) {
        setQueryTemplates(result.templatesRows);
        if (!result.templatesRows.some((template) => template.template_id === selectedQueryTemplate)) {
          setSelectedQueryTemplate(result.templatesRows[0]?.template_id ?? "low_battery");
        }
      }
    }
  }

  async function refreshTemplateRegistry() {
    const result = await run(t("busyLoadingRegistry"), async () => {
      const [templateRows, mappingTemplateRows] = await Promise.all([
        api.templates(),
        api.mappingTemplates()
      ]);
      return { templateRows, mappingTemplateRows };
    });
    if (result) {
      setTemplateRegistry(result.templateRows);
      setMappingTemplates(result.mappingTemplateRows);
      setSelectedMappingTemplateId((current) => current || result.mappingTemplateRows[0]?.id || "");
    }
  }

  async function refreshExtensionData() {
    const result = await run(t("busyLoadingRegistry"), async () => {
      const [pluginRows, templateRows, mappingTemplateRows] = await Promise.all([
        api.plugins(),
        api.templates(),
        api.mappingTemplates()
      ]);
      return { pluginRows, templateRows, mappingTemplateRows };
    });
    if (result) {
      setPlugins(result.pluginRows);
      setTemplateRegistry(result.templateRows);
      setMappingTemplates(result.mappingTemplateRows);
      setSelectedMappingTemplateId((current) => current || result.mappingTemplateRows[0]?.id || "");
    }
  }

  async function refreshAll() {
    await refreshProjects();
    if (selectedProjectId) await refreshProjectData(selectedProjectId);
    if (activeSection === "templates") {
      await refreshExtensionData();
    } else if (activeSection !== "settings") {
      await refreshTemplateRegistry();
    }
  }

  async function createProject() {
    const result = await run(t("busyCreatingProject"), () => api.createProject(projectName));
    if (result) {
      setProjects((current) => [result, ...current]);
      setSelectedProjectId(result.id);
    }
  }

  async function importAndInspect() {
    const nextSourcePath = normalizeSourcePathInput(sourcePath);
    if (!nextSourcePath) {
      setError(t("errorMissingSourcePath"));
      return;
    }
    if (nextSourcePath !== sourcePath) {
      setSourcePath(nextSourcePath);
    }
    const result = await run(t("busyInspectingSource"), async () => {
      let projectRows = projects;
      let projectForImport = selectedProject;
      let projectIdForImport = selectedProjectId;
      if (!projectIdForImport) {
        const fallbackName = projectName.trim() || "Sensor Run";
        if (!projectRows.length) {
          projectRows = await api.projects();
        }
        projectForImport =
          projectRows.find((project) => project.name === fallbackName) ??
          (await api.createProject(fallbackName));
        projectRows = upsertProject(projectRows, projectForImport);
        projectIdForImport = projectForImport.id;
      }

      const added = await api.addSource(projectIdForImport, nextSourcePath);
      const inspection = await api.inspect(added.id);
      const templateMatches = await api.suggestTemplates(added.id);
      const nextTemplateId = templateMatches[0]?.template_id ?? "sensor_monitor";
      const suggested = await api.suggestMappingForTemplate(added.id, nextTemplateId);
      const savedMapping = await api.saveMapping(added.id, suggested.mapping);
      const mappingPreview = await api.previewMapping(added.id, suggested.mapping);
      return {
        added,
        project: projectForImport,
        projectRows,
        streams: inspection.streams,
        templateMatches,
        nextTemplateId,
        suggested,
        savedMappingId: savedMapping.id,
        previewRows: mappingPreview.preview.rows,
        schemaProfile: mappingPreview.schema_profile,
        validation: mappingPreview.validation
      };
    });
    if (result) {
      setProjects(result.projectRows);
      if (result.project) {
        setSelectedProjectId(result.project.id);
      }
      setSource(result.added);
      setStreams(result.streams);
      setTemplates(result.templateMatches);
      setSelectedTemplateId(result.nextTemplateId);
      setMapping(result.suggested);
      setPreviewRows(result.previewRows);
      setSchemaProfile(result.schemaProfile);
      setMappingValidation(result.validation);
      setSavedMappingId(result.savedMappingId);
      setMappingConfirmed(false);
      setBuildResult(null);
      setActiveSection("import");
    }
  }

  async function saveMapping() {
    if (!source || !mapping) return;
    const saved = await run(t("busySavingMapping"), () => api.saveMapping(source.id, mapping.mapping));
    if (saved) {
      setSavedMappingId(saved.id);
      setMappingConfirmed(false);
      setMapping((current) =>
        current
          ? { mapping: { ...current.mapping, status: "draft" } }
          : current
      );
    }
  }

  async function validateCurrentMapping() {
    if (!source || !mapping) return null;
    const result = await run(t("busyValidatingMapping"), () =>
      api.validateMapping(source.id, mapping.mapping)
    );
    if (result) setMappingValidation(result);
    return result;
  }

  async function confirmCurrentMapping() {
    if (!source || !mapping) return;
    const result = await run(t("busyConfirmingMapping"), async () => {
      const saved = savedMappingId
        ? { id: savedMappingId }
        : await api.saveMapping(source.id, mapping.mapping);
      return api.confirmMapping(saved.id);
    });
    if (result) {
      setSavedMappingId(result.mapping.id);
      setMappingValidation(result.validation);
      setMappingConfirmed(true);
      setMapping((current) =>
        current
          ? {
              mapping: {
                ...current.mapping,
                status: "confirmed",
                timelines: {
                  primary: {
                    ...current.mapping.timelines.primary,
                    effective_unit: result.validation.effective_timeline_unit
                  }
                }
              }
            }
          : current
      );
    }
  }

  async function buildRecording() {
    if (!selectedProject || !source || !mapping) {
      setError(t("errorMappingUnavailable"));
      return;
    }
    if (!mappingConfirmed) {
      setError(t("errorConfirmMappingFirst"));
      return;
    }
    const result = await run(t("busyBuildingRecording"), async () => {
      const mappingId = savedMappingId || (await api.saveMapping(source.id, mapping.mapping)).id;
      const built = await api.build(selectedProject.id, source.id, mappingId, outputName, selectedTemplateId);
      return { built, mappingId };
    });
    if (result) {
      setSavedMappingId(result.mappingId);
      setBuildResult(result.built);
      refreshProjectData(selectedProject.id);
    }
  }

  async function openInRerun() {
    const recordingPath = buildResult?.recording_path ?? latestRecording?.path;
    const blueprintPath = buildResult?.blueprint_path ?? latestRecording?.blueprint_path ?? undefined;
    if (!recordingPath) {
      setError(t("errorNoRecordingToOpen"));
      return;
    }
    await run(t("busyOpeningRerun"), () =>
      api.open(recordingPath, blueprintPath)
    );
  }

  async function openRecording(recording: Recording) {
    await run(t("busyOpeningRerun"), () =>
      api.open(recording.path, recording.blueprint_path ?? undefined)
    );
  }

  function updateMappingStream(
    index: number,
    key: "entity_path" | "semantic_type" | "source_fields" | "enabled",
    value: string | boolean
  ) {
    if (!mapping) return;
    const next = structuredClone(mapping);
    if (key === "source_fields") {
      next.mapping.streams[index].source_fields = String(value)
        .split(",")
        .map((field) => field.trim())
        .filter(Boolean);
      next.mapping.streams[index].match_ambiguous = false;
      next.mapping.streams[index].match_candidates = [];
      next.mapping.streams[index].template_missing_fields = [];
    } else if (key === "enabled") {
      next.mapping.streams[index].enabled = Boolean(value);
    } else {
      next.mapping.streams[index][key] = String(value);
      if (key === "semantic_type") {
        const derived = derivedMappingFields(String(value));
        next.mapping.streams[index].archetype = derived.archetype;
        next.mapping.streams[index].view = derived.view;
      }
    }
    next.mapping.status = "draft";
    setMapping(next);
    setSavedMappingId("");
    setMappingConfirmed(false);
    setMappingValidation(null);
  }

  function updateTimeline(key: "source_field" | "unit" | "sort", value: string) {
    if (!mapping) return;
    const next = structuredClone(mapping);
    if (key === "sort") {
      next.mapping.timelines.primary.sort = value as "source" | "ascending";
    } else {
      next.mapping.timelines.primary[key] = value;
    }
    if (key === "source_field") next.mapping.timelines.primary.name = value;
    next.mapping.timelines.primary.effective_unit = null;
    next.mapping.status = "draft";
    setMapping(next);
    setSavedMappingId("");
    setMappingConfirmed(false);
    setMappingValidation(null);
  }

  async function applyMappingSuggestion(suggestion: MappingSuggestion) {
    if (!source || !mapping) return;
    const next = structuredClone(mapping);
    const params = suggestion.params;
    const streamIndex = params.stream_id
      ? next.mapping.streams.findIndex((stream) => stream.stream_id === params.stream_id)
      : -1;

    switch (suggestion.action) {
      case "set_timeline_field":
        next.mapping.timelines.primary.source_field = params.field ?? "";
        next.mapping.timelines.primary.name = params.field ?? "";
        next.mapping.timelines.primary.effective_unit = null;
        break;
      case "set_timeline_unit":
        if (params.unit) next.mapping.timelines.primary.unit = params.unit;
        next.mapping.timelines.primary.effective_unit = null;
        break;
      case "set_timeline_sort":
        next.mapping.timelines.primary.sort = params.sort ?? "source";
        break;
      case "replace_source_field":
        if (streamIndex >= 0 && params.new_field) {
          const stream = next.mapping.streams[streamIndex];
          const fields = stream.source_fields;
          const oldIndex = fields.indexOf(params.old_field ?? "");
          if (oldIndex >= 0) {
            fields[oldIndex] = params.new_field;
          } else if (!fields.includes(params.new_field)) {
            fields.push(params.new_field);
          }
          stream.template_missing_fields = (stream.template_missing_fields ?? []).filter(
            (field) => field !== params.old_field
          );
          stream.match_candidates = (stream.match_candidates ?? []).filter(
            (match) => match.field !== params.old_field
          );
          stream.match_ambiguous = Boolean(stream.match_candidates.length);
        }
        break;
      case "set_source_fields":
        if (streamIndex >= 0) {
          next.mapping.streams[streamIndex].source_fields = params.fields ?? [];
        }
        break;
      case "set_entity_path":
        if (streamIndex >= 0 && params.entity_path) {
          next.mapping.streams[streamIndex].entity_path = params.entity_path;
        }
        break;
      case "set_semantic_type":
        if (streamIndex >= 0 && params.semantic_type) {
          const stream = next.mapping.streams[streamIndex];
          const derived = derivedMappingFields(params.semantic_type);
          stream.semantic_type = params.semantic_type;
          stream.archetype = derived.archetype;
          stream.view = derived.view;
        }
        break;
      case "set_stream_enabled":
        if (streamIndex >= 0 && typeof params.enabled === "boolean") {
          next.mapping.streams[streamIndex].enabled = params.enabled;
        }
        break;
    }

    next.mapping.status = "draft";
    setMapping(next);
    setSavedMappingId("");
    setMappingConfirmed(false);
    setMappingValidation(null);
    const result = await run(t("busyApplyingMappingFix"), () =>
      api.validateMapping(source.id, next.mapping)
    );
    if (result) setMappingValidation(result);
  }

  async function changeTemplate(templateId: string) {
    setSelectedTemplateId(templateId);
    setSavedMappingId("");
    if (!source) return;
    const result = await run(t("busySuggestingMapping"), async () => {
      const suggested = await api.suggestMappingForTemplate(source.id, templateId);
      const savedMapping = await api.saveMapping(source.id, suggested.mapping);
      const validation = await api.validateMapping(source.id, suggested.mapping);
      return { suggested, savedMappingId: savedMapping.id, validation };
    });
    if (result) {
      setMapping(result.suggested);
      setSavedMappingId(result.savedMappingId);
      setMappingValidation(result.validation);
      setMappingConfirmed(false);
    }
  }

  async function applySelectedMappingTemplate() {
    if (!source || !selectedMappingTemplateId) return;
    const result = await run(t("busyApplyingMappingTemplate"), () =>
      api.applyMappingTemplate(selectedMappingTemplateId, source.id)
    );
    if (result) {
      setMapping({ mapping: result.mapping });
      setMappingValidation(result.validation);
      setSelectedTemplateId(result.mapping.template_id || selectedTemplateId);
      setSavedMappingId("");
      setMappingConfirmed(false);
    }
  }

  async function createCurrentMappingTemplate() {
    if (!source || !mapping) return;
    const result = await run(t("busySavingMappingTemplate"), async () => {
      const saved = savedMappingId
        ? { id: savedMappingId }
        : await api.saveMapping(source.id, mapping.mapping);
      const template = await api.createMappingTemplate(
        mappingTemplateName.trim(),
        source.id,
        saved.id
      );
      return { template, mappingId: saved.id };
    });
    if (result) {
      setSavedMappingId(result.mappingId);
      await refreshTemplateRegistry();
      setSelectedMappingTemplateId(result.template.id);
    }
  }

  async function importMappingTemplate() {
    if (!mappingTemplatePath.trim()) return;
    const result = await run(t("busyImportingMappingTemplate"), () =>
      api.importMappingTemplate(mappingTemplatePath.trim())
    );
    if (result) {
      setMappingTemplatePath("");
      await refreshTemplateRegistry();
      setSelectedMappingTemplateId(result.id);
    }
  }

  async function saveMappingTemplateConfig() {
    if (!selectedMappingTemplateId || !mappingTemplateJson.trim()) return;
    const result = await run(t("busySavingMappingTemplate"), () =>
      api.saveMappingTemplate(selectedMappingTemplateId, JSON.parse(mappingTemplateJson))
    );
    if (result) await refreshTemplateRegistry();
  }

  async function exportSelectedMappingTemplate() {
    if (!selectedMappingTemplateId) return;
    const result = await run(t("busyExportingMappingTemplate"), () =>
      api.exportMappingTemplate(
        selectedMappingTemplateId,
        mappingTemplateExportPath.trim() || undefined
      )
    );
    if (result) setMappingTemplateExportPath(result.path);
  }

  async function runMappingDiff() {
    if (
      !selectedProjectId ||
      !selectedMappingTemplateId ||
      !diffLeftSourceId ||
      !diffRightSourceId
    ) return;
    const result = await run(t("busyDiffingMapping"), () =>
      api.diffMappingTemplate(
        selectedProjectId,
        selectedMappingTemplateId,
        diffLeftSourceId,
        diffRightSourceId
      )
    );
    if (result) setMappingDiff(result);
  }

  async function addTagToRecording(recordingId: string) {
    const tag = tagInput.trim();
    if (!tag) return;
    const updated = await run(t("busyUpdatingTag"), () =>
      api.patchRecording(recordingId, { add_tags: [tag] })
    );
    if (updated) {
      setTagInput("");
      refreshProjectData(updated.project_id);
    }
  }

  async function runQuery() {
    if (!selectedProjectId) return;
    const params = thresholdTemplates.has(selectedQueryTemplate)
      ? { threshold: Number(queryThreshold) }
      : {};
    const result = await run(t("busyRunningQuery"), () =>
      api.query(
        selectedProjectId,
        selectedQueryTemplate,
        selectedQueryRecording ? [selectedQueryRecording] : [],
        params
      )
    );
    if (result) setQueryResult(result);
  }

  async function exportQuery() {
    if (!selectedProjectId) return;
    const params = thresholdTemplates.has(selectedQueryTemplate)
      ? { threshold: Number(queryThreshold) }
      : {};
    const result = await run(t("busyExportingQuery"), () =>
      api.exportQuery(
        selectedProjectId,
        selectedQueryTemplate,
        selectedQueryRecording ? [selectedQueryRecording] : [],
        params,
        "csv"
      )
    );
    if (result) setExportPath(result.path);
  }

  async function installPlugin() {
    if (!pluginPath.trim()) return;
    const result = await run(t("busyInstallingPlugin"), () => api.installPlugin(pluginPath.trim()));
    if (result) {
      setPluginPath("");
      refreshExtensionData();
    }
  }

  async function installTemplate() {
    if (!templatePath.trim()) return;
    const result = await run(t("busyInstallingTemplate"), () => api.installTemplate(templatePath.trim()));
    if (result) {
      setTemplatePath("");
      refreshExtensionData();
    }
  }

  async function runBatchImport() {
    if (!selectedProjectId || !batchPattern.trim()) return;
    const patterns = batchPattern
      .split("\n")
      .map((value) => value.trim())
      .filter(Boolean);
    const result = await run(t("busyRunningBatch"), () =>
      api.batchImport(selectedProjectId, patterns, selectedTemplateId, batchOutputPrefix)
    );
    if (result) {
      setBatchResult(result);
      refreshProjectData(selectedProjectId);
    }
  }

  async function runCompare() {
    if (!selectedProjectId) return;
    const recordingIds = compareRecordingIds
      .split(/[,\s]+/)
      .map((value) => value.trim())
      .filter(Boolean);
    const metricKeys = compareMetric
      .split(/[,\s]+/)
      .map((value) => value.trim())
      .filter(Boolean);
    const result = await run(t("busyComparing"), () =>
      api.compare(selectedProjectId, recordingIds, metricKeys, "summary")
    );
    if (result) setCompareResult(result);
  }

  async function exportProject() {
    if (!selectedProjectId) return;
    const outputPath = normalizeSourcePathInput(defaultExportDir);
    if (outputPath !== defaultExportDir) {
      setDefaultExportDir(outputPath);
    }
    const result = await run(t("busyExportingProject"), () =>
      api.exportProject(selectedProjectId, outputPath || undefined)
    );
    if (result) setProjectExport(result);
  }

  async function chooseExportFolder() {
    if (!isTauriRuntime()) {
      setError(t("errorPickerUnavailable"));
      return;
    }
    const selected = await run(t("busySelectingExportFolder"), () =>
      openDialog({
        title: t("selectExportFolder"),
        directory: true,
        multiple: false,
        recursive: false
      })
    );
    const selectedPath = Array.isArray(selected) ? selected[0] : selected;
    if (selectedPath) {
      setDefaultExportDir(normalizeSourcePathInput(selectedPath));
      setError("");
    }
  }

  async function openProjectPackage() {
    if (!isTauriRuntime()) {
      setError(t("errorPickerUnavailable"));
      return;
    }
    const selected = await run(t("busyOpeningPackage"), () =>
      openDialog({
        title: t("selectProjectPackage"),
        multiple: false,
        filters: [
          {
            name: "DataScope Project Package",
            extensions: ["zip"]
          }
        ]
      })
    );
    const selectedPath = Array.isArray(selected) ? selected[0] : selected;
    if (!selectedPath) return;
    const packagePath = normalizeSourcePathInput(selectedPath);
    const result = await run(t("busyOpeningPackage"), () => api.importProjectPackage(packagePath));
    if (result) {
      setProjects((current) => upsertProject(current, result.project));
      setSelectedProjectId(result.project.id);
      setRecordings(result.recordings);
      setJobs([]);
      setSource(null);
      setStreams([]);
      setMapping(null);
      setSchemaProfile(null);
      setMappingValidation(null);
      setMappingConfirmed(false);
      setTemplates([]);
      setSavedMappingId("");
      setBuildResult(null);
      setProjectSources([]);
      setMappingDiff(null);
      setOpenedPackagePath(result.package_path);
      setError("");
      setActiveSection("dashboard");
    }
  }

  function goToSection(sectionId: string) {
    setActiveSection(sectionId);
    document.querySelector(".workspace")?.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }

  function handleDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragActive(true);
  }

  function handleDragLeave(event: DragEvent<HTMLDivElement>) {
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
    setDragActive(false);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragActive(false);
    const droppedFile = event.dataTransfer.files?.[0] as
      | (File & { path?: string; webkitRelativePath?: string })
      | undefined;
    const uriList = event.dataTransfer.getData("text/uri-list");
    const textPath = event.dataTransfer.getData("text/plain");
    const droppedPath =
      droppedFile?.path ??
      droppedFile?.webkitRelativePath ??
      normalizeDroppedPath(uriList || textPath);
    if (droppedPath) setSourcePath(normalizeSourcePathInput(droppedPath));
  }

  async function chooseSource(kind: "file" | "folder") {
    setSourcePickerOpen(false);
    if (!isTauriRuntime()) {
      setError(t("errorPickerUnavailable"));
      return;
    }
    const selected = await run(
      kind === "file" ? t("busySelectingFile") : t("busySelectingFolder"),
      () =>
        openDialog({
          title: kind === "file" ? t("selectSourceFile") : t("selectSourceFolder"),
          directory: kind === "folder",
          multiple: false,
          recursive: kind === "folder",
          filters:
            kind === "file"
              ? [
                  {
                    name: "DataScope",
                    extensions: ["csv", "jsonl", "json", "mcap", "ply", "pcd", "npy", "npz"]
                  },
                  {
                    name: "Tabular",
                    extensions: ["csv", "jsonl", "json"]
                  },
                  {
                    name: "Point Cloud",
                    extensions: ["ply", "pcd", "npy", "npz"]
                  },
                  {
                    name: "MCAP",
                    extensions: ["mcap"]
                  }
                ]
              : undefined
        })
    );
    const selectedPath = Array.isArray(selected) ? selected[0] : selected;
    if (selectedPath) {
      setSourcePath(normalizeSourcePathInput(selectedPath));
      setError("");
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-mark" aria-hidden="true">
          <Database size={20} />
        </div>
        <div className="topbar-title">
          <h1>DataScope Studio</h1>
          <span>{t("localCatalog")}</span>
        </div>
        <div className="topbar-spacer" />
        <StatusBadge tone={error ? "danger" : "success"} label={error ? t("needsAttention") : t("online")} />
        {busy && <span className="busy-indicator">{busy}</span>}
        <button className="icon-button" onClick={refreshAll} title={t("refreshWorkspace")}>
          <RefreshCcw size={16} />
        </button>
        <button className="icon-button" onClick={() => goToSection("settings")} title={t("settings")}>
          <Settings size={16} />
        </button>
      </header>

      <div className="app-frame">
        <aside className="sidebar">
          <nav className="sidebar-nav" aria-label="Primary">
            <NavButton
              active={activeSection === "dashboard"}
              icon={<LayoutDashboard size={17} />}
              label={t("dashboard")}
              onClick={() => goToSection("dashboard")}
            />
            <NavButton
              active={activeSection === "import"}
              icon={<Upload size={17} />}
              label={t("import")}
              onClick={() => goToSection("import")}
            />
            <NavButton
              active={activeSection === "recordings"}
              icon={<ListChecks size={17} />}
              label={t("recordings")}
              onClick={() => goToSection("recordings")}
            />
            <NavButton
              active={activeSection === "templates"}
              icon={<Image size={17} />}
              label={t("templates")}
              onClick={() => goToSection("templates")}
            />
            <NavButton
              active={activeSection === "settings"}
              icon={<Settings size={17} />}
              label={t("settings")}
              onClick={() => goToSection("settings")}
            />
          </nav>

          <section className="sidebar-card">
            <div className="sidebar-card-title">
              <span>{t("workspace")}</span>
              <button className="mini-button" onClick={refreshProjects} title={t("busyRefreshingProjects")}>
                <RefreshCcw size={14} />
              </button>
            </div>
            <label className="field-label" htmlFor="project-select">
              {t("currentProject")}
            </label>
            <select
              id="project-select"
              value={selectedProjectId}
              onChange={(event) => setSelectedProjectId(event.target.value)}
            >
              <option value="">{t("selectProject")}</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
            <div className="compact-form">
              <input
                aria-label={t("createProject")}
                value={projectName}
                onChange={(event) => setProjectName(event.target.value)}
              />
              <button className="icon-button" onClick={createProject} title={t("createProject")}>
                <FolderPlus size={16} />
              </button>
            </div>
            {selectedProject && <p className="path-line">{selectedProject.workspace_path}</p>}
          </section>

          <section className="sidebar-card subtle">
            <div className="mini-stat">
              <span>{t("recordings")}</span>
              <strong>{recordings.length}</strong>
            </div>
            <div className="mini-stat">
              <span>{t("jobs")}</span>
              <strong>{jobs.length}</strong>
            </div>
            <div className="mini-stat">
              <span>{t("templates")}</span>
              <strong>{templateRegistry.length}</strong>
            </div>
          </section>
        </aside>

        <section className="workspace">
          {(busy || error) && (
            <div className={`notice ${error ? "notice-error" : "notice-info"}`} role="status">
              {error ? <AlertCircle size={17} /> : <Activity size={17} />}
              <span>{error || busy}</span>
            </div>
          )}

          {activeSection === "dashboard" && (
          <section className="dashboard" id="dashboard">
            <div className="hero-card project-summary-card">
              <div className="project-summary-main">
                <div>
                  <span className="eyebrow">{t("currentProjectEyebrow")}</span>
                  <h2>{selectedProject?.name ?? t("selectOrCreateProject")}</h2>
                  <p>
                    {selectedProject
                      ? t("projectReadyDescription")
                      : t("projectEmptyDescription")}
                  </p>
                </div>
                <div className="project-meta-list">
                  <span className="project-meta-item">
                    <FolderOpen size={14} />
                    {selectedProject?.workspace_path ?? t("createProject")}
                  </span>
                  <span className="project-meta-item">
                    <ListChecks size={14} />
                    {latestRecording ? `${t("latestRun")}: ${latestRecording.run_name}` : t("noLatestRun")}
                  </span>
                  <span className="project-meta-item">
                    <Activity size={14} />
                    {latestJob ? `${latestJob.type} / ${latestJob.status}` : t("localArtifacts")}
                  </span>
                </div>
                <div className="hero-metrics compact-metrics">
                  <Metric label={t("runs")} value={recordings.length} />
                  <Metric label={t("streams")} value={streams.length} />
                  <Metric label={t("jobs")} value={jobs.length} />
                </div>
              </div>
              <ProjectVisual recordings={recordings.length} streams={streams.length} jobs={jobs.length} />
            </div>

            <section className="card import-card">
              <CardHeader
                icon={<Upload size={18} />}
                title={t("importData")}
                subtitle={t("importDataSubtitle")}
              />
              <div className="source-picker-toolbar">
                <div className="source-picker-wrap">
                  <button
                    className="button-primary source-picker-button"
                    disabled={isBusy}
                    onClick={() => setSourcePickerOpen((value) => !value)}
                    type="button"
                  >
                    <FolderOpen size={16} />
                    {t("chooseSource")}
                  </button>
                  {sourcePickerOpen && (
                    <div className="source-picker-popover" role="menu">
                      <button type="button" onClick={() => chooseSource("file")}>
                        <FileSearch size={16} />
                        <span>
                          <strong>{t("selectSourceFile")}</strong>
                          <small>{t("selectSourceFileHint")}</small>
                        </span>
                      </button>
                      <button type="button" onClick={() => chooseSource("folder")}>
                        <FolderOpen size={16} />
                        <span>
                          <strong>{t("selectSourceFolder")}</strong>
                          <small>{t("selectSourceFolderHint")}</small>
                        </span>
                      </button>
                    </div>
                  )}
                </div>
                <button disabled={isBusy} onClick={importAndInspect} type="button">
                  <FileSearch size={16} />
                  {t("inspectSource")}
                </button>
              </div>
              <div
                className={`drop-zone compact-drop-zone ${dragActive ? "is-dragging" : ""}`}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
              >
                <div className="drop-icon">
                  <Upload size={22} />
                </div>
                <div>
                  <strong>{t("dragSourceHere")}</strong>
                  <span>{t("supportedSources")}</span>
                </div>
              </div>
              <div className="chip-row">
                {supportedFormats.map((format) => (
                  <span className="chip" key={format}>
                    {format}
                  </span>
                ))}
              </div>
              <input
                placeholder={t("sourcePathPlaceholder")}
                value={sourcePath}
                onChange={(event) => setSourcePath(event.target.value)}
                onBlur={(event) => setSourcePath(normalizeSourcePathInput(event.target.value))}
              />
            </section>

            <section className="card quick-actions-card">
              <CardHeader icon={<Zap size={18} />} title={t("quickActions")} subtitle={t("quickActionsSubtitle")} />
              <div className="quick-actions">
                <button onClick={() => refreshProjectData()} disabled={!selectedProjectId || isBusy}>
                  <RefreshCcw size={16} />
                  {t("refreshRuns")}
                </button>
                <button onClick={exportProject} disabled={!selectedProjectId || isBusy}>
                  <Download size={16} />
                  {t("exportProject")}
                </button>
                <button onClick={openProjectPackage} disabled={isBusy}>
                  <FolderOpen size={16} />
                  {t("openProjectPackage")}
                </button>
                <button onClick={openInRerun} disabled={(!buildResult && !latestRecording) || isBusy}>
                  <ExternalLink size={16} />
                  {t("openInRerun")}
                </button>
              </div>
              {projectExport && <p className="path-line light">{t("packagePath")}: {projectExport.path}</p>}
              {openedPackagePath && <p className="path-line light">{t("importedPackage")}: {openedPackagePath}</p>}
              {latestJob && (
                <div className="soft-status">
                  <span>{latestJob.type}</span>
                  <StatusBadge tone={latestJob.status === "failed" ? "danger" : "neutral"} label={latestJob.status} />
                </div>
              )}
            </section>

            <section className="card recent-runs-card">
              <CardHeader
                icon={<ListChecks size={18} />}
                title={t("recentRuns")}
                subtitle={latestRecording ? `${t("latest")}: ${latestRecording.run_name}` : t("noRecordingsYet")}
              />
              {recordings.length ? (
                <div className="compact-list">
                  {recentRecordings.map((recording) => (
                    <div className="run-row" key={recording.id}>
                      <div>
                        <strong>{recording.run_name}</strong>
                        <span>{recording.source_type ?? t("unknown")} · {formatDateTime(recording.created_at, language)}</span>
                      </div>
                      <div className="run-row-actions">
                        <StatusBadge tone="neutral" label={recording.blueprint_id ?? t("recording")} />
                        <button className="mini-button" onClick={() => openRecording(recording)} disabled={isBusy} title={t("openInRerun")}>
                          <ExternalLink size={15} />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState text={t("recordingsWillAppear")} />
              )}
            </section>
          </section>
          )}

          {activeSection === "import" && (
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
                    onChange={(event) => changeTemplate(event.target.value)}
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
                  onChange={(event) => setSelectedMappingTemplateId(event.target.value)}
                >
                  <option value="">{t("automaticMapping")}</option>
                  {mappingTemplates.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name} ({item.source_family})
                    </option>
                  ))}
                </select>
                <button
                  onClick={applySelectedMappingTemplate}
                  disabled={!source || !selectedMappingTemplateId || isBusy}
                >
                  {t("applyMappingTemplate")}
                </button>
                <input
                  value={mappingTemplateName}
                  onChange={(event) => setMappingTemplateName(event.target.value)}
                  placeholder={t("mappingTemplateName")}
                />
                <button
                  onClick={createCurrentMappingTemplate}
                  disabled={!mapping || !mappingTemplateName.trim() || isBusy}
                >
                  <Save size={16} />
                  {t("saveAsMappingTemplate")}
                </button>
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
                          onChange={(event) => updateTimeline("source_field", event.target.value)}
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
                          onChange={(event) => updateTimeline("unit", event.target.value)}
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
                          onChange={(event) => updateTimeline("sort", event.target.value)}
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
                                    updateMappingStream(index, "enabled", event.target.checked)
                                  }
                                />
                              </td>
                              <td>
                                <input
                                  value={stream.source_fields.join(", ")}
                                  onChange={(event) =>
                                    updateMappingStream(index, "source_fields", event.target.value)
                                  }
                                />
                                <span className="subline">
                                  {stream.rule_key} / {stream.origin}
                                </span>
                              </td>
                              <td>
                                <select
                                  value={stream.semantic_type}
                                  disabled={source?.type === "mcap"}
                                  onChange={(event) =>
                                    updateMappingStream(index, "semantic_type", event.target.value)
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
                                  disabled={source?.type === "mcap"}
                                  title={source?.type === "mcap" ? t("mcapPathManaged") : undefined}
                                  onChange={(event) =>
                                    updateMappingStream(index, "entity_path", event.target.value)
                                  }
                                />
                                {source?.type === "mcap" && (
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
                            onApply={applyMappingSuggestion}
                          />
                        ))}
                      </div>
                    )}
                    <div className="actions">
                      <button onClick={saveMapping} disabled={isBusy || Boolean(savedMappingId)}>
                        <Save size={16} />
                        {savedMappingId ? t("draftSaved") : t("saveDraft")}
                      </button>
                      <button onClick={validateCurrentMapping} disabled={isBusy}>
                        <ListChecks size={16} />
                        {t("validateMapping")}
                      </button>
                      <button
                        className="button-primary"
                        onClick={confirmCurrentMapping}
                        disabled={isBusy || Boolean(mappingValidation && !mappingValidation.valid)}
                      >
                        <CheckCircle2 size={16} />
                        {mappingConfirmed ? t("mappingConfirmed") : t("confirmMapping")}
                      </button>
                      <span className={mappingConfirmed ? "success" : "pending"}>
                        {mappingConfirmed ? t("mappingConfirmed") : t("mappingDraft")}
                      </span>
                    </div>
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
                <select value={diffLeftSourceId} onChange={(event) => setDiffLeftSourceId(event.target.value)}>
                  <option value="">{t("leftSource")}</option>
                  {projectSources.map((item) => (
                    <option key={item.id} value={item.id}>{item.id} / {item.type}</option>
                  ))}
                </select>
                <select value={diffRightSourceId} onChange={(event) => setDiffRightSourceId(event.target.value)}>
                  <option value="">{t("rightSource")}</option>
                  {projectSources.map((item) => (
                    <option key={item.id} value={item.id}>{item.id} / {item.type}</option>
                  ))}
                </select>
                <button
                  onClick={runMappingDiff}
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
                  <input value={outputName} onChange={(event) => setOutputName(event.target.value)} />
                  <button className="button-primary" disabled={isBusy || !mappingConfirmed} onClick={buildRecording}>
                    <Play size={16} />
                    {t("buildArtifacts")}
                  </button>
                  <button disabled={!buildResult || isBusy} onClick={openInRerun}>
                    <ExternalLink size={16} />
                    {t("openInRerun")}
                  </button>
                </div>
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
                ) : (
                  <EmptyState text={t("buildEmpty")} />
                )}
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
          )}

          {activeSection === "recordings" && (
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
                        onChange={(event) => setTagInput(event.target.value)}
                      />
                    </div>
                    <div className="table-wrap responsive-table">
                      <table>
                        <thead>
                          <tr>
                            <th>{t("run")}</th>
                            <th>{t("template")}</th>
                            <th>{t("source")}</th>
                            <th>{t("tags")}</th>
                            <th>{t("action")}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {visibleRecordings.map((recording) => (
                            <tr key={recording.id}>
                              <td data-label={t("run")}>
                                <strong>{recording.run_name}</strong>
                                <span className="subline">{recording.id}</span>
                              </td>
                              <td data-label={t("template")}>{recording.blueprint_id}</td>
                              <td data-label={t("source")}>{recording.source_type ?? t("unknown")}</td>
                              <td data-label={t("tags")}>{recording.tags.join(", ") || "-"}</td>
                              <td data-label={t("action")}>
                                <button onClick={() => openRecording(recording)} disabled={isBusy}>
                                  <ExternalLink size={16} />
                                  {t("openInRerun")}
                                </button>
                                <button onClick={() => addTagToRecording(recording.id)} disabled={isBusy}>
                                  <Tags size={16} />
                                  {t("addTag")}
                                </button>
                              </td>
                            </tr>
                          ))}
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
                    onChange={(event) => setSelectedQueryTemplate(event.target.value)}
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
                    onChange={(event) => setSelectedQueryRecording(event.target.value)}
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
                      onChange={(event) => setQueryThreshold(event.target.value)}
                    />
                  )}
                  <button className="button-primary" onClick={runQuery} disabled={!selectedProjectId || isBusy}>
                    <Search size={16} />
                    {t("runQuery")}
                  </button>
                  <button onClick={exportQuery} disabled={!selectedProjectId || isBusy}>
                    <Download size={16} />
                    {t("exportCsv")}
                  </button>
                </div>
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
                    onChange={(event) => setCompareRecordingIds(event.target.value)}
                  />
                  <input
                    placeholder={t("metricPlaceholder")}
                    value={compareMetric}
                    onChange={(event) => setCompareMetric(event.target.value)}
                  />
                  <button className="button-primary" onClick={runCompare} disabled={!selectedProjectId || isBusy}>
                    <Search size={16} />
                    {t("compare")}
                  </button>
                </div>
                <ResultTable
                  result={compareResult}
                  emptyText={t("compareEmpty")}
                />
              </section>

              <section className="card">
                <CardHeader icon={<Activity size={18} />} title={t("jobs")} />
                {jobs.length ? (
                  <div className="job-list">
                    {visibleJobs.map((job) => (
                      <span key={job.id}>
                        {job.type} / {job.status} / {Math.round(job.progress * 100)}%
                      </span>
                    ))}
                  </div>
                ) : (
                  <EmptyState text={t("jobsEmpty")} />
                )}
              </section>
            </div>
          </section>
          )}

          {activeSection === "templates" && (
          <section className="section-stack" id="templates">
            <SectionTitle
              eyebrow={t("workspace")}
              title={t("templatesExtensions")}
              subtitle={t("templatesExtensionsSubtitle")}
            />
            <div className="two-column balanced">
              <section className="card">
                <CardHeader icon={<FolderOpen size={18} />} title={t("batchImport")} />
                <textarea
                  placeholder={t("batchPlaceholder")}
                  value={batchPattern}
                  onChange={(event) => setBatchPattern(event.target.value)}
                />
                <div className="inline-actions">
                  <input
                    value={batchOutputPrefix}
                    onChange={(event) => setBatchOutputPrefix(event.target.value)}
                  />
                  <button onClick={runBatchImport} disabled={!selectedProjectId || isBusy}>
                    <Upload size={16} />
                    {t("runBatch")}
                  </button>
                </div>
                {batchResult && (
                  <p className="path-line light">
                    {batchResult.id}: {batchResult.succeeded}/{batchResult.total} succeeded
                  </p>
                )}
              </section>

              <section className="card">
                <CardHeader
                  icon={<Save size={18} />}
                  title={t("extensionRegistry")}
                  subtitle={t("extensionRegistrySubtitle")}
                />
                <div className="extension-form">
                  <input
                    placeholder={t("pluginPathPlaceholder")}
                    value={pluginPath}
                    onChange={(event) => setPluginPath(event.target.value)}
                  />
                  <button onClick={installPlugin} disabled={isBusy}>
                    <Save size={16} />
                    {t("installPlugin")}
                  </button>
                  <input
                    placeholder={t("templatePathPlaceholder")}
                    value={templatePath}
                    onChange={(event) => setTemplatePath(event.target.value)}
                  />
                  <button onClick={installTemplate} disabled={isBusy}>
                    <Save size={16} />
                    {t("installTemplate")}
                  </button>
                </div>
              </section>
            </div>

            <section className="card mapping-template-manager">
              <CardHeader
                icon={<ListChecks size={18} />}
                title={t("mappingTemplateRegistry")}
                subtitle={`${mappingTemplates.length} ${t("mappingTemplates")}`}
              />
              <div className="mapping-template-manager-grid">
                <div className="mapping-template-controls">
                  <div className="mapping-template-control-row">
                    <input
                      placeholder={t("mappingTemplatePathPlaceholder")}
                      value={mappingTemplatePath}
                      onChange={(event) => setMappingTemplatePath(event.target.value)}
                    />
                    <button onClick={importMappingTemplate} disabled={isBusy}>
                      <Upload size={16} />
                      {t("importMappingTemplate")}
                    </button>
                  </div>
                  <select
                    value={selectedMappingTemplateId}
                    onChange={(event) => setSelectedMappingTemplateId(event.target.value)}
                  >
                    <option value="">{t("selectMappingTemplate")}</option>
                    {mappingTemplates.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name} / {item.source_family}
                      </option>
                    ))}
                  </select>
                  <div className="mapping-template-control-row">
                    <input
                      placeholder={t("mappingTemplateExportPath")}
                      value={mappingTemplateExportPath}
                      onChange={(event) => setMappingTemplateExportPath(event.target.value)}
                    />
                    <button
                      onClick={exportSelectedMappingTemplate}
                      disabled={!selectedMappingTemplateId || isBusy}
                    >
                      <Download size={16} />
                      {t("exportMappingTemplate")}
                    </button>
                  </div>
                </div>
                <div className="mapping-template-rules">
                  <label className="field-label">{t("mappingTemplateRules")}</label>
                  <textarea
                    className="mapping-template-json"
                    value={mappingTemplateJson}
                    onChange={(event) => setMappingTemplateJson(event.target.value)}
                    placeholder={t("mappingTemplateRulesHint")}
                  />
                  <div className="actions">
                    <button
                      onClick={saveMappingTemplateConfig}
                      disabled={!selectedMappingTemplateId || !mappingTemplateJson.trim() || isBusy}
                    >
                      <Save size={16} />
                      {t("saveTemplateRules")}
                    </button>
                  </div>
                </div>
              </div>
            </section>

            <section className="card registry-card">
              <CardHeader
                icon={<Database size={18} />}
                title={t("pluginTemplateRegistry")}
                subtitle={`${plugins.length} ${t("plugins")} / ${templateRegistry.length} ${t("templates")}`}
              />
              <div className="table-wrap responsive-table">
                <table>
                  <thead>
                    <tr>
                      <th>{t("kind")}</th>
                      <th>{t("name")}</th>
                      <th>{t("version")}</th>
                      <th>{t("status")}</th>
                      <th>{t("pathApp")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visiblePlugins.map((plugin) => (
                      <tr key={`plugin-${plugin.id}`}>
                        <td data-label={t("kind")}>{t("plugin")}</td>
                        <td data-label={t("name")}>{plugin.name}</td>
                        <td data-label={t("version")}>{plugin.version}</td>
                        <td data-label={t("status")}>{plugin.status}</td>
                        <td data-label={t("pathApp")}>{plugin.path}</td>
                      </tr>
                    ))}
                    {visibleTemplateRegistry.map((template) => (
                      <tr key={`template-${template.id}`}>
                        <td data-label={t("kind")}>{t("template")}</td>
                        <td data-label={t("name")}>{template.name}</td>
                        <td data-label={t("version")}>{template.version}</td>
                        <td data-label={t("status")}>{template.enabled ? t("enabled") : t("disabled")}</td>
                        <td data-label={t("pathApp")}>{template.app_id}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {visiblePlugins.length + visibleTemplateRegistry.length < plugins.length + templateRegistry.length && (
                <p className="render-limit-note">
                  {renderLimitText(
                    language,
                    visiblePlugins.length + visibleTemplateRegistry.length,
                    plugins.length + templateRegistry.length
                  )}
                </p>
              )}
              {!plugins.length && !templateRegistry.length && (
                <EmptyState text={t("registryEmpty")} />
              )}
            </section>
          </section>
          )}

          {activeSection === "settings" && (
          <section className="section-stack" id="settings">
            <SectionTitle
              eyebrow={t("workspace")}
              title={t("settings")}
              subtitle={t("settingsSubtitle")}
            />
            <section className="card">
              <CardHeader
                icon={<Settings size={18} />}
                title={t("preferences")}
                subtitle={t("preferencesSubtitle")}
              />
              <div className="settings-block">
                <div>
                  <strong>{t("language")}</strong>
                  <span>{t("languageSubtitle")}</span>
                </div>
                <div className="segmented-control" role="group" aria-label={t("language")}>
                  {languageOptions.map((option) => (
                    <button
                      key={option.value}
                      className={language === option.value ? "is-selected" : ""}
                      onClick={() => setLanguage(option.value)}
                      type="button"
                    >
                      {option.value === "zh" ? t("chinese") : t("english")}
                    </button>
                  ))}
                </div>
              </div>
              <div className="settings-block vertical">
                <div>
                  <strong>{t("defaultExportPath")}</strong>
                  <span>{t("defaultExportPathSubtitle")}</span>
                </div>
                <div className="settings-path-control">
                  <input
                    placeholder={t("exportPathPlaceholder")}
                    value={defaultExportDir}
                    onChange={(event) => setDefaultExportDir(event.target.value)}
                    onBlur={(event) => setDefaultExportDir(normalizeSourcePathInput(event.target.value))}
                  />
                  <button type="button" onClick={chooseExportFolder} disabled={isBusy}>
                    <FolderOpen size={16} />
                    {t("selectExportFolder")}
                  </button>
                </div>
              </div>
            </section>
          </section>
          )}
        </section>
      </div>
    </main>
  );
}

function normalizeDroppedPath(value: string) {
  const firstLine = value.trim().split(/\r?\n/)[0];
  if (!firstLine) return "";
  return normalizeSourcePathInput(decodeURIComponent(firstLine.replace(/^file:\/\//, "")));
}

function normalizeSourcePathInput(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return "";
  const roots = ["/home/", "/mnt/", "/media/", "/tmp/", "/var/", "/opt/"];
  for (const root of roots) {
    let index = trimmed.indexOf(root, 1);
    while (index > 0) {
      const prefix = trimmed.slice(0, index);
      const suffix = trimmed.slice(index);
      if (prefix === suffix || prefix.endsWith(suffix)) {
        return suffix;
      }
      index = trimmed.indexOf(root, index + root.length);
    }
  }
  return trimmed;
}

function isTauriRuntime() {
  return Boolean((window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__);
}

function getInitialDefaultExportDir() {
  return window.localStorage.getItem(DEFAULT_EXPORT_DIR_KEY) ?? "";
}

function upsertProject(projects: Project[], project: Project) {
  const withoutProject = projects.filter((item) => item.id !== project.id);
  return [project, ...withoutProject];
}

function formatCell(value: unknown) {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function formatDateTime(value: string, language: Language) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(language === "zh" ? "zh-CN" : "en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
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
  point_cloud_sample_warning: "issuePointCloudSampleWarning",
  point_cloud_coordinates_missing: "issuePointCloudCoordinatesMissing",
  image_stream_required: "issueImageStreamRequired"
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
  point_cloud_sample_warning: "recommendPointCloudSampleWarning",
  point_cloud_coordinates_missing: "recommendPointCloudCoordinatesMissing",
  image_stream_required: "recommendImageStreamRequired"
};

function MappingIssueCard({
  issue,
  language,
  t,
  isBusy,
  onApply
}: {
  issue: MappingValidationIssue;
  language: Language;
  t: (key: TranslationKey) => string;
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
        ? zh
          ? `使用 ${params.field} 作为时间字段`
          : `Use ${params.field} as time`
        : zh
          ? "使用行序列"
          : "Use row sequence";
    case "set_timeline_unit":
      return zh ? `时间单位设为 ${params.unit}` : `Use ${params.unit}`;
    case "set_timeline_sort":
      return params.sort === "ascending"
        ? zh
          ? "按时间升序排序"
          : "Sort by time ascending"
        : zh
          ? "保持源顺序"
          : "Keep source order";
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
        ? zh
          ? "启用该流"
          : "Enable stream"
        : zh
          ? "禁用可选流"
          : "Disable optional stream";
    default:
      return suggestion.label;
  }
}

function renderLimitText(language: Language, shown: number, total: number) {
  return language === "zh" ? `已显示 ${shown} / 共 ${total} 条` : `Showing ${shown} of ${total}`;
}

function derivedMappingFields(semanticType: string) {
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

const NavButton = memo(function NavButton({
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

const StatusBadge = memo(function StatusBadge({
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

const Metric = memo(function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="metric">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
});

const ProjectVisual = memo(function ProjectVisual({
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
            <div>
              <strong>{item.value}</strong>
              <span>{item.label}</span>
            </div>
            <span className="visual-track">
              <span style={{ width: `${Math.round(item.ratio * 100)}%` }} />
            </span>
          </div>
        ))}
        <div className="visual-foot">
          <span />
          <span />
          <span />
        </div>
      </div>
    </div>
  );
});

const CardHeader = memo(function CardHeader({
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
      <div>
        <h3>{title}</h3>
        {subtitle && <p>{subtitle}</p>}
      </div>
    </div>
  );
});

const SectionTitle = memo(function SectionTitle({
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
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h2>{title}</h2>
        <p>{subtitle}</p>
      </div>
      {action}
    </div>
  );
});

const StreamTable = memo(function StreamTable({
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
        <thead>
          <tr>
            <th>{labels.name}</th>
            <th>{labels.semanticType}</th>
            <th>{labels.fields}</th>
            <th>{labels.time}</th>
            <th>{labels.confidence}</th>
          </tr>
        </thead>
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

const ResultTable = memo(function ResultTable({
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
        <thead>
          <tr>
            {result.columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.slice(0, 50).map((row, index) => (
            <tr key={index}>
              {result.columns.map((column) => (
                <td key={column} data-label={column}>
                  {formatCell(row[column])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
});

const EmptyState = memo(function EmptyState({ text }: { text: string }) {
  return (
    <div className="empty-state">
      <Command size={17} />
      <span>{text}</span>
    </div>
  );
});

export default App;
