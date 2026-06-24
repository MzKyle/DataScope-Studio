import {
  Ban,
  CheckCircle2,
  CircleAlert,
  LoaderCircle,
  XCircle
} from "lucide-react";

import type { TranslationKey } from "./i18n";
import type { Job } from "./types";

type Translate = (key: TranslationKey) => string;

type BuildJobStatusProps = {
  job: Job | null;
  isSubmitting: boolean;
  t: Translate;
};

const ACTIVE_BUILD_STATUSES = new Set<Job["status"]>([
  "pending",
  "running",
  "cancel_requested"
]);

const STAGE_TRANSLATIONS: Record<string, TranslationKey> = {
  queued: "buildStageQueued",
  starting: "buildStageStarting",
  preparing: "buildStagePreparing",
  converting: "buildStageConverting",
  ros2_to_mcap: "buildStageRos2ToMcap",
  rerun_mcap: "buildStageRerunMcap",
  blueprint: "buildStageBlueprint",
  completed: "buildStageCompleted",
  failed: "buildStageFailed",
  cancelled: "buildStageCancelled",
  interrupted: "buildStageInterrupted"
};

export function isActiveBuildJob(job: Job | null): boolean {
  return Boolean(job && ACTIVE_BUILD_STATUSES.has(job.status));
}

export function buildStageLabel(stage: string | null | undefined, t: Translate): string {
  if (!stage) return t("buildStageQueued");
  const key = STAGE_TRANSLATIONS[stage];
  return key ? t(key) : stage;
}

export function BuildJobStatus({ job, isSubmitting, t }: BuildJobStatusProps) {
  if (!isSubmitting && !job) return null;

  const progress = Math.min(1, Math.max(0, job?.progress ?? 0));
  const percent = Math.round(progress * 100);
  const active = isSubmitting || isActiveBuildJob(job);
  const status = job?.status;

  let title = t("buildSubmitting");
  let description = t("buildSubmittingHint");
  let tone = "running";
  let icon = <LoaderCircle className="build-status-spinner" size={20} />;

  if (!isSubmitting && job) {
    if (status === "succeeded") {
      title = t("buildCompleted");
      description = t("buildCompletedHint");
      tone = "success";
      icon = <CheckCircle2 size={20} />;
    } else if (status === "failed") {
      title = t("buildFailed");
      description = job.error?.message || job.error_message || t("buildFailedHint");
      tone = "danger";
      icon = <XCircle size={20} />;
    } else if (status === "cancelled") {
      title = t("buildCancelled");
      description = t("buildCancelledHint");
      tone = "neutral";
      icon = <Ban size={20} />;
    } else if (status === "interrupted") {
      title = t("buildInterrupted");
      description = job.error?.message || job.error_message || t("buildInterruptedHint");
      tone = "danger";
      icon = <CircleAlert size={20} />;
    } else if (status === "cancel_requested") {
      title = t("buildCancelRequested");
      description = t("buildBackgroundHint");
    } else {
      title = `${t("buildRunning")} ${percent}%`;
      description = t("buildBackgroundHint");
    }
  }

  return (
    <section
      className={`build-job-status is-${tone}`}
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      <div className="build-job-status-icon">{icon}</div>
      <div className="build-job-status-content">
        <div className="build-job-status-heading">
          <strong>{title}</strong>
          {job && <span>{buildStageLabel(job.stage, t)}</span>}
        </div>
        <p>{description}</p>
        {(active || job) && (
          <div className="build-job-progress">
            <div>
              <span>{t("buildProgress")}</span>
              <strong>{isSubmitting ? "…" : `${percent}%`}</strong>
            </div>
            <progress
              aria-label={t("buildProgress")}
              max={1}
              value={isSubmitting ? undefined : progress}
            />
          </div>
        )}
        {job && (
          <span className="build-job-id">
            {t("buildTaskId")}: {job.id}
          </span>
        )}
      </div>
    </section>
  );
}
