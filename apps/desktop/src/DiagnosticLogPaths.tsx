import { FileText } from "lucide-react";

import { CardHeader } from "./app-support";
import type { TranslationKey } from "./i18n";

type Translate = (key: TranslationKey) => string;

type DiagnosticLogPathsProps = {
  logDir: string;
  desktopLogPath: string;
  backendLogPath: string;
  t: Translate;
};

export function DiagnosticLogPaths({
  logDir,
  desktopLogPath,
  backendLogPath,
  t
}: DiagnosticLogPathsProps) {
  if (!logDir && !desktopLogPath && !backendLogPath) return null;

  return (
    <section className="card">
      <CardHeader
        icon={<FileText size={18} />}
        title={t("diagnosticLogs")}
        subtitle={t("diagnosticLogsSubtitle")}
      />
      <dl className="diagnostic-log-paths">
        <div>
          <dt>{t("diagnosticLogFolder")}</dt>
          <dd>{logDir || "-"}</dd>
        </div>
        <div>
          <dt>{t("desktopLog")}</dt>
          <dd>{desktopLogPath || "-"}</dd>
        </div>
        <div>
          <dt>{t("backendLog")}</dt>
          <dd>{backendLogPath || "-"}</dd>
        </div>
      </dl>
      <p className="field-hint">{t("diagnosticLogsHint")}</p>
    </section>
  );
}
