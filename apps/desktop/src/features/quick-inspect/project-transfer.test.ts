import { describe, expect, it, vi } from "vitest";
import { api, type ImportWorkflowResult } from "../../api";
import type { MappingPayload } from "../../types";
import { createProjectTransfer, type TransferInput } from "./project-transfer";

function mapping(id: string, source: string, recording: string): MappingPayload {
  return { mapping: { id, source, recording_id: recording, schema_version: 2,
    status: "confirmed", app_id: "datascope.sensor_monitor.v1", template_id: "sensor_monitor",
    timelines: { primary: { name: "timestamp", source_field: "timestamp", unit: "unix_ms", sort: "ascending", effective_unit: "unix_ms" } },
    streams: [{ stream_id: "stream_temperature", source_fields: ["temperature"], semantic_type: "scalar",
      entity_path: "/custom/temperature", archetype: "Scalars", view: "TimeSeriesView", confidence: 1,
      enabled: false, required: true, origin: "user", rule_key: "custom" }]
  } };
}

function setup() {
  const target = mapping("mapping_new", "source_new", "recording_new");
  const imported = { source: { id: "source_new" }, mapping: target, saved_mapping: { id: "mapping_new" },
    validation: { valid: true }, template_id: "sensor_monitor" } as unknown as ImportWorkflowResult;
  const client = { ...api,
    createProject: vi.fn().mockResolvedValue({ id: "project_new", name: "Saved" }),
    importWorkflow: vi.fn().mockResolvedValue(imported),
    saveMapping: vi.fn().mockResolvedValue({ id: "mapping_new", path: "/target/mapping.yaml" }),
    previewMapping: vi.fn().mockImplementation(async (_id, value) => ({ mapping: value,
      validation: { valid: false, errors: [{ code: "field_missing" }] }, preview: { rows: [] }, schema_profile: {} }))
  };
  const input: TransferInput = { sessionId: "session_old", sourcePath: "/original/run.csv",
    importOptions: { csv: { header_mode: "no_header", column_names: ["timestamp", "temperature"] } },
    storageMode: "reference", projectId: "", projectName: "Saved", templateId: "sensor_monitor",
    mapping: mapping("mapping_old", "source_old", "recording_old") };
  return { client, input, transfer: createProjectTransfer(client) };
}

describe("move quick inspect into a project", () => {
  it("preserves edits, uses fresh identifiers and keeps invalid mappings for repair", async () => {
    const { client, input, transfer } = setup();
    const original = structuredClone(input.mapping);
    const result = await transfer.run(input);
    expect(client.importWorkflow).toHaveBeenCalledWith("project_new", input.sourcePath, "reference", input.importOptions, "sensor_monitor");
    const saved = client.saveMapping.mock.calls[0][1];
    expect(saved).toMatchObject({ id: "mapping_new", source: "source_new", recording_id: "recording_new", status: "draft" });
    expect(saved.streams).toEqual(original.mapping.streams);
    expect(saved.timelines.primary).toEqual({ name: "timestamp", source_field: "timestamp", unit: "unix_ms", sort: "ascending" });
    expect(result.inspection.validation.valid).toBe(false);
    expect(input.mapping).toEqual(original);
  });

  it("retries the mapping step without creating another project or source", async () => {
    const { client, input, transfer } = setup();
    client.saveMapping.mockRejectedValueOnce(new Error("temporary save error"));
    await expect(transfer.run(input)).rejects.toThrow("temporary save error");
    await transfer.run(input);
    expect(client.createProject).toHaveBeenCalledTimes(1);
    expect(client.importWorkflow).toHaveBeenCalledTimes(1);
    expect(client.saveMapping).toHaveBeenCalledTimes(2);
  });

  it("deduplicates double submission and supports a copied source in an existing project", async () => {
    const { client, input, transfer } = setup();
    input.projectId = "existing"; input.storageMode = "copy";
    const first = transfer.run(input);
    expect(transfer.run(input)).toBe(first);
    await first;
    expect(client.createProject).not.toHaveBeenCalled();
    expect(client.importWorkflow).toHaveBeenCalledTimes(1);
    expect(client.importWorkflow.mock.calls[0].slice(0, 3)).toEqual(["existing", "/original/run.csv", "copy"]);
  });
});
