import {
  type DragEvent,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";
import { open as openDialog } from "@tauri-apps/plugin-dialog";

import { useQueryClient } from "@tanstack/react-query";

import { api, ApiError, asApiError, type ApiStatus } from "../../api";
import {
  ErrorDialog,
  GlobalErrorToast,
  clearErrorAreaState,
  defaultOutputName,
  derivedMappingFields,
  isBatchResult,
  isBuildResult,
  isTauriRuntime,
  isTerminalJob,
  normalizeDroppedPath,
  normalizeSourcePathInput,
  sourceFileDialogFilters,
  upsertProject,
  type AreaErrors,
  type ErrorDialogRequest,
  type ErrorArea,
  type GlobalNotification
} from "../../app-support";
import { DashboardSection } from "../../DashboardSection";
import { DiagnosticsSection } from "../../DiagnosticsSection";
import { logDiagnosticError } from "../../diagnostic-log";
import { ExtensionsSections } from "../../ExtensionsSections";
import { isActiveBuildJob } from "../../BuildJobStatus";
import { ImportWorkflowSection } from "../../ImportWorkflowSection";
import { RecordingsQueriesSection } from "../../RecordingsQueriesSection";
import { AppSidebar, AppTopbar } from "../../AppNavigation";
import {
  createTranslator,
  type Language
} from "../../i18n";
import { queryKeys } from "../../app/query-keys";
import {
  useImportDraftStore,
  type CsvHeaderMode
} from "../../stores/import-draft-store";
import { usePreferencesStore } from "../../stores/preferences-store";
import { useUiStore } from "../../stores/ui-store";
import type {
  BatchResult,
  BatchSummary,
  BuildResult,
  CustomQueryFilters,
  DiagnosticExport,
  DiagnosticExportResult,
  DiagnosticPreset,
  DiagnosticReport,
  DiagnosticThresholds,
  Job,
  JobSettings,
  MappingPayload,
  MappingDiff,
  MappingSuggestion,
  MappingTemplateItem,
  MappingValidation,
  Plugin,
  Project,
  ProjectExportResult,
  QueryResult,
  QueryTemplate,
  Recipe,
  Recording,
  Source,
  SchemaProfile,
  StreamInfo,
  TemplateMatch,
  TemplateRegistryItem
} from "../../types";

const thresholdTemplates = new Set(["low_battery", "detection_failure"]);
const TABLE_RENDER_LIMIT = 100;
const JOB_POLL_LIMIT = 50;
const ACTIVE_JOB_POLL_MS = 1000;
const IDLE_JOB_POLL_MS = 15_000;
const JOB_SETTINGS_STORAGE_KEY = "datascope.jobSettings.maxWorkers";
type RunOptions = {
  area?: ErrorArea | "global";
  retry?: () => void;
  onError?: (error: ApiError) => void;
  blockUi?: boolean;
};
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

function getInitialJobSettings(): JobSettings {
  const stored = Number(window.localStorage.getItem(JOB_SETTINGS_STORAGE_KEY) || "1");
  return { max_workers: Math.min(4, Math.max(1, Number.isFinite(stored) ? stored : 1)) };
}

function activeJobs(jobRows: Job[]) {
  return jobRows.filter((job) => !isTerminalJob(job));
}

function mergeJobRows(current: Job[], updates: Job[]) {
  const updateIds = new Set(updates.map((job) => job.id));
  return [...updates, ...current.filter((job) => !updateIds.has(job.id))].sort(
    (left, right) => Date.parse(right.created_at) - Date.parse(left.created_at)
  );
}

export function StudioWorkspace() {
  const queryClient = useQueryClient();
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectName, setProjectName] = useState("Sensor Run");
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const sourcePath = useImportDraftStore((state) => state.sourcePath);
  const setSourcePath = useImportDraftStore((state) => state.setSourcePath);
  const sourceStorageMode = useImportDraftStore((state) => state.sourceStorageMode);
  const setSourceStorageMode = useImportDraftStore((state) => state.setSourceStorageMode);
  const csvHeaderMode = useImportDraftStore((state) => state.csvHeaderMode);
  const setCsvHeaderMode = useImportDraftStore((state) => state.setCsvHeaderMode);
  const csvColumnNames = useImportDraftStore((state) => state.csvColumnNames);
  const setCsvColumnNames = useImportDraftStore((state) => state.setCsvColumnNames);
  const outputName = useImportDraftStore((state) => state.outputName);
  const setOutputName = useImportDraftStore((state) => state.setOutputName);
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
  const [activeBuildJobId, setActiveBuildJobId] = useState("");
  const [isBuildSubmitting, setIsBuildSubmitting] = useState(false);
  const [previewRows, setPreviewRows] = useState<Record<string, unknown>[]>([]);
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [plugins, setPlugins] = useState<Plugin[]>([]);
  const [templateRegistry, setTemplateRegistry] = useState<TemplateRegistryItem[]>([]);
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [queryTemplates, setQueryTemplates] = useState<QueryTemplate[]>([]);
  const [selectedQueryTemplate, setSelectedQueryTemplate] = useState("low_battery");
  const [selectedQueryRecording, setSelectedQueryRecording] = useState("");
  const [queryThreshold, setQueryThreshold] = useState("0.5");
  const [queryResult, setQueryResult] = useState<QueryResult | null>(null);
  const [customQueryEntityPath, setCustomQueryEntityPath] = useState("");
  const [customQueryKey, setCustomQueryKey] = useState("");
  const [customQueryText, setCustomQueryText] = useState("");
  const [customQuerySemanticTypes, setCustomQuerySemanticTypes] = useState("scalar,scalar_group,state");
  const [customQueryOperator, setCustomQueryOperator] =
    useState<NonNullable<CustomQueryFilters["operator"]>>("any");
  const [customQueryValue, setCustomQueryValue] = useState("");
  const [customQueryTimeStart, setCustomQueryTimeStart] = useState("");
  const [customQueryTimeEnd, setCustomQueryTimeEnd] = useState("");
  const [diagnosticReport, setDiagnosticReport] = useState<DiagnosticReport | null>(null);
  const [diagnosticPresets, setDiagnosticPresets] = useState<DiagnosticPreset[]>([]);
  const [diagnosticExports, setDiagnosticExports] = useState<DiagnosticExport[]>([]);
  const [diagnosticExportResult, setDiagnosticExportResult] =
    useState<DiagnosticExportResult | null>(null);
  const [apiStatus, setApiStatus] = useState<ApiStatus | null>(null);
  const [compareRecordingIds, setCompareRecordingIds] = useState("");
  const [compareMetric, setCompareMetric] = useState("battery");
  const [compareResult, setCompareResult] = useState<QueryResult | null>(null);
  const [batchPattern, setBatchPattern] = useState("");
  const [batchOutputPrefix, setBatchOutputPrefix] = useState("batch_run");
  const [batchStorageMode, setBatchStorageMode] = useState<"copy" | "reference">("copy");
  const [batchResult, setBatchResult] = useState<BatchResult | null>(null);
  const [batches, setBatches] = useState<BatchSummary[]>([]);
  const [selectedBatch, setSelectedBatch] = useState<BatchResult | null>(null);
  const [batchEstimate, setBatchEstimate] = useState("");
  const [jobSettings, setJobSettings] = useState<JobSettings>(getInitialJobSettings);
  const [pluginPath, setPluginPath] = useState("");
  const [templatePath, setTemplatePath] = useState("");
  const [exportPath, setExportPath] = useState("");
  const [projectExport, setProjectExport] = useState<ProjectExportResult | null>(null);
  const [openedPackagePath, setOpenedPackagePath] = useState("");
  const defaultExportDir = usePreferencesStore((state) => state.defaultExportDir);
  const setDefaultExportDir = usePreferencesStore((state) => state.setDefaultExportDir);
  const defaultArtifactDir = usePreferencesStore((state) => state.defaultArtifactDir);
  const setDefaultArtifactDir = usePreferencesStore((state) => state.setDefaultArtifactDir);
  const [mcapDecoders, setMcapDecoders] = useState("");
  const [rrdOptimizeProfile, setRrdOptimizeProfile] = useState("none");
  const [artifactValidation, setArtifactValidation] = useState("basic");
  const [catalogEnabled, setCatalogEnabled] = useState(false);
  const [catalogDataset, setCatalogDataset] = useState("datascope");
  const [catalogManagedLocal, setCatalogManagedLocal] = useState(true);
  const [catalogServerUrl, setCatalogServerUrl] = useState("");
  const [tagInput, setTagInput] = useState("");
  const [openingRecordingIds, setOpeningRecordingIds] = useState<Set<string>>(() => new Set());
  const busy = useUiStore((state) => state.busy);
  const setBusy = useUiStore((state) => state.setBusy);
  const [areaErrors, setAreaErrors] = useState<AreaErrors>({});
  const [globalNotification, setGlobalNotification] = useState<GlobalNotification | null>(null);
  const [errorDialog, setErrorDialog] = useState<ErrorDialogRequest | null>(null);
  const activeSection = useUiStore((state) => state.activeSection);
  const setActiveSection = useUiStore((state) => state.setActiveSection);
  const [dragActive, setDragActive] = useState(false);
  const sourcePickerOpen = useUiStore((state) => state.sourcePickerOpen);
  const setSourcePickerOpen = useUiStore((state) => state.setSourcePickerOpen);
  const language = usePreferencesStore((state) => state.language);
  const setLanguage = usePreferencesStore((state) => state.setLanguage);
  const outputNameRef = useRef<HTMLInputElement>(null);
  const processedJobIds = useRef(new Set<string>());
  const trackedActiveJobIds = useRef(new Set<string>());
  const [jobPollRevision, setJobPollRevision] = useState(0);
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
  const buildJob = useMemo(
    () => jobs.find((job) => job.id === activeBuildJobId) ?? null,
    [activeBuildJobId, jobs]
  );
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
    if (isTauriRuntime()) {
      void queryClient.fetchQuery({
        queryKey: queryKeys.apiStatus(),
        queryFn: () => api.status()
      }).then(setApiStatus).catch((error) => {
        logDiagnosticError("frontend.api_status", error);
      });
    }
    void refreshJobSettings();
  }, [queryClient]);

  useEffect(() => {
    if (selectedProjectId) {
      void refreshProjectData(selectedProjectId, activeSection === "recordings", {
        blockUi: false
      });
      if (activeSection === "diagnostics") {
        refreshDiagnosticData(selectedProjectId);
      }
    }
  }, [selectedProjectId]);

  useEffect(() => {
    setActiveBuildJobId("");
    setIsBuildSubmitting(false);
    setSelectedBatch(null);
    processedJobIds.current.clear();
    trackedActiveJobIds.current.clear();
  }, [selectedProjectId]);

  useEffect(() => {
    if (selectedProjectId && ["recordings", "diagnostics"].includes(activeSection)) {
      void refreshProjectData(selectedProjectId, true, { blockUi: false });
    }
    if (selectedProjectId && activeSection === "diagnostics") {
      refreshDiagnosticData(selectedProjectId);
    }
    if (activeSection === "templates") {
      refreshExtensionData();
    }
  }, [activeSection]);

  useEffect(() => {
    const selected = mappingTemplates.find((item) => item.id === selectedMappingTemplateId);
    setMappingTemplateJson(selected ? JSON.stringify(selected.config, null, 2) : "");
  }, [mappingTemplates, selectedMappingTemplateId]);

  useEffect(() => {
    if (!selectedProjectId) return;

    let disposed = false;
    let polling = false;
    let timer: number | undefined;
    const schedule = (delayMs: number) => {
      if (!disposed) {
        timer = window.setTimeout(() => void poll(), delayMs);
      }
    };

    const processCompletedJobs = (jobRows: Job[], trackedJobIds: Set<string>) => {
      const completed = jobRows.filter(
        (job) =>
          trackedJobIds.has(job.id) &&
          isTerminalJob(job) &&
          !processedJobIds.current.has(job.id)
      );
      completed.forEach((job) => {
        processedJobIds.current.add(job.id);
        if (job.status !== "succeeded" || !job.result) return;
        if (isBuildResult(job.result)) setBuildResult(job.result);
        if (isBatchResult(job.result)) setBatchResult(job.result);
      });
      return completed.length > 0;
    };

    const refreshCompletedProjectData = async () => {
      const selectedBatchId = selectedBatch?.id ?? "";
      const [, selectedBatchRow] = await Promise.all([
        refreshProjectData(selectedProjectId, activeSection === "recordings", {
          blockUi: false
        }),
        selectedBatchId ? api.batch(selectedBatchId) : Promise.resolve(null)
      ]);
      if (!disposed && selectedBatchRow) setSelectedBatch(selectedBatchRow);
    };

    const poll = async () => {
      if (polling) return;
      polling = true;
      try {
        const trackedJobIds = new Set(trackedActiveJobIds.current);
        const wasTrackingActiveJobs = trackedJobIds.size > 0;
        const jobRows = await api.jobs(selectedProjectId, {
          activeOnly: wasTrackingActiveJobs,
          limit: JOB_POLL_LIMIT
        });
        if (disposed) return;

        if (wasTrackingActiveJobs) {
          const activeRows = activeJobs(jobRows);
          const activeIds = new Set(activeRows.map((job) => job.id));
          const missingTrackedJob = [...trackedJobIds].some((jobId) => !activeIds.has(jobId));
          if (activeRows.length && !missingTrackedJob) {
            trackedActiveJobIds.current = activeIds;
            setJobs((current) => mergeJobRows(current, activeRows));
            schedule(ACTIVE_JOB_POLL_MS);
            return;
          }

          const fullJobRows = await api.jobs(selectedProjectId, { limit: JOB_POLL_LIMIT });
          if (disposed) return;
          setJobs(fullJobRows);
          const nextActiveRows = activeJobs(fullJobRows);
          trackedActiveJobIds.current = new Set(nextActiveRows.map((job) => job.id));
          const completed = processCompletedJobs(fullJobRows, trackedJobIds);
          if (completed) await refreshCompletedProjectData();
          schedule(nextActiveRows.length ? ACTIVE_JOB_POLL_MS : IDLE_JOB_POLL_MS);
          return;
        }

        setJobs(jobRows);
        const nextActiveRows = activeJobs(jobRows);
        trackedActiveJobIds.current = new Set(nextActiveRows.map((job) => job.id));
        schedule(nextActiveRows.length ? ACTIVE_JOB_POLL_MS : IDLE_JOB_POLL_MS);
      } catch {
        // The regular refresh path surfaces connectivity errors; polling stays quiet.
        schedule(IDLE_JOB_POLL_MS);
      } finally {
        polling = false;
      }
    };

    void poll();
    return () => {
      disposed = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [selectedProjectId, selectedBatch?.id, activeSection, jobPollRevision]);

  function clearAreaError(area: ErrorArea) {
    setAreaErrors((current) => clearErrorAreaState(current, area));
  }

  function showAreaError(area: ErrorArea, message: string, code = "client_validation") {
    setAreaErrors((current) => ({
      ...current,
      [area]: new ApiError(message, 0, code)
    }));
  }

  function setRecordingOpening(recordingId: string, opening: boolean) {
    if (!recordingId) return;
    setOpeningRecordingIds((current) => {
      const next = new Set(current);
      if (opening) {
        next.add(recordingId);
      } else {
        next.delete(recordingId);
      }
      return next;
    });
  }

  function trackJobForPolling(job: Job) {
    if (isTerminalJob(job)) return;
    trackedActiveJobIds.current.add(job.id);
    setJobPollRevision((current) => current + 1);
  }

  function upsertJob(job: Job) {
    setJobs((current) => [job, ...current.filter((item) => item.id !== job.id)]);
    trackJobForPolling(job);
  }

  function trackActiveJobsFromRows(jobRows: Job[]) {
    const next = new Set(activeJobs(jobRows).map((job) => job.id));
    const current = trackedActiveJobIds.current;
    const changed = next.size !== current.size || [...next].some((jobId) => !current.has(jobId));
    trackedActiveJobIds.current = next;
    if (next.size && changed) setJobPollRevision((value) => value + 1);
  }

  function shouldOpenErrorDialog(area: ErrorArea | "global", error: ApiError) {
    if (area === "global") return true;
    if (error.code === "artifact_name_conflict") return true;
    if (error.code === "mapping_validation_failed") return false;
    return [
      "dashboard",
      "import",
      "build",
      "diagnostics",
      "batch",
      "extensions",
      "mappingTemplates",
      "settings"
    ].includes(area);
  }

  function openErrorDialog(
    error: ApiError,
    area: ErrorArea | "global",
    retry?: () => void,
    context: Record<string, unknown> = {}
  ) {
    setErrorDialog({ error, area, retry, context });
  }

  function buildJobError(job: Job) {
    const details = {
      ...(job.error?.details ?? {}),
      job_id: job.id,
      stage: job.stage,
      status: job.status
    };
    return new ApiError(
      job.error?.message || job.error_message || t("buildFailedHint"),
      0,
      job.error?.code || "job_failed",
      details
    );
  }

  async function run<T>(
    label: string,
    task: () => Promise<T>,
    options: RunOptions = {}
  ): Promise<T | null> {
    const area = options.area ?? "global";
    const blockUi = options.blockUi ?? true;
    if (blockUi) setBusy(label);
    if (area === "global") {
      setGlobalNotification(null);
    } else {
      clearAreaError(area);
    }
    try {
      return await task();
    } catch (err) {
      const apiError = asApiError(err);
      logDiagnosticError("frontend.operation", apiError, {
        area,
        code: apiError.code,
        status: apiError.status
      });
      if (area === "global") {
        setGlobalNotification({ error: apiError, retry: options.retry });
      } else {
        setAreaErrors((current) => ({ ...current, [area]: apiError }));
      }
      if (shouldOpenErrorDialog(area, apiError)) {
        openErrorDialog(apiError, area, options.retry, { operation: label });
      }
      options.onError?.(apiError);
      return null;
    } finally {
      if (blockUi) setBusy("");
    }
  }

  async function refreshProjects(): Promise<boolean> {
    const result = await run(
      t("busyRefreshingProjects"),
      () =>
        queryClient.fetchQuery({
          queryFn: () => api.projects(),
          queryKey: queryKeys.projects()
        }),
      {
        retry: () => void refreshProjects()
      }
    );
    if (result) {
      setProjects(result);
      if (!selectedProjectId && result[0]) {
        setSelectedProjectId(result[0].id);
      }
    }
    return result !== null;
  }

  async function refreshProjectData(
    projectId = selectedProjectId,
    includeQueryTemplates = false,
    options: { blockUi?: boolean } = {}
  ): Promise<boolean> {
    if (!projectId) return true;
    const result = await run(
      t("busyRefreshingWorkspace"),
      () =>
        queryClient.fetchQuery({
          queryFn: async () => {
            const [recordingRows, jobRows, sourceRows, batchRows] = await Promise.all([
              api.recordings(projectId),
              api.jobs(projectId),
              api.sources(projectId),
              api.batches(projectId)
            ]);
            const templatesRows = includeQueryTemplates ? await api.queryTemplates(projectId) : null;
            return { recordingRows, jobRows, sourceRows, batchRows, templatesRows };
          },
          queryKey: queryKeys.projectData(projectId, includeQueryTemplates),
          staleTime: 0
        }),
      {
        blockUi: options.blockUi,
        retry: () => void refreshProjectData(projectId, includeQueryTemplates, options)
      }
    );
    if (result) {
      setRecordings(result.recordingRows);
      setJobs(result.jobRows);
      trackActiveJobsFromRows(result.jobRows);
      setProjectSources(result.sourceRows);
      setBatches(result.batchRows);
      if (selectedBatch && !result.batchRows.some((batch) => batch.id === selectedBatch.id)) {
        setSelectedBatch(null);
      }
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
    return result !== null;
  }

  async function refreshDiagnosticData(projectId = selectedProjectId): Promise<boolean> {
    if (!projectId) return true;
    const result = await run(
      t("busyRefreshingWorkspace"),
      () =>
        queryClient.fetchQuery({
          queryFn: async () => {
            const [presetRows, exportRows] = await Promise.all([
              api.diagnosticPresets(projectId),
              api.diagnosticExports(projectId)
            ]);
            return { presetRows, exportRows };
          },
          queryKey: ["projects", projectId, "diagnostics"]
        }),
      {
        retry: () => void refreshDiagnosticData(projectId)
      }
    );
    if (result) {
      setDiagnosticPresets(result.presetRows);
      setDiagnosticExports(result.exportRows);
    }
    return result !== null;
  }

  async function refreshJobSettings(): Promise<boolean> {
    const result = await run(
      t("busyRefreshingWorkspace"),
      () =>
        queryClient.fetchQuery({
          queryFn: async () => {
            const remote = await api.jobSettings();
            const stored = getInitialJobSettings();
            if (stored.max_workers !== remote.max_workers) {
              return api.updateJobSettings(stored.max_workers);
            }
            return remote;
          },
          queryKey: queryKeys.jobSettings()
        }),
      {
        area: "settings",
        retry: () => void refreshJobSettings()
      }
    );
    if (result) setJobSettings(result);
    return result !== null;
  }

  async function refreshTemplateRegistry(): Promise<boolean> {
    const result = await run(
      t("busyLoadingRegistry"),
      () =>
        queryClient.fetchQuery({
          queryFn: async () => {
            const [templateRows, mappingTemplateRows, recipeRows] = await Promise.all([
              api.templates(),
              api.mappingTemplates(),
              api.recipes()
            ]);
            return { templateRows, mappingTemplateRows, recipeRows };
          },
          queryKey: queryKeys.templateRegistry()
        }),
      {
        retry: () => void refreshTemplateRegistry()
      }
    );
    if (result) {
      setTemplateRegistry(result.templateRows);
      setMappingTemplates(result.mappingTemplateRows);
      setRecipes(result.recipeRows);
      setSelectedMappingTemplateId((current) => current || result.mappingTemplateRows[0]?.id || "");
    }
    return result !== null;
  }

  async function refreshExtensionData(): Promise<boolean> {
    const result = await run(
      t("busyLoadingRegistry"),
      () =>
        queryClient.fetchQuery({
          queryFn: async () => {
            const [pluginRows, templateRows, mappingTemplateRows, recipeRows] = await Promise.all([
              api.plugins(),
              api.templates(),
              api.mappingTemplates(),
              api.recipes()
            ]);
            return { pluginRows, templateRows, mappingTemplateRows, recipeRows };
          },
          queryKey: queryKeys.extensionRegistry()
        }),
      {
        retry: () => void refreshExtensionData()
      }
    );
    if (result) {
      setPlugins(result.pluginRows);
      setTemplateRegistry(result.templateRows);
      setMappingTemplates(result.mappingTemplateRows);
      setRecipes(result.recipeRows);
      setSelectedMappingTemplateId((current) => current || result.mappingTemplateRows[0]?.id || "");
    }
    return result !== null;
  }

  async function refreshAll() {
    if (!(await refreshProjects())) return;
    if (selectedProjectId && !(await refreshProjectData(selectedProjectId))) return;
    if (activeSection === "templates") {
      await refreshExtensionData();
    } else if (activeSection !== "settings") {
      await refreshTemplateRegistry();
    }
  }

  async function createProject() {
    const result = await run(t("busyCreatingProject"), () => api.createProject(projectName), {
      area: "project"
    });
    if (result) {
      setProjects((current) => [result, ...current]);
      setSelectedProjectId(result.id);
    }
  }

  async function importAndInspect() {
    const nextSourcePath = normalizeSourcePathInput(sourcePath);
    if (!nextSourcePath) {
      showAreaError("import", t("errorMissingSourcePath"));
      return;
    }
    if (nextSourcePath !== sourcePath) {
      setSourcePath(nextSourcePath);
    }
    const result = await run(
      t("busyInspectingSource"),
      async () => {
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

        const importOptions = nextSourcePath.toLowerCase().endsWith(".csv")
          ? {
              csv: {
                header_mode: csvHeaderMode,
                column_names: csvColumnNames
                  .split(",")
                  .map((name) => name.trim())
                  .filter(Boolean)
              }
            }
          : {};
        const imported = await api.importWorkflow(
          projectIdForImport,
          nextSourcePath,
          sourceStorageMode,
          importOptions
        );
        return {
          added: imported.source,
          project: projectForImport,
          projectRows,
          streams: imported.streams,
          templateMatches: imported.template_matches,
          nextTemplateId: imported.template_id,
          suggested: imported.mapping,
          savedMappingId: imported.saved_mapping.id,
          previewRows: imported.preview.rows,
          schemaProfile: imported.schema_profile,
          validation: imported.validation
        };
      },
      { area: "import" }
    );
    if (result) {
      setProjects(result.projectRows);
      if (result.project) {
        setSelectedProjectId(result.project.id);
      }
      setSource(result.added);
      setOutputName(defaultOutputName(nextSourcePath));
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
      setActiveBuildJobId("");
      setIsBuildSubmitting(false);
      clearAreaError("build");
      setActiveSection("import");
    }
  }

  async function saveMapping() {
    if (!source || !mapping) return;
    const saved = await run(
      t("busySavingMapping"),
      () => api.saveMapping(source.id, mapping.mapping),
      { area: "mapping" }
    );
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
    const result = await run(
      t("busyValidatingMapping"),
      () => api.validateMapping(source.id, mapping.mapping),
      { area: "mapping" }
    );
    if (result) setMappingValidation(result);
    return result;
  }

  async function confirmCurrentMapping() {
    if (!source || !mapping) return;
    const result = await run(
      t("busyConfirmingMapping"),
      async () => {
        const saved = savedMappingId
          ? { id: savedMappingId }
          : await api.saveMapping(source.id, mapping.mapping);
        return api.confirmMapping(saved.id);
      },
      {
        area: "mapping",
        onError: (error) => {
          if (error.code === "mapping_validation_failed" && error.details.validation) {
            setMappingValidation(error.details.validation);
          }
        }
      }
    );
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
      showAreaError("build", t("errorMappingUnavailable"));
      return;
    }
    if (!mappingConfirmed) {
      showAreaError("build", t("errorConfirmMappingFirst"));
      return;
    }
    if (isBuildSubmitting || isActiveBuildJob(buildJob)) return;

    setIsBuildSubmitting(true);
    setActiveBuildJobId("");
    setBuildResult(null);
    clearAreaError("build");
    try {
      const mappingId = savedMappingId || (await api.saveMapping(source.id, mapping.mapping)).id;
      const built = await api.build(
        selectedProject.id,
        source.id,
        mappingId,
        outputName,
        selectedTemplateId,
        normalizeSourcePathInput(defaultArtifactDir) || undefined,
        {
          mcap_decoders:
            source.type === "mcap" || source.type === "ros2_db3"
              ? parseListInput(mcapDecoders)
              : null,
          rrd_optimize_profile: rrdOptimizeProfile,
          artifact_validation: artifactValidation,
          catalog_registration: {
            enabled: catalogEnabled,
            dataset_name: catalogDataset,
            server_url: catalogManagedLocal ? null : normalizeSourcePathInput(catalogServerUrl),
            managed_local: catalogManagedLocal
          }
        }
      );
      setSavedMappingId(mappingId);
      setActiveBuildJobId(built.id);
      upsertJob(built);
      setBuildResult(null);
    } catch (err) {
      const apiError = asApiError(err);
      logDiagnosticError("frontend.build_recording", apiError, {
        code: apiError.code,
        status: apiError.status
      });
      setAreaErrors((current) => ({ ...current, build: apiError }));
      openErrorDialog(apiError, "build", undefined, { output_name: outputName });
      if (apiError.code === "artifact_name_conflict") {
        window.requestAnimationFrame(() => {
          outputNameRef.current?.focus();
          outputNameRef.current?.select();
        });
      }
    } finally {
      setIsBuildSubmitting(false);
    }
  }

  async function cancelJob(job: Job) {
    const result = await run(
      t("busyCancellingJob"),
      () => api.cancelJob(job.id),
      { area: "recordings" }
    );
    if (result) {
      upsertJob(result);
    }
  }

  async function retryJob(job: Job) {
    const result = await run(
      t("busyRetryingJob"),
      () => api.retryJob(job.id),
      { area: "recordings" }
    );
    if (result) {
      upsertJob(result);
    }
  }

  async function openInRerun() {
    const recordingPath = buildResult?.recording_path ?? latestRecording?.path;
    const blueprintPath = buildResult?.blueprint_path ?? latestRecording?.blueprint_path ?? undefined;
    const recordingId = buildResult?.recording_id ?? latestRecording?.id ?? "";
    if (!recordingPath) {
      showAreaError(activeSection === "import" ? "build" : "dashboard", t("errorNoRecordingToOpen"));
      return;
    }
    setRecordingOpening(recordingId, true);
    try {
      await run(t("busyOpeningRerun"), () => api.open(recordingPath, blueprintPath), {
        area: activeSection === "import" ? "build" : "dashboard",
        blockUi: false
      });
    } finally {
      setRecordingOpening(recordingId, false);
    }
  }

  async function openRecording(recording: Recording) {
    setRecordingOpening(recording.id, true);
    try {
      await run(
        t("busyOpeningRerun"),
        () => api.open(recording.path, recording.blueprint_path ?? undefined),
        {
          area: activeSection === "dashboard" ? "dashboard" : "recordings",
          blockUi: false
        }
      );
    } finally {
      setRecordingOpening(recording.id, false);
    }
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
    clearAreaError("mapping");
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
    clearAreaError("mapping");
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
    const result = await run(
      t("busyApplyingMappingFix"),
      () => api.validateMapping(source.id, next.mapping),
      { area: "mapping" }
    );
    if (result) setMappingValidation(result);
  }

  async function changeTemplate(templateId: string) {
    setSelectedTemplateId(templateId);
    setSavedMappingId("");
    if (!source) return;
    const result = await run(
      t("busySuggestingMapping"),
      async () => {
        const suggested = await api.suggestMappingForTemplate(source.id, templateId);
        const savedMapping = await api.saveMapping(source.id, suggested.mapping);
        const validation = await api.validateMapping(source.id, suggested.mapping);
        return { suggested, savedMappingId: savedMapping.id, validation };
      },
      { area: "mappingToolbar" }
    );
    if (result) {
      setMapping(result.suggested);
      setSavedMappingId(result.savedMappingId);
      setMappingValidation(result.validation);
      setMappingConfirmed(false);
    }
  }

  async function applySelectedMappingTemplate() {
    if (!source || !selectedMappingTemplateId) return;
    const result = await run(
      t("busyApplyingMappingTemplate"),
      () => api.applyMappingTemplate(selectedMappingTemplateId, source.id),
      { area: "mappingToolbar" }
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
    const result = await run(
      t("busySavingMappingTemplate"),
      async () => {
        const saved = savedMappingId
          ? { id: savedMappingId }
          : await api.saveMapping(source.id, mapping.mapping);
        const template = await api.createMappingTemplate(
          mappingTemplateName.trim(),
          source.id,
          saved.id
        );
        return { template, mappingId: saved.id };
      },
      { area: "mappingToolbar" }
    );
    if (result) {
      setSavedMappingId(result.mappingId);
      await refreshTemplateRegistry();
      setSelectedMappingTemplateId(result.template.id);
    }
  }

  async function importMappingTemplate() {
    if (!mappingTemplatePath.trim()) return;
    const result = await run(
      t("busyImportingMappingTemplate"),
      () => api.importMappingTemplate(mappingTemplatePath.trim()),
      { area: "mappingTemplates" }
    );
    if (result) {
      setMappingTemplatePath("");
      await refreshTemplateRegistry();
      setSelectedMappingTemplateId(result.id);
    }
  }

  async function saveMappingTemplateConfig() {
    if (!selectedMappingTemplateId || !mappingTemplateJson.trim()) return;
    const result = await run(
      t("busySavingMappingTemplate"),
      () => api.saveMappingTemplate(selectedMappingTemplateId, JSON.parse(mappingTemplateJson)),
      { area: "mappingTemplates" }
    );
    if (result) await refreshTemplateRegistry();
  }

  async function exportSelectedMappingTemplate() {
    if (!selectedMappingTemplateId) return;
    const result = await run(
      t("busyExportingMappingTemplate"),
      () =>
        api.exportMappingTemplate(
          selectedMappingTemplateId,
          mappingTemplateExportPath.trim() || undefined
        ),
      { area: "mappingTemplates" }
    );
    if (result) setMappingTemplateExportPath(result.path);
  }

  async function deleteSelectedMappingTemplate() {
    if (!selectedMappingTemplateId) return;
    const deletedId = selectedMappingTemplateId;
    const result = await run(
      t("busyDeletingMappingTemplate"),
      () => api.deleteMappingTemplate(deletedId),
      { area: "mappingTemplates" }
    );
    if (!result) return;
    setMappingTemplates((current) => current.filter((item) => item.id !== deletedId));
    setSelectedMappingTemplateId("");
    setMappingTemplateJson("");
  }

  async function runMappingDiff() {
    if (
      !selectedProjectId ||
      !selectedMappingTemplateId ||
      !diffLeftSourceId ||
      !diffRightSourceId
    ) return;
    const result = await run(
      t("busyDiffingMapping"),
      () =>
        api.diffMappingTemplate(
          selectedProjectId,
          selectedMappingTemplateId,
          diffLeftSourceId,
          diffRightSourceId
        ),
      { area: "mappingDiff" }
    );
    if (result) setMappingDiff(result);
  }

  async function addTagToRecording(recordingId: string) {
    const tag = tagInput.trim();
    if (!tag) return;
    const updated = await run(
      t("busyUpdatingTag"),
      () => api.patchRecording(recordingId, { add_tags: [tag] }),
      { area: "recordings" }
    );
    if (updated) {
      setTagInput("");
      void refreshProjectData(updated.project_id, false, { blockUi: false });
    }
  }

  async function runQuery() {
    if (!selectedProjectId) return;
    const params = thresholdTemplates.has(selectedQueryTemplate)
      ? { threshold: Number(queryThreshold) }
      : {};
    const result = await run(
      t("busyRunningQuery"),
      () =>
        api.query(
          selectedProjectId,
          selectedQueryTemplate,
          selectedQueryRecording ? [selectedQueryRecording] : [],
          params
        ),
      { area: "query" }
    );
    if (result) setQueryResult(result);
  }

  async function exportQuery() {
    if (!selectedProjectId) return;
    const params = thresholdTemplates.has(selectedQueryTemplate)
      ? { threshold: Number(queryThreshold) }
      : {};
    const result = await run(
      t("busyExportingQuery"),
      () =>
        api.exportQuery(
          selectedProjectId,
          selectedQueryTemplate,
          selectedQueryRecording ? [selectedQueryRecording] : [],
          params,
          "csv"
        ),
      { area: "query" }
    );
    if (result) setExportPath(result.path);
  }

  async function runCustomQuery() {
    if (!selectedProjectId) return;
    const filters = {
      entity_path: customQueryEntityPath.trim() || undefined,
      key: customQueryKey.trim() || undefined,
      text: customQueryText.trim() || undefined,
      operator: customQueryOperator,
      value: customQueryValue.trim() || undefined,
      time_start: customQueryTimeStart.trim() || undefined,
      time_end: customQueryTimeEnd.trim() || undefined
    };
    const semanticTypes = customQuerySemanticTypes
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
    const result = await run(
      t("busyRunningQuery"),
      () =>
        api.customQuery(
          selectedProjectId,
          selectedQueryRecording ? [selectedQueryRecording] : [],
          semanticTypes,
          filters
        ),
      { area: "query" }
    );
    if (result) setQueryResult(result);
  }

  async function runDiagnostics(
    recordingIds: string[],
    thresholds: DiagnosticThresholds,
    preset = "balanced"
  ) {
    if (!selectedProjectId) return;
    const result = await run(
      t("busyRunningDiagnostics"),
      () => api.diagnostics(selectedProjectId, recordingIds, thresholds, preset),
      { area: "diagnostics" }
    );
    if (result) setDiagnosticReport(result);
  }

  async function exportDiagnostics(
    recordingIds: string[],
    thresholds: DiagnosticThresholds,
    preset: string,
    format: "json" | "csv" | "html"
  ) {
    if (!selectedProjectId) return;
    const result = await run(
      t("busyExportingDiagnostics"),
      () => api.exportDiagnostics(selectedProjectId, recordingIds, thresholds, preset, format),
      { area: "diagnostics" }
    );
    if (result) {
      setDiagnosticExportResult(result);
      await refreshDiagnosticData(selectedProjectId);
    }
  }

  async function installPlugin() {
    if (!pluginPath.trim()) return;
    const result = await run(
      t("busyInstallingPlugin"),
      () => api.installPlugin(pluginPath.trim()),
      { area: "extensions" }
    );
    if (result) {
      setPluginPath("");
      refreshExtensionData();
    }
  }

  async function installTemplate() {
    if (!templatePath.trim()) return;
    const result = await run(
      t("busyInstallingTemplate"),
      () => api.installTemplate(templatePath.trim()),
      { area: "extensions" }
    );
    if (result) {
      setTemplatePath("");
      refreshExtensionData();
    }
  }

  async function runBatchImport() {
    if (!selectedProjectId || !batchPattern.trim()) return;
    const patterns = parseBatchPatterns();
    const result = await run(
      t("busyRunningBatch"),
      () =>
        api.batchImport(
          selectedProjectId,
          patterns,
          selectedTemplateId,
          batchOutputPrefix,
          batchStorageMode
        ),
      { area: "batch" }
    );
    if (result) {
      upsertJob(result);
      setBatchResult(null);
      setBatchEstimate("");
      await refreshProjectData(selectedProjectId);
    }
  }

  function parseBatchPatterns() {
    return batchPattern
      .split("\n")
      .map((value) => value.trim())
      .filter(Boolean);
  }

  async function estimateBatchImport() {
    if (!selectedProjectId || !batchPattern.trim()) return;
    const result = await run(
      t("busyEstimatingBatch"),
      () => api.estimateBatchImport(selectedProjectId, parseBatchPatterns(), batchStorageMode),
      { area: "batch" }
    );
    if (result) {
      const free = result.free === null ? "-" : result.free.toLocaleString();
      setBatchEstimate(
        `${result.required.toLocaleString()} bytes required / ${free} bytes free (${result.confidence})`
      );
    }
  }

  async function selectBatch(batchId: string) {
    if (!batchId) {
      setSelectedBatch(null);
      return;
    }
    const result = await run(
      t("busyRefreshingWorkspace"),
      () => api.batch(batchId),
      { area: "batch" }
    );
    if (result) setSelectedBatch(result);
  }

  async function retryBatchItem(batchId: string, itemId: string) {
    const result = await run(
      t("busyRetryingJob"),
      () => api.retryBatchItem(batchId, itemId),
      { area: "batch" }
    );
    if (result) {
      upsertJob(result);
      await refreshProjectData(selectedProjectId);
      await selectBatch(batchId);
    }
  }

  async function cancelBatchItem(batchId: string, itemId: string) {
    const result = await run(
      t("busyCancellingJob"),
      () => api.cancelBatchItem(batchId, itemId),
      { area: "batch" }
    );
    if (result) {
      setSelectedBatch(result);
      await refreshProjectData(selectedProjectId);
    }
  }

  async function updateMaxWorkers(maxWorkers: number) {
    const next = Math.min(4, Math.max(1, maxWorkers));
    const result = await run(
      t("busySavingSettings"),
      () => api.updateJobSettings(next),
      { area: "settings" }
    );
    if (result) {
      window.localStorage.setItem(JOB_SETTINGS_STORAGE_KEY, String(result.max_workers));
      setJobSettings(result);
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
    const result = await run(
      t("busyComparing"),
      () => api.compare(selectedProjectId, recordingIds, metricKeys, "summary"),
      { area: "compare" }
    );
    if (result) setCompareResult(result);
  }

  async function exportProject() {
    if (!selectedProjectId) return;
    const outputPath = normalizeSourcePathInput(defaultExportDir);
    if (outputPath !== defaultExportDir) {
      setDefaultExportDir(outputPath);
    }
    const result = await run(
      t("busyExportingProject"),
      () => api.exportProject(selectedProjectId, outputPath || undefined),
      { area: "dashboard" }
    );
    if (result) setProjectExport(result);
  }

  async function chooseExportFolder() {
    if (!isTauriRuntime()) {
      showAreaError("settings", t("errorPickerUnavailable"));
      return;
    }
    const selected = await run(
      t("busySelectingExportFolder"),
      () =>
        openDialog({
          title: t("selectExportFolder"),
          directory: true,
          multiple: false,
          recursive: false
        }),
      { area: "settings" }
    );
    const selectedPath = Array.isArray(selected) ? selected[0] : selected;
    if (selectedPath) {
      setDefaultExportDir(normalizeSourcePathInput(selectedPath));
      clearAreaError("settings");
    }
  }

  async function chooseArtifactFolder(area: "build" | "settings" = "settings") {
    if (!isTauriRuntime()) {
      showAreaError(area, t("errorPickerUnavailable"));
      return;
    }
    const selected = await run(
      t("busySelectingArtifactFolder"),
      () =>
        openDialog({
          title: t("selectArtifactFolder"),
          directory: true,
          multiple: false,
          recursive: false
        }),
      { area }
    );
    const selectedPath = Array.isArray(selected) ? selected[0] : selected;
    if (selectedPath) {
      setDefaultArtifactDir(normalizeSourcePathInput(selectedPath));
      clearAreaError(area);
    }
  }

  async function openProjectPackage() {
    if (!isTauriRuntime()) {
      showAreaError("dashboard", t("errorPickerUnavailable"));
      return;
    }
    const selected = await run(
      t("busyOpeningPackage"),
      () =>
        openDialog({
          title: t("selectProjectPackage"),
          multiple: false,
          filters: [
            {
              name: "DataScope Project Package",
              extensions: ["zip"]
            }
          ]
        }),
      { area: "dashboard" }
    );
    const selectedPath = Array.isArray(selected) ? selected[0] : selected;
    if (!selectedPath) return;
    const packagePath = normalizeSourcePathInput(selectedPath);
    const result = await run(
      t("busyOpeningPackage"),
      () => api.importProjectPackage(packagePath),
      { area: "dashboard" }
    );
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
      setActiveBuildJobId("");
      setIsBuildSubmitting(false);
      setProjectSources([]);
      setMappingDiff(null);
      setOpenedPackagePath(result.package_path);
      clearAreaError("dashboard");
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
    if (droppedPath) {
      const normalizedPath = normalizeSourcePathInput(droppedPath);
      setSourcePath(normalizedPath);
      setOutputName(defaultOutputName(normalizedPath));
      clearAreaError("import");
    }
  }

  async function chooseSource(kind: "file" | "folder") {
    setSourcePickerOpen(false);
    if (!isTauriRuntime()) {
      showAreaError("import", t("errorPickerUnavailable"));
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
              ? sourceFileDialogFilters
              : undefined
        }),
      { area: "import" }
    );
    const selectedPath = Array.isArray(selected) ? selected[0] : selected;
    if (selectedPath) {
      const normalizedPath = normalizeSourcePathInput(selectedPath);
      setSourcePath(normalizedPath);
      setOutputName(defaultOutputName(normalizedPath, kind));
      clearAreaError("import");
    }
  }

  const latestRecordingOpening = Boolean(
    (buildResult?.recording_id && openingRecordingIds.has(buildResult.recording_id)) ||
      (latestRecording?.id && openingRecordingIds.has(latestRecording.id))
  );

  const navigationProps = {
    activeSection,
    busy,
    projects,
    selectedProject,
    selectedProjectId,
    projectName,
    projectError: areaErrors.project,
    recordingCount: recordings.length,
    jobCount: jobs.length,
    templateCount: templateRegistry.length,
    t,
    onRefreshAll: () => void refreshAll(),
    onSectionChange: goToSection,
    onRefreshProjects: () => void refreshProjects(),
    onSelectedProjectChange: setSelectedProjectId,
    onProjectNameChange: (name: string) => {
      setProjectName(name);
      clearAreaError("project");
    },
    onCreateProject: () => void createProject()
  };

  return (
    <main className="app-shell">
      <AppTopbar {...navigationProps} />

      <div className="app-frame">
        <AppSidebar {...navigationProps} />

        <section className="workspace">
          {activeSection === "dashboard" && (
            <DashboardSection
              selectedProject={selectedProject}
              latestRecording={latestRecording}
              latestJob={latestJob}
              recordings={recordings}
              streamCount={streams.length}
              jobCount={jobs.length}
              sourcePickerOpen={sourcePickerOpen}
              dragActive={dragActive}
              sourcePath={sourcePath}
              sourceStorageMode={sourceStorageMode}
              csvHeaderMode={csvHeaderMode}
              csvColumnNames={csvColumnNames}
              isBusy={isBusy}
              isLatestRecordingOpening={latestRecordingOpening}
              openingRecordingIds={openingRecordingIds}
              importError={areaErrors.import}
              dashboardError={areaErrors.dashboard}
              projectExport={projectExport}
              openedPackagePath={openedPackagePath}
              buildResult={buildResult}
              diagnosticReport={diagnosticReport}
              language={language}
              t={t}
              onToggleSourcePicker={() => setSourcePickerOpen((value) => !value)}
              onChooseSource={(kind) => void chooseSource(kind)}
              onImport={() => void importAndInspect()}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onSourcePathChange={(value) => {
                setSourcePath(value);
                clearAreaError("import");
              }}
              onStorageModeChange={setSourceStorageMode}
              onCsvHeaderModeChange={setCsvHeaderMode}
              onCsvColumnNamesChange={setCsvColumnNames}
              onRefresh={() => void refreshProjectData()}
              onExportProject={() => void exportProject()}
              onOpenPackage={() => void openProjectPackage()}
              onOpenLatest={() => void openInRerun()}
              onOpenRecording={(recording) => void openRecording(recording)}
            />
          )}

          {activeSection === "import" && (
            <ImportWorkflowSection
              selectedTemplateId={selectedTemplateId}
              templateOptions={templateOptions}
              selectedMappingTemplateId={selectedMappingTemplateId}
              mappingTemplates={mappingTemplates}
              mappingTemplateName={mappingTemplateName}
              source={source}
              streams={streams}
              mapping={mapping}
              schemaProfile={schemaProfile}
              mappingValidation={mappingValidation}
              mappingConfirmed={mappingConfirmed}
              savedMappingId={savedMappingId}
              mappingDiff={mappingDiff}
              projectSources={projectSources}
              diffLeftSourceId={diffLeftSourceId}
              diffRightSourceId={diffRightSourceId}
              supportedSemanticTypes={supportedSemanticTypes}
              timeUnits={timeUnits}
              outputNameRef={outputNameRef}
              outputName={outputName}
              artifactOutputDir={defaultArtifactDir}
              mcapDecoders={mcapDecoders}
              rrdOptimizeProfile={rrdOptimizeProfile}
              artifactValidation={artifactValidation}
              catalogEnabled={catalogEnabled}
              catalogDataset={catalogDataset}
              catalogManagedLocal={catalogManagedLocal}
              catalogServerUrl={catalogServerUrl}
              rerun033Available={Boolean(apiStatus?.rerun_features?.rerun_033)}
              buildResult={buildResult}
              buildJob={buildJob}
              isBuildSubmitting={isBuildSubmitting}
              previewRows={previewRows}
              previewText={previewText}
              isBusy={isBusy}
              language={language}
              errors={areaErrors}
              t={t}
              onTemplateChange={(value) => void changeTemplate(value)}
              onSelectedMappingTemplateChange={(value) => {
                setSelectedMappingTemplateId(value);
                clearAreaError("mappingToolbar");
              }}
              onApplyMappingTemplate={() => void applySelectedMappingTemplate()}
              onMappingTemplateNameChange={(value) => {
                setMappingTemplateName(value);
                clearAreaError("mappingToolbar");
              }}
              onCreateMappingTemplate={() => void createCurrentMappingTemplate()}
              onUpdateTimeline={updateTimeline}
              onUpdateMappingStream={updateMappingStream}
              onApplyMappingSuggestion={applyMappingSuggestion}
              onSaveMapping={() => void saveMapping()}
              onValidateMapping={() => void validateCurrentMapping()}
              onConfirmMapping={() => void confirmCurrentMapping()}
              onDiffLeftSourceChange={(value) => {
                setDiffLeftSourceId(value);
                clearAreaError("mappingDiff");
              }}
              onDiffRightSourceChange={(value) => {
                setDiffRightSourceId(value);
                clearAreaError("mappingDiff");
              }}
              onRunMappingDiff={() => void runMappingDiff()}
              onOutputNameChange={(value) => {
                setOutputName(value);
                clearAreaError("build");
              }}
              onArtifactOutputDirChange={(value) => {
                setDefaultArtifactDir(value);
                clearAreaError("build");
              }}
              onMcapDecodersChange={(value) => {
                setMcapDecoders(value);
                clearAreaError("build");
              }}
              onRrdOptimizeProfileChange={(value) => {
                setRrdOptimizeProfile(value);
                clearAreaError("build");
              }}
              onArtifactValidationChange={(value) => {
                setArtifactValidation(value);
                clearAreaError("build");
              }}
              onCatalogEnabledChange={(value) => {
                setCatalogEnabled(value);
                clearAreaError("build");
              }}
              onCatalogDatasetChange={(value) => {
                setCatalogDataset(value);
                clearAreaError("build");
              }}
              onCatalogManagedLocalChange={(value) => {
                setCatalogManagedLocal(value);
                clearAreaError("build");
              }}
              onCatalogServerUrlChange={(value) => {
                setCatalogServerUrl(value);
                clearAreaError("build");
              }}
              onChooseArtifactOutputFolder={() => void chooseArtifactFolder("build")}
              onBuildRecording={() => void buildRecording()}
              onShowBuildJobDetails={(job) => openErrorDialog(buildJobError(job), "build")}
              onOpenInRerun={() => void openInRerun()}
            />
          )}

          {activeSection === "recordings" && (
            <RecordingsQueriesSection
              recordings={recordings}
              visibleRecordings={visibleRecordings}
              tagInput={tagInput}
              queryTemplates={queryTemplates}
              selectedQueryTemplate={selectedQueryTemplate}
              selectedQueryRecording={selectedQueryRecording}
              queryRecordingOptions={queryRecordingOptions}
              thresholdTemplates={thresholdTemplates}
              queryThreshold={queryThreshold}
              customQueryEntityPath={customQueryEntityPath}
              customQueryKey={customQueryKey}
              customQueryText={customQueryText}
              customQuerySemanticTypes={customQuerySemanticTypes}
              customQueryOperator={customQueryOperator}
              customQueryValue={customQueryValue}
              customQueryTimeStart={customQueryTimeStart}
              customQueryTimeEnd={customQueryTimeEnd}
              selectedProjectId={selectedProjectId}
              exportPath={exportPath}
              queryResult={queryResult}
              compareRecordingIds={compareRecordingIds}
              compareMetric={compareMetric}
              compareResult={compareResult}
              jobs={jobs}
              visibleJobs={visibleJobs}
              isBusy={isBusy}
              openingRecordingIds={openingRecordingIds}
              language={language}
              errors={areaErrors}
              t={t}
              onTagInputChange={(value) => {
                setTagInput(value);
                clearAreaError("recordings");
              }}
              onOpenRecording={(recording) => void openRecording(recording)}
              onAddTag={(recordingId) => void addTagToRecording(recordingId)}
              onQueryTemplateChange={(value) => {
                setSelectedQueryTemplate(value);
                clearAreaError("query");
              }}
              onQueryRecordingChange={(value) => {
                setSelectedQueryRecording(value);
                clearAreaError("query");
              }}
              onQueryThresholdChange={(value) => {
                setQueryThreshold(value);
                clearAreaError("query");
              }}
              onRunQuery={() => void runQuery()}
              onExportQuery={() => void exportQuery()}
              onCustomQueryEntityPathChange={(value) => {
                setCustomQueryEntityPath(value);
                clearAreaError("query");
              }}
              onCustomQueryKeyChange={(value) => {
                setCustomQueryKey(value);
                clearAreaError("query");
              }}
              onCustomQueryTextChange={(value) => {
                setCustomQueryText(value);
                clearAreaError("query");
              }}
              onCustomQuerySemanticTypesChange={(value) => {
                setCustomQuerySemanticTypes(value);
                clearAreaError("query");
              }}
              onCustomQueryOperatorChange={(value) => {
                setCustomQueryOperator(value);
                clearAreaError("query");
              }}
              onCustomQueryValueChange={(value) => {
                setCustomQueryValue(value);
                clearAreaError("query");
              }}
              onCustomQueryTimeStartChange={(value) => {
                setCustomQueryTimeStart(value);
                clearAreaError("query");
              }}
              onCustomQueryTimeEndChange={(value) => {
                setCustomQueryTimeEnd(value);
                clearAreaError("query");
              }}
              onRunCustomQuery={() => void runCustomQuery()}
              onCompareRecordingIdsChange={(value) => {
                setCompareRecordingIds(value);
                clearAreaError("compare");
              }}
              onCompareMetricChange={(value) => {
                setCompareMetric(value);
                clearAreaError("compare");
              }}
              onRunCompare={() => void runCompare()}
              onCancelJob={(job) => void cancelJob(job)}
              onRetryJob={(job) => void retryJob(job)}
            />
          )}

          {activeSection === "diagnostics" && (
            <DiagnosticsSection
              selectedProjectId={selectedProjectId}
              recordings={recordings}
              report={diagnosticReport}
              presets={diagnosticPresets}
              exports={diagnosticExports}
              exportResult={diagnosticExportResult}
              isBusy={isBusy}
              errors={areaErrors}
              t={t}
              onRun={(recordingIds, thresholds, preset) =>
                void runDiagnostics(recordingIds, thresholds, preset)
              }
              onExport={(recordingIds, thresholds, preset, format) =>
                void exportDiagnostics(recordingIds, thresholds, preset, format)
              }
            />
          )}

          <ExtensionsSections
            activeSection={activeSection}
            selectedProjectId={selectedProjectId}
            batchPattern={batchPattern}
            batchOutputPrefix={batchOutputPrefix}
            batchStorageMode={batchStorageMode}
            batchResult={batchResult}
            batches={batches}
            selectedBatch={selectedBatch}
            batchEstimate={batchEstimate}
            jobSettings={jobSettings}
            pluginPath={pluginPath}
            templatePath={templatePath}
            mappingTemplates={mappingTemplates}
            selectedMappingTemplateId={selectedMappingTemplateId}
            mappingTemplatePath={mappingTemplatePath}
            mappingTemplateExportPath={mappingTemplateExportPath}
            mappingTemplateJson={mappingTemplateJson}
            plugins={plugins}
            templateRegistry={templateRegistry}
            recipes={recipes}
            visiblePlugins={visiblePlugins}
            visibleTemplateRegistry={visibleTemplateRegistry}
            language={language}
            defaultExportDir={defaultExportDir}
            defaultArtifactDir={defaultArtifactDir}
            diagnosticLogDir={apiStatus?.log_dir ?? ""}
            desktopLogPath={apiStatus?.desktop_log_path ?? ""}
            backendLogPath={apiStatus?.backend_log_path ?? ""}
            isBusy={isBusy}
            batchError={areaErrors.batch}
            extensionsError={areaErrors.extensions}
            mappingTemplatesError={areaErrors.mappingTemplates}
            settingsError={areaErrors.settings}
            t={t}
            onBatchPatternChange={(value) => {
              setBatchPattern(value);
              clearAreaError("batch");
            }}
            onBatchOutputPrefixChange={(value) => {
              setBatchOutputPrefix(value);
              clearAreaError("batch");
            }}
            onBatchStorageModeChange={setBatchStorageMode}
            onRunBatch={() => void runBatchImport()}
            onEstimateBatch={() => void estimateBatchImport()}
            onSelectBatch={(batchId) => void selectBatch(batchId)}
            onRetryBatchItem={(batchId, itemId) => void retryBatchItem(batchId, itemId)}
            onCancelBatchItem={(batchId, itemId) => void cancelBatchItem(batchId, itemId)}
            onPluginPathChange={(value) => {
              setPluginPath(value);
              clearAreaError("extensions");
            }}
            onInstallPlugin={() => void installPlugin()}
            onTemplatePathChange={(value) => {
              setTemplatePath(value);
              clearAreaError("extensions");
            }}
            onInstallTemplate={() => void installTemplate()}
            onMappingTemplatePathChange={(value) => {
              setMappingTemplatePath(value);
              clearAreaError("mappingTemplates");
            }}
            onImportMappingTemplate={() => void importMappingTemplate()}
            onSelectedMappingTemplateChange={(value) => {
              setSelectedMappingTemplateId(value);
              clearAreaError("mappingTemplates");
            }}
            onMappingTemplateExportPathChange={(value) => {
              setMappingTemplateExportPath(value);
              clearAreaError("mappingTemplates");
            }}
            onExportMappingTemplate={() => void exportSelectedMappingTemplate()}
            onDeleteMappingTemplate={() => void deleteSelectedMappingTemplate()}
            onMappingTemplateJsonChange={(value) => {
              setMappingTemplateJson(value);
              clearAreaError("mappingTemplates");
            }}
            onSaveMappingTemplate={() => void saveMappingTemplateConfig()}
            onLanguageChange={setLanguage}
            onDefaultExportDirChange={(value) => {
              setDefaultExportDir(value);
              clearAreaError("settings");
            }}
            onChooseExportFolder={() => void chooseExportFolder()}
            onDefaultArtifactDirChange={(value) => {
              setDefaultArtifactDir(value);
              clearAreaError("settings");
            }}
            onChooseArtifactFolder={() => void chooseArtifactFolder("settings")}
            onJobSettingsChange={(maxWorkers) => void updateMaxWorkers(maxWorkers)}
          />
        </section>
      </div>
      {globalNotification && (
        <GlobalErrorToast
          notification={globalNotification}
          t={t}
          onDismiss={() => setGlobalNotification(null)}
          onDetails={(error) => openErrorDialog(error, "global", globalNotification.retry)}
          onRetry={() => {
            const retry = globalNotification.retry;
            setGlobalNotification(null);
            retry?.();
          }}
        />
      )}
      <ErrorDialog
        request={errorDialog}
        t={t}
        onClose={() => setErrorDialog(null)}
        onRetry={(request) => {
          setErrorDialog(null);
          request.retry?.();
        }}
      />
    </main>
  );
}

export default StudioWorkspace;

function parseListInput(value: string): string[] | null {
  const items = value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  return items.length ? items : null;
}
