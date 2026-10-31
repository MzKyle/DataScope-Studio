import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useContextDrafts } from "./use-context-drafts";

describe("task draft isolation", () => {
  it("restores quick and per-project drafts without starting work or clearing a session", () => {
    let current = { path: "/quick.csv", mapping: "edited quick", job: "" };
    const restore = vi.fn((draft) => { current = draft ?? { path: "", mapping: "", job: "" }; });
    const { result } = renderHook(() => useContextDrafts(() => current, restore));
    act(() => result.current.switchTo("project:a"));
    expect(current.path).toBe("");
    current = { path: "/project.csv", mapping: "edited project", job: "job_a" };
    act(() => result.current.switchTo("inspect"));
    expect(current.mapping).toBe("edited quick");
    act(() => result.current.update("project:a", (draft) => ({ ...draft, job: "completed" })));
    act(() => result.current.switchTo("project:a"));
    expect(current).toEqual({ path: "/project.csv", mapping: "edited project", job: "completed" });
    act(() => result.current.switchTo("project:b"));
    expect(current.path).toBe("");
  });
});
