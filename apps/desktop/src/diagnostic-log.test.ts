import { invoke } from "@tauri-apps/api/core";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  apiErrorLogContext,
  logDiagnostic,
  logDiagnosticError
} from "./diagnostic-log";

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn().mockResolvedValue(undefined)
}));

beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(window, "__TAURI_INTERNALS__", {
    configurable: true,
    value: {}
  });
});

describe("diagnostic logging", () => {
  it("writes structured local events through the Tauri command", () => {
    logDiagnostic("warn", "frontend.test", "test warning", { path: "/tmp/input.ply" });

    expect(invoke).toHaveBeenCalledWith("write_diagnostic_log", {
      event: {
        level: "warn",
        component: "frontend.test",
        message: "test warning",
        context: { path: "/tmp/input.ply" }
      }
    });
  });

  it("records error metadata without throwing another error", () => {
    const error = new Error("viewer failed");
    logDiagnosticError("frontend.viewer", error, { action: "open" });

    expect(invoke).toHaveBeenCalledWith(
      "write_diagnostic_log",
      expect.objectContaining({
        event: expect.objectContaining({
          level: "error",
          component: "frontend.viewer",
          message: "viewer failed",
          context: expect.objectContaining({
            action: "open",
            name: "Error"
          })
        })
      })
    );
  });

  it("keeps API context concise and omits request bodies", () => {
    expect(
      apiErrorLogContext("POST", "/api/sources/source/inspect", 400, "bad_request", {
        source_id: "source",
        paths: ["/tmp/input.ply"],
        validation: { large: "payload" }
      })
    ).toEqual({
      method: "POST",
      path: "/api/sources/source/inspect",
      status: 400,
      code: "bad_request",
      detail_keys: ["paths", "source_id", "validation"],
      source_id: "source",
      paths: ["/tmp/input.ply"]
    });
  });
});
