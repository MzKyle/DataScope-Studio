import { invoke } from "@tauri-apps/api/core";

export type DiagnosticLevel = "debug" | "info" | "warn" | "error";
export type DiagnosticContext = Record<string, unknown>;

type TauriInternalsWindow = Window & {
  __TAURI_INTERNALS__?: unknown;
};

let globalHandlersInstalled = false;

export function logDiagnostic(
  level: DiagnosticLevel,
  component: string,
  message: string,
  context?: DiagnosticContext
): void {
  if (!isTauriRuntime()) return;
  void invoke("write_diagnostic_log", {
    event: {
      level,
      component,
      message,
      context: context ?? null
    }
  }).catch(() => {
    // Diagnostic logging must never become another user-facing failure.
  });
}

export function logDiagnosticError(
  component: string,
  error: unknown,
  context?: DiagnosticContext
): void {
  const normalized = normalizeError(error);
  logDiagnostic("error", component, normalized.message, {
    ...context,
    name: normalized.name,
    stack: normalized.stack
  });
}

export function installGlobalDiagnosticHandlers(): void {
  if (globalHandlersInstalled) return;
  globalHandlersInstalled = true;

  window.addEventListener("error", (event) => {
    logDiagnosticError("frontend.window_error", event.error ?? event.message, {
      filename: event.filename,
      line: event.lineno,
      column: event.colno
    });
  });
  window.addEventListener("unhandledrejection", (event) => {
    logDiagnosticError("frontend.unhandled_rejection", event.reason);
  });
  logDiagnostic("info", "frontend.lifecycle", "frontend initialized", {
    user_agent: window.navigator.userAgent
  });
}

export function apiErrorLogContext(
  method: string,
  path: string,
  status: number,
  code: string,
  details: Record<string, unknown>
): DiagnosticContext {
  const context: DiagnosticContext = {
    method,
    path,
    status,
    code,
    detail_keys: Object.keys(details).sort()
  };
  if (typeof details.output_name === "string") context.output_name = details.output_name;
  if (typeof details.source_id === "string") context.source_id = details.source_id;
  if (
    Array.isArray(details.paths) &&
    details.paths.every((value) => typeof value === "string")
  ) {
    context.paths = details.paths.slice(0, 10);
  }
  return context;
}

function isTauriRuntime(): boolean {
  return Boolean((window as TauriInternalsWindow).__TAURI_INTERNALS__);
}

function normalizeError(error: unknown): {
  name: string;
  message: string;
  stack?: string;
} {
  if (error instanceof Error) {
    return {
      name: error.name,
      message: error.message || String(error),
      stack: error.stack?.slice(0, 8_000)
    };
  }
  return {
    name: typeof error,
    message: safeString(error)
  };
}

function safeString(value: unknown): string {
  try {
    if (typeof value === "string") return value;
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
}
