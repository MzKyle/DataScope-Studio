import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  defaultOutputName,
  MappingIssueCard,
  sourceFileDialogFilters,
  sourceFileExtensions
} from "./App";
import { createTranslator } from "./i18n";
import type { MappingValidationIssue } from "./types";

describe("ROS2 source selection", () => {
  it("accepts DB3 files and preserves file or folder names for outputs", () => {
    expect(sourceFileExtensions.has("db3")).toBe(true);
    expect(sourceFileExtensions.has("tif")).toBe(true);
    expect(sourceFileExtensions.has("xyz")).toBe(true);
    expect(sourceFileExtensions.has("log")).toBe(true);
    expect(
      sourceFileDialogFilters.some((filter) => filter.extensions.includes("db3"))
    ).toBe(true);
    expect(
      sourceFileDialogFilters.some((filter) => filter.extensions.includes("tif"))
    ).toBe(true);
    expect(
      sourceFileDialogFilters.some((filter) => filter.extensions.includes("xyz"))
    ).toBe(true);
    expect(
      sourceFileDialogFilters.some((filter) => filter.extensions.includes("log"))
    ).toBe(true);
    expect(defaultOutputName("/data/robot/run_001.db3", "file")).toBe("run_001");
    expect(defaultOutputName("/data/robot/bag_run/", "folder")).toBe("bag_run");
  });

  it("shows skipped ROS2 topics in the local mapping issue card", () => {
    const issue: MappingValidationIssue = {
      severity: "warning",
      code: "ros2_topics_skipped",
      message: "ROS2 topics will be skipped: /custom (acme_msgs/msg/Unknown)",
      recommendation: "Provide message definitions.",
      suggestions: []
    };

    render(
      <MappingIssueCard
        issue={issue}
        language="en"
        t={createTranslator("en")}
        isBusy={false}
        onApply={vi.fn()}
      />
    );

    expect(screen.getByText("Some ROS2 topics will be skipped")).toBeInTheDocument();
    expect(screen.getByText(/acme_msgs\/msg\/Unknown/)).toBeInTheDocument();
  });
});
