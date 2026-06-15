import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "./api";
import { clearErrorAreaState, GlobalErrorToast, InlineError } from "./App";
import { createTranslator } from "./i18n";

const t = createTranslator("en");

describe("error UI", () => {
  it("shows artifact conflicts with the conflicting files", () => {
    const error = new ApiError(
      "Output files already exist",
      409,
      "artifact_name_conflict",
      {
        output_name: "select",
        paths: ["/tmp/select.rrd", "/tmp/select.rbl"]
      }
    );

    render(<InlineError error={error} t={t} />);

    expect(screen.getByRole("alert")).toHaveTextContent("Output name already exists");
    expect(screen.getByRole("alert")).toHaveTextContent("select");
    expect(screen.getByRole("alert")).toHaveTextContent("/tmp/select.rrd");
    expect(screen.getByRole("alert")).toHaveTextContent("/tmp/select.rbl");
  });

  it("supports retrying and dismissing a global error", () => {
    const onRetry = vi.fn();
    const onDismiss = vi.fn();
    const error = new ApiError("Backend unavailable", 503, "backend_unavailable");

    const { rerender } = render(
      <GlobalErrorToast
        notification={{ error, retry: onRetry }}
        t={t}
        onDismiss={onDismiss}
        onRetry={onRetry}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledOnce();

    rerender(
      <GlobalErrorToast
        notification={{ error }}
        t={t}
        onDismiss={onDismiss}
        onRetry={onRetry}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it("clears only the requested local error area", () => {
    const importError = new ApiError("Invalid source");
    const queryError = new ApiError("Invalid query");

    const next = clearErrorAreaState(
      {
        import: importError,
        query: queryError
      },
      "import"
    );

    expect(next.import).toBeUndefined();
    expect(next.query).toBe(queryError);
  });
});
