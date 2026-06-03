import { useEffect, useMemo, useState } from "react";
import {
  Database,
  Download,
  ExternalLink,
  FileSearch,
  FolderPlus,
  Image,
  ListChecks,
  Play,
  RefreshCcw,
  Save,
  Search,
  Tags,
  Upload
} from "lucide-react";

import { api } from "./api";
import type {
  BatchResult,
  BuildResult,
  Job,
  MappingPayload,
  Plugin,
  Project,
  ProjectExportResult,
  QueryResult,
  QueryTemplate,
  Recording,
  Source,
  StreamInfo,
  TemplateMatch,
  TemplateRegistryItem
} from "./types";

function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectName, setProjectName] = useState("Sensor Run");
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [sourcePath, setSourcePath] = useState("");
  const [outputName, setOutputName] = useState("run_001");
  const [source, setSource] = useState<Source | null>(null);
  const [streams, setStreams] = useState<StreamInfo[]>([]);
  const [mapping, setMapping] = useState<MappingPayload | null>(null);
  const [templates, setTemplates] = useState<TemplateMatch[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState("sensor_monitor");
  const [savedMappingId, setSavedMappingId] = useState("");
  const [buildResult, setBuildResult] = useState<BuildResult | null>(null);
  const [previewRows, setPreviewRows] = useState<Record<string, unknown>[]>([]);
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [plugins, setPlugins] = useState<Plugin[]>([]);
  const [templateRegistry, setTemplateRegistry] = useState<TemplateRegistryItem[]>([]);
  const [queryTemplates, setQueryTemplates] = useState<QueryTemplate[]>([]);
  const [selectedQueryTemplate, setSelectedQueryTemplate] = useState("low_battery");
  const [selectedQueryRecording, setSelectedQueryRecording] = useState("");
  const [queryThreshold, setQueryThreshold] = useState("0.5");
  const [queryResult, setQueryResult] = useState<QueryResult | null>(null);
  const [compareRecordingIds, setCompareRecordingIds] = useState("");
  const [compareMetric, setCompareMetric] = useState("battery");
  const [compareResult, setCompareResult] = useState<QueryResult | null>(null);
  const [batchPattern, setBatchPattern] = useState("");
  const [batchOutputPrefix, setBatchOutputPrefix] = useState("batch_run");
  const [batchResult, setBatchResult] = useState<BatchResult | null>(null);
  const [pluginPath, setPluginPath] = useState("");
  const [templatePath, setTemplatePath] = useState("");
  const [exportPath, setExportPath] = useState("");
  const [projectExport, setProjectExport] = useState<ProjectExportResult | null>(null);
  const [tagInput, setTagInput] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) ?? null,
    [projects, selectedProjectId]
  );

  useEffect(() => {
    refreshProjects();
    refreshExtensionData();
  }, []);

  useEffect(() => {
    if (selectedProjectId) {
      refreshProjectData(selectedProjectId);
    }
  }, [selectedProjectId]);

  async function run<T>(label: string, task: () => Promise<T>): Promise<T | null> {
    setBusy(label);
    setError("");
    try {
      return await task();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return null;
    } finally {
      setBusy("");
    }
  }

  async function refreshProjects() {
    const result = await run("Refreshing projects", () => api.projects());
    if (result) {
      setProjects(result);
      if (!selectedProjectId && result[0]) {
        setSelectedProjectId(result[0].id);
      }
    }
  }

  async function refreshProjectData(projectId = selectedProjectId) {
    if (!projectId) return;
    const recordingRows = await run("Refreshing recordings", () => api.recordings(projectId));
    if (recordingRows) setRecordings(recordingRows);
    const jobRows = await run("Refreshing jobs", () => api.jobs(projectId));
    if (jobRows) setJobs(jobRows);
    const templatesRows = await run("Loading query templates", () => api.queryTemplates(projectId));
    if (templatesRows) {
      setQueryTemplates(templatesRows);
      if (!templatesRows.some((template) => template.template_id === selectedQueryTemplate)) {
        setSelectedQueryTemplate(templatesRows[0]?.template_id ?? "low_battery");
      }
    }
  }

  async function refreshExtensionData() {
    const pluginRows = await run("Loading plugins", () => api.plugins());
    if (pluginRows) setPlugins(pluginRows);
    const templateRows = await run("Loading templates", () => api.templates());
    if (templateRows) setTemplateRegistry(templateRows);
  }

  async function createProject() {
    const result = await run("Creating project", () => api.createProject(projectName));
    if (result) {
      setProjects((current) => [result, ...current]);
      setSelectedProjectId(result.id);
    }
  }

  async function importAndInspect() {
    if (!selectedProjectId || !sourcePath) {
      setError("Select a project and enter a CSV, JSONL, image folder, or MCAP path.");
      return;
    }
    const added = await run("Adding source", () => api.addSource(selectedProjectId, sourcePath));
    if (!added) return;
    setSource(added);
    const inspection = await run("Inspecting source", () => api.inspect(added.id));
    if (!inspection) return;
    setStreams(inspection.streams);
    const templateMatches = await run("Suggesting templates", () => api.suggestTemplates(added.id));
    const nextTemplateId = templateMatches?.[0]?.template_id ?? "sensor_monitor";
    setTemplates(templateMatches ?? []);
    setSelectedTemplateId(nextTemplateId);
    const suggested = await run("Suggesting mapping", () =>
      api.suggestMappingForTemplate(added.id, nextTemplateId)
    );
    if (suggested) {
      setMapping(suggested);
      const firstStream = inspection.streams[0];
      if (firstStream) {
        const preview = await run("Loading preview", () => api.preview(added.id, firstStream.stream_id));
        if (preview) setPreviewRows(preview.rows);
      }
    }
  }

  async function saveMapping() {
    if (!source || !mapping) return;
    const saved = await run("Saving mapping", () => api.saveMapping(source.id, mapping.mapping));
    if (saved) setSavedMappingId(saved.id);
  }

  async function buildRecording() {
    if (!selectedProject || !source || !savedMappingId) {
      setError("Save the mapping before building a recording.");
      return;
    }
    const result = await run("Building recording", () =>
      api.build(selectedProject.id, source.id, savedMappingId, outputName, selectedTemplateId)
    );
    if (result) {
      setBuildResult(result);
      refreshProjectData(selectedProject.id);
    }
  }

  async function openInRerun() {
    if (!buildResult) return;
    await run("Opening Rerun", () =>
      api.open(buildResult.recording_path, buildResult.blueprint_path)
    );
  }

  function updateMappingStream(index: number, key: "entity_path" | "archetype", value: string) {
    if (!mapping) return;
    const next = structuredClone(mapping);
    next.mapping.streams[index][key] = value;
    setMapping(next);
    setSavedMappingId("");
  }

  async function changeTemplate(templateId: string) {
    setSelectedTemplateId(templateId);
    setSavedMappingId("");
    if (!source) return;
    const suggested = await run("Suggesting mapping", () =>
      api.suggestMappingForTemplate(source.id, templateId)
    );
    if (suggested) setMapping(suggested);
  }

  async function addTagToRecording(recordingId: string) {
    const tag = tagInput.trim();
    if (!tag) return;
    const updated = await run("Updating tag", () =>
      api.patchRecording(recordingId, { add_tags: [tag] })
    );
    if (updated) {
      setTagInput("");
      refreshProjectData(updated.project_id);
    }
  }

  async function runQuery() {
    if (!selectedProjectId) return;
    const params = thresholdTemplates.has(selectedQueryTemplate)
      ? { threshold: Number(queryThreshold) }
      : {};
    const result = await run("Running query", () =>
      api.query(
        selectedProjectId,
        selectedQueryTemplate,
        selectedQueryRecording ? [selectedQueryRecording] : [],
        params
      )
    );
    if (result) setQueryResult(result);
  }

  async function exportQuery() {
    if (!selectedProjectId) return;
    const params = thresholdTemplates.has(selectedQueryTemplate)
      ? { threshold: Number(queryThreshold) }
      : {};
    const result = await run("Exporting query", () =>
      api.exportQuery(
        selectedProjectId,
        selectedQueryTemplate,
        selectedQueryRecording ? [selectedQueryRecording] : [],
        params,
        "csv"
      )
    );
    if (result) setExportPath(result.path);
  }

  async function installPlugin() {
    if (!pluginPath.trim()) return;
    const result = await run("Installing plugin", () => api.installPlugin(pluginPath.trim()));
    if (result) {
      setPluginPath("");
      refreshExtensionData();
    }
  }

  async function installTemplate() {
    if (!templatePath.trim()) return;
    const result = await run("Installing template", () => api.installTemplate(templatePath.trim()));
    if (result) {
      setTemplatePath("");
      refreshExtensionData();
    }
  }

  async function runBatchImport() {
    if (!selectedProjectId || !batchPattern.trim()) return;
    const patterns = batchPattern
      .split("\n")
      .map((value) => value.trim())
      .filter(Boolean);
    const result = await run("Running batch import", () =>
      api.batchImport(selectedProjectId, patterns, selectedTemplateId, batchOutputPrefix)
    );
    if (result) {
      setBatchResult(result);
      refreshProjectData(selectedProjectId);
    }
  }

  async function runCompare() {
    if (!selectedProjectId) return;
    const recordingIds = compareRecordingIds
      .split(/[,\s]+/)
      .map((value) => value.trim())
      .filter(Boolean);
    const metricKeys = compareMetric
      .split(/[,\s]+/)
      .map((value) => value.trim())
      .filter(Boolean);
    const result = await run("Comparing recordings", () =>
      api.compare(selectedProjectId, recordingIds, metricKeys, "summary")
    );
    if (result) setCompareResult(result);
  }

  async function exportProject() {
    if (!selectedProjectId) return;
    const result = await run("Exporting project", () => api.exportProject(selectedProjectId));
    if (result) setProjectExport(result);
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <Database size={24} />
          <div>
            <h1>DataScope Studio</h1>
            <span>V1.0 Local Catalog</span>
          </div>
        </div>

        <section className="panel">
          <div className="panel-title">
            <span>Projects</span>
            <button className="icon-button" onClick={refreshProjects} title="Refresh projects">
              <RefreshCcw size={16} />
            </button>
          </div>
          <div className="inline-form">
            <input value={projectName} onChange={(event) => setProjectName(event.target.value)} />
            <button onClick={createProject} title="Create project">
              <FolderPlus size={16} />
            </button>
          </div>
          <select
            value={selectedProjectId}
            onChange={(event) => setSelectedProjectId(event.target.value)}
          >
            <option value="">Select project</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
          {selectedProject && <p className="path-line">{selectedProject.workspace_path}</p>}
          <button onClick={() => refreshProjectData()} title="Refresh recordings and queries">
            <ListChecks size={16} />
            Refresh Runs
          </button>
          <button onClick={exportProject} title="Export project package">
            <Download size={16} />
            Export Project
          </button>
          {projectExport && <p className="path-line">Package: {projectExport.path}</p>}
        </section>

        <section className="panel">
          <div className="panel-title">Import Data</div>
          <input
            placeholder="/path/to/run.csv, run.jsonl, images/, or run.mcap"
            value={sourcePath}
            onChange={(event) => setSourcePath(event.target.value)}
          />
          <button className="primary" onClick={importAndInspect}>
            <Upload size={16} />
            Inspect Source
          </button>
        </section>

        <section className="panel">
          <div className="panel-title">Batch Import</div>
          <textarea
            placeholder="/path/to/*.csv&#10;/path/to/images"
            value={batchPattern}
            onChange={(event) => setBatchPattern(event.target.value)}
          />
          <input
            value={batchOutputPrefix}
            onChange={(event) => setBatchOutputPrefix(event.target.value)}
          />
          <button onClick={runBatchImport}>
            <Upload size={16} />
            Run Batch
          </button>
          {batchResult && (
            <p className="path-line">
              {batchResult.id}: {batchResult.succeeded}/{batchResult.total} succeeded
            </p>
          )}
        </section>

        <section className="panel">
          <div className="panel-title">
            <span>Extensions</span>
            <button className="icon-button" onClick={refreshExtensionData} title="Refresh extensions">
              <RefreshCcw size={16} />
            </button>
          </div>
          <input
            placeholder="/path/to/plugin"
            value={pluginPath}
            onChange={(event) => setPluginPath(event.target.value)}
          />
          <button onClick={installPlugin}>
            <Save size={16} />
            Install Plugin
          </button>
          <input
            placeholder="/path/to/template.yaml"
            value={templatePath}
            onChange={(event) => setTemplatePath(event.target.value)}
          />
          <button onClick={installTemplate}>
            <Save size={16} />
            Install Template
          </button>
          <p className="path-line">
            {plugins.length} plugins / {templateRegistry.length} templates
          </p>
        </section>

        {(busy || error) && (
          <section className="status-panel">
            {busy && <span>{busy}</span>}
            {error && <strong>{error}</strong>}
          </section>
        )}
      </aside>

      <section className="workspace">
        <header className="workspace-header">
          <div>
            <h2>Import Wizard</h2>
            <p>Select Source &gt; Inspect &gt; Confirm Mapping &gt; Convert &gt; Open</p>
          </div>
          <div className="template-control">
            <Image size={16} />
            <select
              value={selectedTemplateId}
              onChange={(event) => changeTemplate(event.target.value)}
            >
              {(templates.length ? templates : [{ template_id: "sensor_monitor", name: "Sensor Monitor", score: 1 }]).map(
                (template) => (
                  <option key={template.template_id} value={template.template_id}>
                    {template.name} ({Math.round(template.score * 100)}%)
                  </option>
                )
              )}
            </select>
          </div>
        </header>

        <div className="grid">
          <section className="surface">
            <div className="section-heading">
              <FileSearch size={18} />
              <h3>Schema Inspector</h3>
            </div>
            {source ? (
              <>
                <dl className="meta-grid">
                  <div>
                    <dt>Type</dt>
                    <dd>{source.type}</dd>
                  </div>
                  <div>
                    <dt>Status</dt>
                    <dd>{source.status}</dd>
                  </div>
                  <div>
                    <dt>Size</dt>
                    <dd>{source.size_bytes.toLocaleString()} bytes</dd>
                  </div>
                  <div>
                    <dt>Streams</dt>
                    <dd>{streams.length}</dd>
                  </div>
                </dl>
                <StreamTable streams={streams} />
              </>
            ) : (
              <EmptyState text="Create or select a project, then inspect a CSV, JSONL, image folder, or MCAP file." />
            )}
          </section>

          <section className="surface">
            <div className="section-heading">
              <Save size={18} />
              <h3>Mapping Editor</h3>
            </div>
            {mapping ? (
              <>
                <div className="mapping-meta">
                  <span>{mapping.mapping.app_id}</span>
                  <span>{mapping.mapping.timelines.primary.source_field}</span>
                </div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Fields</th>
                        <th>Type</th>
                        <th>Entity Path</th>
                        <th>Archetype</th>
                        <th>Confidence</th>
                      </tr>
                    </thead>
                    <tbody>
                      {mapping.mapping.streams.map((stream, index) => (
                        <tr key={stream.stream_id}>
                          <td>{stream.source_fields.join(", ")}</td>
                          <td>{stream.semantic_type}</td>
                          <td>
                            <input
                              value={stream.entity_path}
                              onChange={(event) =>
                                updateMappingStream(index, "entity_path", event.target.value)
                              }
                            />
                          </td>
                          <td>
                            <input
                              value={stream.archetype}
                              onChange={(event) =>
                                updateMappingStream(index, "archetype", event.target.value)
                              }
                            />
                          </td>
                          <td>{Math.round(stream.confidence * 100)}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="actions">
                  <button onClick={saveMapping}>
                    <Save size={16} />
                    Save Mapping
                  </button>
                  {savedMappingId && <span className="success">Saved {savedMappingId}</span>}
                </div>
              </>
            ) : (
              <EmptyState text="Inspect a source to generate an editable mapping." />
            )}
          </section>
        </div>

        <section className="surface">
          <div className="section-heading">
            <Play size={18} />
            <h3>Conversion Job</h3>
          </div>
          <div className="build-row">
            <input value={outputName} onChange={(event) => setOutputName(event.target.value)} />
            <button className="primary" onClick={buildRecording}>
              <Play size={16} />
              Build .rrd + .rbl
            </button>
            <button disabled={!buildResult} onClick={openInRerun}>
              <ExternalLink size={16} />
              Open in Rerun
            </button>
          </div>
          {buildResult && (
            <dl className="artifact-list">
              <div>
                <dt>Recording</dt>
                <dd>{buildResult.recording_path}</dd>
              </div>
              <div>
                <dt>Blueprint</dt>
                <dd>{buildResult.blueprint_path}</dd>
              </div>
              <div>
                <dt>Job</dt>
                <dd>
                  {buildResult.job_id} / {buildResult.status}
                </dd>
              </div>
            </dl>
          )}
        </section>

        <section className="surface">
          <div className="section-heading">
            <FileSearch size={18} />
            <h3>Preview</h3>
          </div>
          {previewRows.length ? (
            <pre className="preview">{JSON.stringify(previewRows.slice(0, 8), null, 2)}</pre>
          ) : (
            <EmptyState text="Preview rows will appear after inspection." />
          )}
        </section>

        <div className="grid">
          <section className="surface">
            <div className="section-heading">
              <ListChecks size={18} />
              <h3>Recording Browser</h3>
            </div>
            {recordings.length ? (
              <>
                <div className="tag-row">
                  <input
                    placeholder="tag or key:value"
                    value={tagInput}
                    onChange={(event) => setTagInput(event.target.value)}
                  />
                </div>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Run</th>
                        <th>Template</th>
                        <th>Source</th>
                        <th>Tags</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {recordings.map((recording) => (
                        <tr key={recording.id}>
                          <td>
                            <strong>{recording.run_name}</strong>
                            <span className="subline">{recording.id}</span>
                          </td>
                          <td>{recording.blueprint_id}</td>
                          <td>{recording.source_type ?? "unknown"}</td>
                          <td>{recording.tags.join(", ") || "-"}</td>
                          <td>
                            <button onClick={() => addTagToRecording(recording.id)}>
                              <Tags size={16} />
                              Add Tag
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <EmptyState text="Build a recording to populate the local run catalog." />
            )}
          </section>

          <section className="surface">
            <div className="section-heading">
              <Search size={18} />
              <h3>Query Console</h3>
            </div>
            <div className="query-controls">
              <select
                value={selectedQueryTemplate}
                onChange={(event) => setSelectedQueryTemplate(event.target.value)}
              >
                {queryTemplates.map((template) => (
                  <option key={template.template_id} value={template.template_id}>
                    {template.name}
                  </option>
                ))}
              </select>
              <select
                value={selectedQueryRecording}
                onChange={(event) => setSelectedQueryRecording(event.target.value)}
              >
                <option value="">All recordings</option>
                {recordings.map((recording) => (
                  <option key={recording.id} value={recording.id}>
                    {recording.run_name}
                  </option>
                ))}
              </select>
              {thresholdTemplates.has(selectedQueryTemplate) && (
                <input
                  value={queryThreshold}
                  onChange={(event) => setQueryThreshold(event.target.value)}
                />
              )}
              <button className="primary" onClick={runQuery}>
                <Search size={16} />
                Run Query
              </button>
              <button onClick={exportQuery}>
                <Download size={16} />
                Export CSV
              </button>
            </div>
            {exportPath && <p className="path-line light">Exported: {exportPath}</p>}
            {queryResult?.rows.length ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      {queryResult.columns.map((column) => (
                        <th key={column}>{column}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {queryResult.rows.slice(0, 50).map((row, index) => (
                      <tr key={index}>
                        {queryResult.columns.map((column) => (
                          <td key={column}>{formatCell(row[column])}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState text="Run a query to see matching samples, frames, or topics." />
            )}
          </section>

          <section className="surface">
            <div className="section-heading">
              <Search size={18} />
              <h3>Run Compare</h3>
            </div>
            <div className="query-controls">
              <input
                placeholder="recording ids separated by comma"
                value={compareRecordingIds}
                onChange={(event) => setCompareRecordingIds(event.target.value)}
              />
              <input
                placeholder="metric tokens, e.g. battery temperature"
                value={compareMetric}
                onChange={(event) => setCompareMetric(event.target.value)}
              />
              <button className="primary" onClick={runCompare}>
                <Search size={16} />
                Compare
              </button>
            </div>
            {compareResult?.rows.length ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      {compareResult.columns.map((column) => (
                        <th key={column}>{column}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {compareResult.rows.slice(0, 50).map((row, index) => (
                      <tr key={index}>
                        {compareResult.columns.map((column) => (
                          <td key={column}>{formatCell(row[column])}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState text="Select two or more recordings from the browser and compare scalar summaries." />
            )}
          </section>
        </div>

        <section className="surface">
          <div className="section-heading">
            <ListChecks size={18} />
            <h3>Jobs</h3>
          </div>
          {jobs.length ? (
            <div className="job-list">
              {jobs.slice(0, 6).map((job) => (
                <span key={job.id}>
                  {job.type} / {job.status} / {Math.round(job.progress * 100)}%
                </span>
              ))}
            </div>
          ) : (
            <EmptyState text="Conversion and query jobs will appear here." />
          )}
        </section>

        <section className="surface">
          <div className="section-heading">
            <Database size={18} />
            <h3>Plugin & Template Registry</h3>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Kind</th>
                  <th>Name</th>
                  <th>Version</th>
                  <th>Status</th>
                  <th>Path / App</th>
                </tr>
              </thead>
              <tbody>
                {plugins.map((plugin) => (
                  <tr key={`plugin-${plugin.id}`}>
                    <td>plugin</td>
                    <td>{plugin.name}</td>
                    <td>{plugin.version}</td>
                    <td>{plugin.status}</td>
                    <td>{plugin.path}</td>
                  </tr>
                ))}
                {templateRegistry.map((template) => (
                  <tr key={`template-${template.id}`}>
                    <td>template</td>
                    <td>{template.name}</td>
                    <td>{template.version}</td>
                    <td>{template.enabled ? "enabled" : "disabled"}</td>
                    <td>{template.app_id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </section>
    </main>
  );
}

const thresholdTemplates = new Set(["low_battery", "detection_failure"]);

function formatCell(value: unknown) {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function StreamTable({ streams }: { streams: StreamInfo[] }) {
  if (!streams.length) return <EmptyState text="No streams detected yet." />;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Semantic Type</th>
            <th>Fields</th>
            <th>Time</th>
            <th>Confidence</th>
          </tr>
        </thead>
        <tbody>
          {streams.map((stream) => (
            <tr key={stream.stream_id}>
              <td>{stream.name}</td>
              <td>{stream.semantic_type}</td>
              <td>{stream.fields.join(", ")}</td>
              <td>{stream.time_key ?? "row"}</td>
              <td>{Math.round(stream.confidence * 100)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return <div className="empty-state">{text}</div>;
}

export default App;
