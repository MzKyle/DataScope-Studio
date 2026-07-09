export const queryKeys = {
  apiStatus: () => ["api-status"] as const,
  batches: (projectId: string) => ["projects", projectId, "batches"] as const,
  diagnosticExports: (projectId: string) => ["projects", projectId, "diagnostics", "exports"] as const,
  diagnosticPresets: (projectId: string) => ["projects", projectId, "diagnostics", "presets"] as const,
  extensionRegistry: () => ["extensions", "registry"] as const,
  jobSettings: () => ["job-settings"] as const,
  jobs: (projectId: string) => ["projects", projectId, "jobs"] as const,
  mappingTemplates: () => ["mapping-templates"] as const,
  plugins: () => ["plugins"] as const,
  project: (projectId: string) => ["projects", projectId] as const,
  projectData: (projectId: string, includeQueryTemplates: boolean) =>
    ["projects", projectId, "workspace", { includeQueryTemplates }] as const,
  projects: () => ["projects"] as const,
  queryTemplates: (projectId: string) => ["projects", projectId, "query-templates"] as const,
  recipes: () => ["recipes"] as const,
  recordings: (projectId: string) => ["projects", projectId, "recordings"] as const,
  sources: (projectId: string) => ["projects", projectId, "sources"] as const,
  templateRegistry: () => ["templates"] as const
};
