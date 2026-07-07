import { create } from "zustand";

export type CsvHeaderMode = "auto" | "header" | "no_header";
export type SourceStorageMode = "copy" | "reference";

type ImportDraftState = {
  csvColumnNames: string;
  csvHeaderMode: CsvHeaderMode;
  outputName: string;
  sourcePath: string;
  sourceStorageMode: SourceStorageMode;
  resetImportDraft: () => void;
  setCsvColumnNames: (value: string) => void;
  setCsvHeaderMode: (value: CsvHeaderMode) => void;
  setOutputName: (value: string) => void;
  setSourcePath: (value: string) => void;
  setSourceStorageMode: (value: SourceStorageMode) => void;
};

const initialImportDraft = {
  csvColumnNames: "",
  csvHeaderMode: "auto" as CsvHeaderMode,
  outputName: "",
  sourcePath: "",
  sourceStorageMode: "copy" as SourceStorageMode
};

export const useImportDraftStore = create<ImportDraftState>((set) => ({
  ...initialImportDraft,
  resetImportDraft: () => set(initialImportDraft),
  setCsvColumnNames: (csvColumnNames) => set({ csvColumnNames }),
  setCsvHeaderMode: (csvHeaderMode) => set({ csvHeaderMode }),
  setOutputName: (outputName) => set({ outputName }),
  setSourcePath: (sourcePath) => set({ sourcePath }),
  setSourceStorageMode: (sourceStorageMode) => set({ sourceStorageMode })
}));
