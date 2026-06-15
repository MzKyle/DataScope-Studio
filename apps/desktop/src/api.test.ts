import { describe, expect, it } from "vitest";

import { apiErrorFromResponse } from "./api";

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
});
