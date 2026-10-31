import { create } from "zustand";

export type SectionId =
  | "inspect"
  | "projects"
  | "settings";

type UiStore = {
  activeSection: SectionId;
  busy: string;
  sourcePickerOpen: boolean;
  setActiveSection: (section: string) => void;
  setBusy: (label: string) => void;
  setSourcePickerOpen: (open: boolean | ((current: boolean) => boolean)) => void;
};

const sectionIds = new Set<SectionId>([
  "inspect",
  "projects",
  "settings"
]);

export function isSectionId(value: string): value is SectionId {
  return sectionIds.has(value as SectionId);
}

export const useUiStore = create<UiStore>((set) => ({
  activeSection: "inspect",
  busy: "",
  sourcePickerOpen: false,
  setActiveSection: (section) => {
    if (isSectionId(section)) set({ activeSection: section });
  },
  setBusy: (busy) => set({ busy }),
  setSourcePickerOpen: (open) =>
    set((state) => ({
      sourcePickerOpen: typeof open === "function" ? open(state.sourcePickerOpen) : open
    }))
}));
