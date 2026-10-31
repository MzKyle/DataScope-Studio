import { useState } from "react";
import type { Project } from "../../types";
import type { TranslationKey } from "../../i18n";

export function MoveToProject({ projects, storageMode, busy, onMove, t }: {
  projects: Project[];
  storageMode: "copy" | "reference";
  busy: boolean;
  onMove: (projectId: string, name: string, storage: "copy" | "reference") => void;
  t: (key: TranslationKey) => string;
}) {
  const [target, setTarget] = useState(projects[0]?.id ?? "");
  const [name, setName] = useState("Sensor Run");
  const [storage, setStorage] = useState(storageMode);
  return <details className="card advanced-panel">
    <summary>{t("moveToProject")}</summary>
    <p>{t("moveToProjectHint")}</p>
    <div className="inline-actions">
      <select aria-label={t("currentProject")} disabled={busy} value={target} onChange={(event) => setTarget(event.target.value)}>
        <option value="">{t("newProject")}</option>
        {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
      </select>
      {!target && <input aria-label={t("createProject")} disabled={busy} value={name} onChange={(event) => setName(event.target.value)} />}
      <select aria-label={t("storageMode")} disabled={busy} value={storage} onChange={(event) => setStorage(event.target.value as "copy" | "reference")}>
        <option value="copy">{t("storageCopy")}</option><option value="reference">{t("storageReference")}</option>
      </select>
      <button disabled={busy || (!target && !name.trim())} onClick={() => onMove(target, name.trim(), storage)}>{t("moveToProject")}</button>
    </div>
  </details>;
}
