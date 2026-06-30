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
});
