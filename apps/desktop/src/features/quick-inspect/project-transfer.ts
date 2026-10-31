import { api, type ImportWorkflowResult } from "../../api";
import type { MappingPayload, Project } from "../../types";

export type TransferInput = {
  sessionId: string;
  sourcePath: string;
  importOptions: Record<string, unknown>;
  storageMode: "copy" | "reference";
  projectId: string;
  projectName: string;
  mapping: MappingPayload;
  templateId: string;
};

/** Retain successful steps across retries without migrating temporary artifacts. */
export function createProjectTransfer(client = api) {
  const projects = new Map<string, Project>();
  const imports = new Map<string, ImportWorkflowResult>();
  let running: Promise<{ projectId: string; project?: Project; inspection: ImportWorkflowResult }> | null = null;
  async function transfer(input: TransferInput) {
    const projectKey = `${input.sessionId}:${input.projectName}`;
    let project = projects.get(projectKey);
    if (!input.projectId && !project) {
      project = await client.createProject(input.projectName);
      projects.set(projectKey, project);
    }
    const projectId = input.projectId || project!.id;
    const key = `${input.sessionId}:${projectId}:${input.storageMode}`;
    let imported = imports.get(key);
    if (!imported) {
      imported = await client.importWorkflow(projectId, input.sourcePath, input.storageMode, input.importOptions, input.templateId);
      imports.set(key, imported);
    }
    const mapping = structuredClone(input.mapping.mapping);
    mapping.id = imported.mapping.mapping.id;
    mapping.source = imported.source.id;
    mapping.recording_id = imported.mapping.mapping.recording_id;
    mapping.template_id = input.templateId;
    mapping.status = "draft";
    delete mapping.timelines.primary.effective_unit;
    const saved = await client.saveMapping(imported.source.id, mapping, false);
    const preview = await client.previewMapping(imported.source.id, mapping);
    return {
      projectId, project: input.projectId ? undefined : project,
      inspection: { ...imported, template_id: input.templateId, mapping: { mapping: preview.mapping },
        saved_mapping: { ...imported.saved_mapping, ...saved }, preview: preview.preview,
        schema_profile: preview.schema_profile, validation: preview.validation }
    };
  }
  return {
    run(input: TransferInput) {
      if (!running) running = transfer(input).finally(() => { running = null; });
      return running;
    }
  };
}
