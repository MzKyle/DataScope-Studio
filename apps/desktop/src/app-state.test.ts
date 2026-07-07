import { describe, expect, it } from "vitest";

import { queryKeys } from "./app/query-keys";
import { useImportDraftStore } from "./stores/import-draft-store";
import { usePreferencesStore } from "./stores/preferences-store";
import { useUiStore } from "./stores/ui-store";

describe("frontend app state boundaries", () => {
  it("keeps project query keys stable and scoped", () => {
    expect(queryKeys.projects()).toEqual(["projects"]);
    expect(queryKeys.projectData("project_1", true)).toEqual([
      "projects",
      "project_1",
      "workspace",
      { includeQueryTemplates: true }
    ]);
    expect(queryKeys.projectData("project_1", false)).not.toEqual(
      queryKeys.projectData("project_1", true)
    );
  });

  it("guards section navigation state", () => {
    useUiStore.setState({ activeSection: "dashboard", busy: "", sourcePickerOpen: false });

    useUiStore.getState().setActiveSection("diagnostics");
    expect(useUiStore.getState().activeSection).toBe("diagnostics");

    useUiStore.getState().setActiveSection("unknown");
    expect(useUiStore.getState().activeSection).toBe("diagnostics");
  });

  it("stores import draft controls independently from workspace data", () => {
    useImportDraftStore.getState().resetImportDraft();

    useImportDraftStore.getState().setSourcePath("/tmp/run.csv");
    useImportDraftStore.getState().setCsvHeaderMode("header");
    useImportDraftStore.getState().setOutputName("run");

    expect(useImportDraftStore.getState()).toMatchObject({
      csvHeaderMode: "header",
      outputName: "run",
      sourcePath: "/tmp/run.csv"
    });
  });

  it("persists preferences through the preferences store interface", () => {
    const previousLanguage = usePreferencesStore.getState().language;
    const previousExportDir = usePreferencesStore.getState().defaultExportDir;

    usePreferencesStore.getState().setLanguage("en");
    usePreferencesStore.getState().setDefaultExportDir("/tmp/datascope-exports");

    expect(usePreferencesStore.getState().language).toBe("en");
    expect(usePreferencesStore.getState().defaultExportDir).toBe("/tmp/datascope-exports");

    usePreferencesStore.getState().setLanguage(previousLanguage);
    usePreferencesStore.getState().setDefaultExportDir(previousExportDir);
  });
});
