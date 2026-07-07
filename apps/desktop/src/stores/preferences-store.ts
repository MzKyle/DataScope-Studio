import { create } from "zustand";
import { persist } from "zustand/middleware";

import {
  getInitialDefaultArtifactDir,
  getInitialDefaultExportDir,
  saveDefaultArtifactDir,
  saveDefaultExportDir
} from "../app-support";
import { getInitialLanguage, saveLanguage, type Language } from "../i18n";

type PreferencesState = {
  defaultArtifactDir: string;
  defaultExportDir: string;
  language: Language;
  setDefaultArtifactDir: (value: string) => void;
  setDefaultExportDir: (value: string) => void;
  setLanguage: (language: Language) => void;
};

export const usePreferencesStore = create<PreferencesState>()(
  persist(
    (set) => ({
      defaultArtifactDir: getInitialDefaultArtifactDir(),
      defaultExportDir: getInitialDefaultExportDir(),
      language: getInitialLanguage(),
      setDefaultArtifactDir: (defaultArtifactDir) => {
        saveDefaultArtifactDir(defaultArtifactDir);
        set({ defaultArtifactDir });
      },
      setDefaultExportDir: (defaultExportDir) => {
        saveDefaultExportDir(defaultExportDir);
        set({ defaultExportDir });
      },
      setLanguage: (language) => {
        saveLanguage(language);
        set({ language });
      }
    }),
    {
      name: "datascope.preferences"
    }
  )
);
