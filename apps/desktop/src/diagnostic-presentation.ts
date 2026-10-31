import type { TranslationKey } from "./i18n";

export function checkLabel(id: string, fallback: string, t: (key: TranslationKey) => string) {
  if (id === "time_sync") return t("topicRangeDifference");
  if (id === "cv_detection" || id === "detection_failure") return t("lowConfidenceSamples");
  return fallback;
}
