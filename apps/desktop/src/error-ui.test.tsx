import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./api";
import { clearErrorAreaState, ErrorDialog, GlobalErrorToast, InlineError } from "./App";
import { createTranslator } from "./i18n";

const t = createTranslator("en");

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("error UI", () => {
  it("keeps artifact conflicts concise and moves raw paths into details", async () => {
    const error = new ApiError(
      "Output files already exist",
      409,
      "artifact_name_conflict",
      {
        output_name: "select",
        paths: ["/tmp/select.rrd", "/tmp/select.rbl"]
      }
    );
    const onDetails = vi.fn();

    render(<InlineError error={error} t={t} area="build" onDetails={onDetails} />);

    expect(screen.getByRole("alert")).toHaveTextContent("Output name already exists");
    expect(screen.getByRole("alert")).toHaveTextContent("select");
    expect(screen.getByRole("alert")).toHaveTextContent("Use a different output name");
    expect(screen.getByRole("alert")).not.toHaveTextContent("/tmp/select.rrd");
    fireEvent.click(screen.getByRole("button", { name: "View details" }));
    expect(onDetails).toHaveBeenCalledWith(error, "build");

    cleanup();
    Object.defineProperty(window.navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) }
    });
    render(
      <ErrorDialog
        request={{ error, area: "build" }}
        t={t}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByRole("dialog")).toHaveTextContent("Output name already exists");
    expect(screen.getByRole("dialog")).toHaveTextContent("Use a different output name");
    expect(
      screen.getByText((_, node) =>
        node?.tagName.toLowerCase() === "pre" &&
        Boolean(node.textContent?.includes("/tmp/select.rrd"))
      )
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Copy details" }));
    await waitFor(() => {
      expect(window.navigator.clipboard.writeText).toHaveBeenCalledWith(
        expect.stringContaining("/tmp/select.rbl")
      );
    });
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
