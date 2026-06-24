import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DiagnosticLogPaths } from "./DiagnosticLogPaths";
import { createTranslator } from "./i18n";

afterEach(() => cleanup());

describe("DiagnosticLogPaths", () => {
  it("shows developer-facing local log locations", () => {
    render(
      <DiagnosticLogPaths
        logDir="/tmp/datascope/logs"
        desktopLogPath="/tmp/datascope/logs/datascope-studio.log"
        backendLogPath="/tmp/datascope/logs/datascope-api.log"
        t={createTranslator("en")}
      />
    );

    expect(screen.getByText("Diagnostic Logs")).toBeInTheDocument();
    expect(screen.getByText("/tmp/datascope/logs/datascope-studio.log")).toBeInTheDocument();
    expect(screen.getByText("/tmp/datascope/logs/datascope-api.log")).toBeInTheDocument();
    expect(screen.getByText(/keeps three backups/)).toBeInTheDocument();
  });

  it("does not render before log paths are available", () => {
    const { container } = render(
      <DiagnosticLogPaths
        logDir=""
        desktopLogPath=""
        backendLogPath=""
        t={createTranslator("zh")}
      />
    );

    expect(container).toBeEmptyDOMElement();
  });
});
