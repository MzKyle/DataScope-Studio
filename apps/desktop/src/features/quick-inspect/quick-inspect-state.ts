export type WorkspaceMode = "project" | "quick-inspect";

export type QuickInspectSessionState = {
  id: string;
  sourcePath: string;
};

export const emptyQuickInspectSession: QuickInspectSessionState = {
  id: "",
  sourcePath: ""
};

export function hasQuickInspectSession(session: QuickInspectSessionState) {
  return Boolean(session.id);
}
