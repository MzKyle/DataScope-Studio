export type Project = {
  id: string;
  name: string;
  description: string;
  workspace_path: string;
  created_at: string;
  updated_at: string;
};

export type Source = {
  id: string;
  project_id: string;
  type: string;
  uri: string;
  storage_mode: "copy" | "reference";
  original_uri?: string | null;
  available?: boolean;
  checksum: string;
  size_bytes: number;
  status: string;
  metadata: Record<string, unknown>;
};

export type StreamInfo = {
  stream_id: string;
  name: string;
  semantic_type: string;
  fields: string[];
  time_key: string | null;
  confidence: number;
  metadata: Record<string, unknown>;
};

export type MappingStream = {
  stream_id: string;
  source_fields: string[];
  semantic_type: string;
  entity_path: string;
  archetype: string;
  view: string;
  confidence: number;
  time_key?: string;
  timeline_source_field?: string;
  name?: string;
  enabled: boolean;
  required: boolean;
  origin: string;
  rule_key: string;
  role?: string | null;
  expected_unit?: string | null;
  source_unit?: string | null;
  match_ambiguous?: boolean;
  match_candidates?: Array<{ field: string; candidates: string[] }>;
  template_missing_fields?: string[];
};

export type MappingPayload = {
  mapping: {
    schema_version: number;
    id: string;
    source: string;
    app_id: string;
    recording_id: string;
    template_id?: string | null;
    mapping_template_id?: string | null;
    status: "draft" | "confirmed";
    timelines: {
      primary: {
        name: string;
        source_field: string;
        unit: string;
        sort: "source" | "ascending";
        effective_unit?: string | null;
      };
    };
    streams: MappingStream[];
  };
};

export type SchemaProfile = {
  schema_version: number;
  source_id: string;
  source_type: string;
  source_family: string;
  sample_rows?: number | null;
  field_names: string[];
  fields: Array<{
    name: string;
    dtype: string;
    null_count: number;
    null_ratio: number;
    non_null_count?: number | null;
    axis?: string | null;
  }>;
  timeline: Record<string, unknown>;
  adapter_metadata: Record<string, unknown>;
};

export type MappingValidationIssue = {
  severity: "error" | "warning";
  code: string;
  message?: string;
  stream_id?: string | null;
  rule_key?: string | null;
  field?: string | null;
  candidates?: string[];
  recommendation?: string;
  suggestions?: MappingSuggestion[];
};

export type MappingSuggestionAction =
  | "set_timeline_field"
  | "set_timeline_unit"
  | "set_timeline_sort"
  | "replace_source_field"
  | "set_source_fields"
  | "set_entity_path"
  | "set_semantic_type"
  | "set_stream_enabled";

export type MappingSuggestion = {
  action: MappingSuggestionAction;
  label: string;
  params: {
    field?: string;
    unit?: string;
    sort?: "source" | "ascending";
    stream_id?: string;
    old_field?: string;
    new_field?: string;
    fields?: string[];
    entity_path?: string;
    semantic_type?: string;
    enabled?: boolean;
  };
};

export type MappingValidation = {
  valid: boolean;
  errors: MappingValidationIssue[];
  warnings: MappingValidationIssue[];
  issues: MappingValidationIssue[];
  summary: { errors: number; warnings: number };
  source_family?: string;
  supported_semantic_types?: string[];
  effective_timeline_unit: string;
};

export type MappingTemplateItem = {
  id: string;
  name: string;
  version: string;
  source_family: string;
  visual_template_id: string;
  path: string;
  config: {
    mapping_template: {
      schema_version: number;
      id: string;
      name: string;
      version: string;
      source_family: string;
      visual_template_id: string;
      timeline: Record<string, unknown>;
      rules: Array<Record<string, unknown>>;
    };
  };
  enabled: boolean;
  installed_at: string;
  updated_at: string;
};

export type MappingDiff = {
  template_id: string;
  left_source_id: string;
  right_source_id: string;
  timeline: Record<string, unknown>;
  rows: Array<{
    rule_key: string;
    status: string;
    changes: string[];
    left: MappingStream | null;
    right: MappingStream | null;
  }>;
  left_issues: MappingValidationIssue[];
  right_issues: MappingValidationIssue[];
};

export type BuildResult = {
  job_id: string;
  status: string;
  recording_id: string;
  recording_path: string;
  blueprint_path: string;
  artifact_info?: RerunArtifactInfo;
};

export type CatalogRegistrationInfo = {
  enabled: boolean;
  dataset_name: string;
  server_url?: string | null;
  managed_local: boolean;
  status: string;
  recording_uri?: string;
};

export type RerunArtifactInfo = {
  recording_size_bytes: number;
  blueprint_size_bytes: number;
  app_id: string;
  template_id: string;
  rerun_recording_id: string;
  source_type: string;
  converter: string;
  rerun_version: string;
  mcap_decoders?: string[] | null;
  rrd_optimize_profile?: string;
  rrd_optimize?: Record<string, unknown>;
  artifact_validation?: string;
  artifact_checks?: Record<string, unknown>;
  catalog_registration?: CatalogRegistrationInfo;
};

export type RerunArtifactStatus = {
  status: "ready" | "missing" | "empty";
  message: string;
  recording_path: string;
  blueprint_path?: string | null;
  recording_size_bytes?: number | null;
  blueprint_size_bytes?: number | null;
};

export type TemplateMatch = {
  template_id: string;
  name: string;
  score: number;
};

