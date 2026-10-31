export type WorkspaceMode = "project" | "quick-inspect";

export type QuickInspectSessionState = {
  id: string;
  sourcePath: string;
  importOptions?: Record<string, unknown>;
  storageMode?: "copy" | "reference";
};

export const emptyQuickInspectSession: QuickInspectSessionState = {
  id: "",
  sourcePath: ""
};

export function hasQuickInspectSession(session: QuickInspectSessionState) {
  return Boolean(session.id);
}
