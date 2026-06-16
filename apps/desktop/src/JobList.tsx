import { Ban, RotateCcw } from "lucide-react";

import type { TranslationKey } from "./i18n";
import type { Job } from "./types";

type Translate = (key: TranslationKey) => string;

type JobListProps = {
  jobs: Job[];
  disabled: boolean;
  onCancel: (job: Job) => void;
  onRetry: (job: Job) => void;
  t: Translate;
};

const ACTIVE_STATUSES = new Set<Job["status"]>([
  "pending",
  "running",
  "cancel_requested"
]);
const RETRYABLE_STATUSES = new Set<Job["status"]>([
  "cancelled",
  "failed",
  "interrupted"
]);

export function JobList({ jobs, disabled, onCancel, onRetry, t }: JobListProps) {
  return (
    <div className="job-list">
      {jobs.map((job) => (
        <article className="job-item" key={job.id}>
          <div className="job-summary">
            <strong>
              {job.type} / {job.status}
            </strong>
            <span>{job.stage || t("jobQueued")}</span>
          </div>
          <progress max={1} value={Math.min(1, Math.max(0, job.progress))} />
          <span className="job-progress">{Math.round(job.progress * 100)}%</span>
          {job.error && <p className="job-error">{job.error.message}</p>}
          <div className="job-actions">
            {ACTIVE_STATUSES.has(job.status) && (
              <button
                disabled={disabled || job.status === "cancel_requested"}
                onClick={() => onCancel(job)}
              >
                <Ban size={14} />
                {t("cancelJob")}
              </button>
            )}
            {RETRYABLE_STATUSES.has(job.status) && (
              <button disabled={disabled} onClick={() => onRetry(job)}>
                <RotateCcw size={14} />
                {t("retryJob")}
              </button>
            )}
          </div>
        </article>
      ))}
    </div>
  );
}
