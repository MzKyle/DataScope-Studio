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
};

export type MappingValidation = {
  valid: boolean;
  errors: MappingValidationIssue[];
  warnings: MappingValidationIssue[];
  issues: MappingValidationIssue[];
  summary: { errors: number; warnings: number };
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
  params: Record<string, unknown>;
  created_at: string;
};

export type Job = {
  id: string;
  project_id: string;
  type: string;
  status: string;
  progress: number;
  log_path?: string | null;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
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

export type BatchItem = {
  id: string;
  batch_id: string;
  source_path: string;
  source_id?: string | null;
  recording_id?: string | null;
  status: string;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
};

export type BatchResult = {
  id: string;
  project_id: string;
  status: string;
  total: number;
  succeeded: number;
  failed: number;
  created_at: string;
  updated_at: string;
  items: BatchItem[];
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