export type Recording = {
  id: string;
  project_id: string;
  source_id?: string | null;
  source_type?: string | null;
  source_uri?: string | null;
  app_id: string;
  path: string;
  blueprint_id?: string | null;
  blueprint_path?: string | null;
  run_name: string;
  tags: string[];
  params: Record<string, unknown> & { rerun_artifact?: RerunArtifactInfo };
  artifact_status?: RerunArtifactStatus;
  created_at: string;
};

export type Job = {
  id: string;
  project_id: string;
  type: string;
  status:
    | "pending"
    | "running"
    | "cancel_requested"
    | "cancelled"
    | "succeeded"
    | "failed"
    | "interrupted";
  progress: number;
  stage?: string | null;
  payload: Record<string, unknown>;
  result: BuildResult | BatchResult | null;
  error?: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  } | null;
  attempt: number;
  retry_of_job_id?: string | null;
  resource_type?: string | null;
  resource_id?: string | null;
  worker_pid?: number | null;
  heartbeat_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  log_path?: string | null;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
};

export type DiskEstimate = {
  kind: "source_import" | "build" | "batch_import" | "project_export";
  estimated: number;
  margin: number;
  required: number;
  free: number | null;
  confidence: "high" | "medium" | "low";
  sufficient: boolean | null;
  warnings: string[];
};

export type QueryTemplate = {
  template_id: string;
  name: string;
  description: string;
  params: Record<string, unknown>;
};

export type QueryResult = {
  columns: string[];
  rows: Record<string, unknown>[];
};

export type QueryExportResult = {
  export_id: string;
  path: string;
  format: string;
  rows: number;
};

export type CustomQueryFilters = {
  entity_path?: string;
  key?: string;
  text?: string;
  operator?: "any" | "eq" | "contains" | "gt" | "gte" | "lt" | "lte";
  value?: string | number;
  time_start?: string | number;
  time_end?: string | number;
};

export type DiagnosticSeverity = "ok" | "warning" | "critical" | "info";

export type DiagnosticThresholds = {
  battery_low?: number;
  detection_confidence?: number;
  time_sync_warn_s?: number;
  time_sync_critical_s?: number;
  missing_ratio_warn?: number;
  missing_ratio_critical?: number;
  time_parse_ratio_warn?: number;
  time_gap_factor_warn?: number;
  outlier_iqr_multiplier?: number;
};

export type DiagnosticPreset = {
  id: string;
  name: string;
  description: string;
  thresholds: DiagnosticThresholds;
};

export type DiagnosticSummary = {
  health_score: number;
  severity: "ok" | "warning" | "critical";
  recording_count: number;
  source_count: number;
  topic_count: number;
  finding_count: number;
};

export type DiagnosticCheck = {
  id: string;
  name: string;
  status: "pass" | "warn" | "fail";
  severity: "ok" | "warning" | "critical";
  score: number;
  evidence: Record<string, unknown>;
  recommendation: string;
};

export type DiagnosticFinding = {
  id: string;
  category: string;
  severity: Exclude<DiagnosticSeverity, "ok">;
  recording_id?: string | null;
  source_id?: string | null;
  topic?: string | null;
  entity_path?: string | null;
  key?: string | null;
  message: string;
  evidence: Record<string, unknown>;
  recommendation: string;
};

export type DiagnosticReport = {
  project_id: string;
  thresholds: DiagnosticThresholds;
  summary: DiagnosticSummary;
  checks: DiagnosticCheck[];
  findings: DiagnosticFinding[];
};

export type DiagnosticExportResult = {
  export_id: string;
  project_id: string;
  path: string;
  format: "json" | "csv" | "html";
  recording_ids: string[];
  thresholds: DiagnosticThresholds;
  summary: DiagnosticSummary;
};

export type DiagnosticExport = {
  id: string;
  project_id: string;
  recording_ids: string[];
  thresholds: DiagnosticThresholds;
  summary: DiagnosticSummary;
  path: string;
  format: "json" | "csv" | "html";
  created_at: string;
};

export type Plugin = {
  id: string;
  name: string;
  version: string;
  path: string;
  status: string;
  manifest: Record<string, unknown>;
  installed_at: string;
  updated_at: string;
};

export type TemplateRegistryItem = {
  id: string;
  name: string;
  version: string;
  app_id: string;
  source: string;
  path?: string | null;
  manifest: Record<string, unknown>;
  enabled: boolean;
  installed_at: string;
  updated_at: string;
};

export type Recipe = {
  id: string;
  name: string;
  version: string;
  source_family: string;
  visual_template_id: string;
  mapping_template_id?: string | null;
  diagnostic_preset: string;
  recommended_queries: string[];
  description: string;
};

export type BatchItem = {
  id: string;
  batch_id: string;
  source_path: string;
  source_id?: string | null;
  recording_id?: string | null;
  status: BatchItemStatus;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
  attempt: number;
  cancel_requested_at?: string | null;
};

export type BatchItemStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "cancel_requested"
  | "cancelled";

export type BatchResult = {
  id: string;
  project_id: string;
  job_id?: string | null;
  status: string;
  template_id?: string;
  output_prefix?: string;
  storage_mode?: "copy" | "reference";
  patterns?: string[];
  total: number;
  succeeded: number;
  failed: number;
  cancelled: number;
  created_at: string;
  updated_at: string;
  items: BatchItem[];
};

export type BatchSummary = Omit<BatchResult, "items">;

export type JobSettings = {
  max_workers: number;
};

export type ProjectExportResult = {
  export_id: string;
  path: string;
  format: string;
  project_id: string;
};

export type ProjectImportResult = {
  project: Project;
  recordings: Recording[];
  recording_ids: string[];
  package_path: string;
};
