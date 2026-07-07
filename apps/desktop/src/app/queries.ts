import { useQuery } from "@tanstack/react-query";

import { api } from "../api";
import { queryKeys } from "./query-keys";

export function useApiStatusQuery(enabled: boolean) {
  return useQuery({
    enabled,
    queryFn: () => api.status(),
    queryKey: queryKeys.apiStatus()
  });
}

export function useProjectsQuery() {
  return useQuery({
    queryFn: () => api.projects(),
    queryKey: queryKeys.projects()
  });
}

export function useProjectDataQuery(projectId: string, includeQueryTemplates: boolean) {
  return useQuery({
    enabled: Boolean(projectId),
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
    queryKey: queryKeys.projectData(projectId, includeQueryTemplates)
  });
}

export function useDiagnosticDataQuery(projectId: string) {
  return useQuery({
    enabled: Boolean(projectId),
    queryFn: async () => {
      const [presetRows, exportRows] = await Promise.all([
        api.diagnosticPresets(projectId),
        api.diagnosticExports(projectId)
      ]);
      return { presetRows, exportRows };
    },
    queryKey: ["projects", projectId, "diagnostics"] as const
  });
}

export function useExtensionRegistryQuery(includePlugins = false) {
  return useQuery({
    queryFn: async () => {
      const [pluginRows, templateRows, mappingTemplateRows, recipeRows] = await Promise.all([
        includePlugins ? api.plugins() : Promise.resolve(null),
        api.templates(),
        api.mappingTemplates(),
        api.recipes()
      ]);
      return { pluginRows, templateRows, mappingTemplateRows, recipeRows };
    },
    queryKey: includePlugins ? queryKeys.extensionRegistry() : queryKeys.templateRegistry()
  });
}
