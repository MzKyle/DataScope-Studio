import { describe, expect, it, vi } from "vitest";

import { api, apiErrorFromResponse } from "./api";

describe("apiErrorFromResponse", () => {
  it("preserves structured artifact conflict details", () => {
    const error = apiErrorFromResponse(
      {
        error: {
          code: "artifact_name_conflict",
          message: "Output files already exist",
          output_name: "select",
          paths: ["/tmp/select.rrd", "/tmp/select.rbl"]
        }
      },
      409,
      "Conflict"
    );

    expect(error.status).toBe(409);
    expect(error.code).toBe("artifact_name_conflict");
    expect(error.message).toBe("Output files already exist");
    expect(error.details.output_name).toBe("select");
    expect(error.details.paths).toEqual(["/tmp/select.rrd", "/tmp/select.rbl"]);
  });

  it("reads errors nested under FastAPI detail", () => {
    const error = apiErrorFromResponse(
      {
        detail: {
          error: {
            code: "bad_request",
            message: "Invalid source"
          }
        }
      },
      400,
      "Bad Request"
    );

    expect(error.code).toBe("bad_request");
    expect(error.message).toBe("Invalid source");
  });

  it("posts diagnostics requests with selected recordings and thresholds", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          project_id: "project",
          thresholds: {
            battery_low: 0.2,
            detection_confidence: 0.5,
            time_sync_warn_s: 0.1,
            time_sync_critical_s: 1
          },
          summary: {
            health_score: 100,
            severity: "ok",
            recording_count: 1,
            source_count: 1,
            topic_count: 1,
            finding_count: 0
          },
          checks: [],
          findings: []
        }),
        { status: 200 }
      )
    );

    await api.diagnostics("project", ["recording_1"], { battery_low: 0.15 });

    const [, init] = fetchMock.mock.calls[0];
    expect(fetchMock.mock.calls[0][0]).toContain("/api/projects/project/diagnostics");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({
      recording_ids: ["recording_1"],
      thresholds: { battery_low: 0.15 },
      preset: "balanced",
      limit: 1000
    });
    fetchMock.mockRestore();
  });

  it("adds lightweight job list query parameters", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([]), { status: 200 })
    );

    await api.jobs("project", { limit: 50, activeOnly: true });

    expect(String(fetchMock.mock.calls[0][0])).toContain(
      "/api/projects/project/jobs?active_only=true&limit=50"
    );
    fetchMock.mockRestore();
  });

  it("posts source import workflow requests in one API round trip", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          source: {},
          streams: [],
          template_matches: [],
          template_id: "sensor_monitor",
          mapping: { mapping: {} },
          saved_mapping: { id: "mapping_1", path: "/tmp/mapping.yaml" },
          preview: { columns: [], rows: [] },
          schema_profile: {},
          validation: {}
        }),
        { status: 200 }
      )
    );

    await api.importWorkflow("project", "/tmp/source.csv", "copy", {
      csv: { header_mode: "header", column_names: ["timestamp", "value"] }
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/projects/project/sources/import-workflow");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({
      path: "/tmp/source.csv",
      storage_mode: "copy",
      import_options: {
        csv: { header_mode: "header", column_names: ["timestamp", "value"] }
      },
      template_id: null
    });
    fetchMock.mockRestore();
  });

  it("posts advanced build options", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "job_1",
          project_id: "project",
          type: "conversion",
          status: "pending",
          progress: 0,
          payload: {},
          result: null,
          attempt: 1,
          created_at: "2026-06-23T00:00:00Z",
          updated_at: "2026-06-23T00:00:00Z"
        }),
        { status: 202 }
      )
    );

    await api.build("project", "source", "mapping", "run", "robotics_debug", "/tmp/out", {
      mcap_decoders: ["ros2msg", "foxglove"],
      rrd_optimize_profile: "object-store",
      artifact_validation: "strict",
      catalog_registration: {
        enabled: true,
        dataset_name: "robot_runs",
        server_url: null,
        managed_local: true
      }
    });

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(String(init?.body))).toEqual({
      project_id: "project",
      source_id: "source",
      mapping_id: "mapping",
      template_id: "robotics_debug",
      output_name: "run",
      output_dir: "/tmp/out",
      mcap_decoders: ["ros2msg", "foxglove"],
      rrd_optimize_profile: "object-store",
      artifact_validation: "strict",
      catalog_registration: {
        enabled: true,
        dataset_name: "robot_runs",
        server_url: null,
        managed_local: true
      }
    });
    fetchMock.mockRestore();
  });
});
