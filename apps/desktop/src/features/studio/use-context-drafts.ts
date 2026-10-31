import { useRef } from "react";

/** In-memory drafts follow the task, not the page currently displaying it. */
export function useContextDrafts<T>(capture: () => T, restore: (draft: T | null) => void) {
  const active = useRef("inspect");
  const drafts = useRef(new Map<string, T>());
  return {
    active,
    forget(key: string) { drafts.current.delete(key); },
    switchTo(key: string) {
      if (active.current === key) return;
      drafts.current.set(active.current, capture());
      active.current = key;
      restore(drafts.current.get(key) ?? null);
    },
    update(key: string, update: (draft: T) => T) {
      const draft = drafts.current.get(key);
      if (draft) drafts.current.set(key, update(draft));
    }
  };
}
