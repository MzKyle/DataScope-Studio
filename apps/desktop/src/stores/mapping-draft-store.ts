import { create } from "zustand";

import type {
  MappingDiff,
  MappingPayload,
  MappingValidation,
  SchemaProfile,
  Source,
  StreamInfo,
  TemplateMatch
} from "../types";

type MappingDraftState = {
  mapping: MappingPayload | null;
  mappingConfirmed: boolean;
  mappingDiff: MappingDiff | null;
  mappingValidation: MappingValidation | null;
  previewRows: Record<string, unknown>[];
  savedMappingId: string;
  schemaProfile: SchemaProfile | null;
  source: Source | null;
  streams: StreamInfo[];
  templates: TemplateMatch[];
  resetMappingDraft: () => void;
  setMappingDraft: (draft: Partial<Omit<MappingDraftState, "resetMappingDraft" | "setMappingDraft">>) => void;
};

const initialMappingDraft = {
  mapping: null,
  mappingConfirmed: false,
  mappingDiff: null,
  mappingValidation: null,
  previewRows: [] as Record<string, unknown>[],
  savedMappingId: "",
  schemaProfile: null,
  source: null,
  streams: [] as StreamInfo[],
  templates: [] as TemplateMatch[]
};

export const useMappingDraftStore = create<MappingDraftState>((set) => ({
  ...initialMappingDraft,
  resetMappingDraft: () => set(initialMappingDraft),
  setMappingDraft: (draft) => set(draft)
}));
