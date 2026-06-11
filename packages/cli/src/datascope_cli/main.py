from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

import typer

from datascope_core.adapters.registry import adapter_for_path
from datascope_core.mapping import mapping_to_yaml_dict
from datascope_core.viewer import open_recording
from datascope_core.workspace import Workspace


app = typer.Typer(help="DataScope Studio local-first data import tools.")
plugin_app = typer.Typer(help="Install and validate local DataScope plugins.")
template_app = typer.Typer(help="Install and validate local DataScope templates.")
batch_app = typer.Typer(help="Run batch import workflows.")
project_app = typer.Typer(help="Project packaging tools.")
mapping_app = typer.Typer(help="Validate mappings and manage reusable mapping templates.")
mapping_template_app = typer.Typer(help="Manage reusable mapping templates.")

app.add_typer(plugin_app, name="plugin")
app.add_typer(template_app, name="template")
app.add_typer(batch_app, name="batch")
app.add_typer(project_app, name="project")
app.add_typer(mapping_app, name="mapping")
mapping_app.add_typer(mapping_template_app, name="template")


@app.command()
def inspect(path: Path, json_output: bool = typer.Option(False, "--json", help="Print JSON.")) -> None:
    """Inspect a CSV, JSONL, image folder, point cloud, or MCAP source."""
    adapter = _adapter_for_cli_path(path)
    source = adapter.inspect(str(path))
    streams = adapter.infer_streams(source)
    if json_output:
        _echo_json({"source": asdict(source), "streams": [asdict(stream) for stream in streams]})
        return
    typer.echo(f"Source type: {source.source_type}")
    if source.source_type == "image_folder":
        typer.echo(f"Images: {source.metadata.get('image_count', 0)}")
        typer.echo(f"Annotation frames: {source.metadata.get('annotation_frame_count', 0)}")
        typer.echo(f"Prediction frames: {source.metadata.get('prediction_frame_count', 0)}")
    elif source.source_type == "mcap":
        typer.echo(f"Topics: {source.metadata.get('topic_count', 0)}")
        typer.echo(f"Messages: {source.metadata.get('message_count', 0)}")
        if source.metadata.get("inspect_warning"):
            typer.echo(f"Warning: {source.metadata['inspect_warning']}")
    elif source.source_type == "point_cloud":
        typer.echo(f"Point clouds: {source.metadata.get('point_cloud_count', 0)}")
        typer.echo(f"Formats: {', '.join(source.metadata.get('formats', []))}")
        typer.echo(
            "Sampled points: "
            f"{source.metadata.get('sampled_point_count_min', 0)}-"
            f"{source.metadata.get('sampled_point_count_max', 0)}"
        )
    else:
        typer.echo(f"Rows: {source.metadata.get('rows', 0)}")
        typer.echo(f"Columns: {', '.join(source.metadata.get('columns', []))}")
    typer.echo("Detected streams:")
    for stream in streams:
        fields = ", ".join(stream.fields)
        typer.echo(
            f"  {stream.name} -> {stream.semantic_type} "
            f"({fields}) confidence={stream.confidence:.2f}"
        )


@app.command("import")
def import_source(
    path: Path,
    project: str = typer.Option(..., "--project", help="Project name."),
    template: str = typer.Option("sensor_monitor", "--template", help="Template id."),
    out: str = typer.Option("run", "--out", help="Output recording base name."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON."),
) -> None:
    """Import a source into a project and build .rrd/.rbl artifacts."""
    workspace = Workspace(os.environ.get("DATASCOPE_WORKSPACE"))
    existing = next((item for item in workspace.list_projects() if item["name"] == project), None)
    project_row = existing or workspace.create_project(project)
    source = workspace.add_source(project_row["id"], str(path))
    inspection = workspace.inspect_source(source["id"])
    spec = workspace.suggest_mapping(source["id"], template_id=template)
    saved_mapping = workspace.save_mapping(project_row["id"], source["id"], spec)
    result = workspace.build_recording(
        project_row["id"],
        source["id"],
        mapping_id=saved_mapping["id"],
        output_name=out,
        template_id=template,
    )

    if json_output:
        _echo_json(
            {
                "project": project_row,
                "source": source,
                "streams": inspection["streams"],
                "mapping": saved_mapping,
                "result": result,
            }
        )
        return
    typer.echo(f"Project: {project_row['name']} ({project_row['id']})")
    typer.echo(f"Source: {source['id']}")
    typer.echo(f"Streams: {len(inspection['streams'])}")
    typer.echo(f"Mapping: {saved_mapping['path']}")
    typer.echo(f"Recording: {result['recording_path']}")
    typer.echo(f"Blueprint: {result['blueprint_path']}")


@app.command()
def open(
    recording: Path,
    blueprint: Path | None = typer.Option(None, "--blueprint", help="Optional .rbl file."),
) -> None:
    """Open a generated recording in the local Rerun Viewer."""
    try:
        result = open_recording(str(recording), str(blueprint) if blueprint else None)
    except RuntimeError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Rerun started: pid={result['pid']}")


@app.command()
def suggest_mapping(path: Path) -> None:
    """Print the mapping YAML that would be generated for a source."""
    adapter = _adapter_for_cli_path(path)
    source = adapter.inspect(str(path))
    streams = adapter.infer_streams(source)
    from datascope_core.mapping import suggest_mapping as suggest

    spec = suggest(source, streams)
    typer.echo(mapping_to_yaml_dict(spec))


@mapping_app.command("validate")
def mapping_validate(
    mapping_id: str,
    json_output: bool = typer.Option(False, "--json", help="Print JSON."),
) -> None:
    """Validate a saved mapping."""
    workspace = Workspace(os.environ.get("DATASCOPE_WORKSPACE"))
    report = workspace.validate_saved_mapping(mapping_id)
    if json_output:
        _echo_json(report)
        return
    typer.echo(
        f"{mapping_id}: {'valid' if report['valid'] else 'invalid'} "
        f"errors={report['summary']['errors']} warnings={report['summary']['warnings']}"
    )
    for issue in report["issues"]:
        typer.echo(f"  {issue['severity']} {issue['code']}: {issue['message']}")
        typer.echo(f"    recommendation: {issue['recommendation']}")
        for suggestion in issue.get("suggestions", []):
            typer.echo(f"    suggestion: {suggestion['label']}")
    if not report["valid"]:
        raise typer.Exit(code=1)


@mapping_app.command("confirm")
def mapping_confirm(mapping_id: str) -> None:
    """Validate and confirm a saved mapping."""
    workspace = Workspace(os.environ.get("DATASCOPE_WORKSPACE"))
    result = workspace.confirm_mapping(mapping_id)
    typer.echo(
        f"Confirmed {mapping_id} "
        f"warnings={result['validation']['summary']['warnings']}"
    )


@mapping_app.command("diff")
def mapping_diff(
    project: str = typer.Option(..., "--project", help="Project name or id."),
    template: str = typer.Option(..., "--template", help="Mapping template id."),
    left: str = typer.Option(..., "--left", help="Left source id."),
    right: str = typer.Option(..., "--right", help="Right source id."),
) -> None:
    """Compare one mapping template across two project sources."""
    workspace = Workspace(os.environ.get("DATASCOPE_WORKSPACE"))
    project_row = _project_by_name_or_id(workspace, project)
    _echo_json(workspace.diff_mapping_template(project_row["id"], template, left, right))


@mapping_template_app.command("list")
def mapping_template_list(
    json_output: bool = typer.Option(False, "--json", help="Print JSON."),
) -> None:
    """List reusable mapping templates."""
    workspace = Workspace(os.environ.get("DATASCOPE_WORKSPACE"))
    rows = workspace.list_mapping_templates()
    if json_output:
        _echo_json(rows)
        return
    for template in rows:
        typer.echo(
            f"{template['id']}  {template['version']}  "
            f"{template['source_family']}  {template['name']}"
        )


@mapping_template_app.command("create")
def mapping_template_create(
    name: str = typer.Option(..., "--name", help="Template display name."),
    source_id: str = typer.Option(..., "--source", help="Source id."),
    mapping_id: str = typer.Option(..., "--mapping", help="Saved mapping id."),
    template_id: str | None = typer.Option(None, "--id", help="Optional stable template id."),
) -> None:
    """Create a mapping template from a saved mapping."""
    workspace = Workspace(os.environ.get("DATASCOPE_WORKSPACE"))
    _echo_json(
        workspace.create_mapping_template(
            name,
            source_id,
            mapping_id,
            template_id=template_id,
        )
    )


@mapping_template_app.command("import")
def mapping_template_import(path: Path) -> None:
    """Import a mapping template YAML."""
    workspace = Workspace(os.environ.get("DATASCOPE_WORKSPACE"))
    _echo_json(workspace.import_mapping_template(str(path)))


@mapping_template_app.command("export")
def mapping_template_export(
    template_id: str,
    out: Path | None = typer.Option(None, "--out", help="Output YAML path or directory."),
) -> None:
    """Export a mapping template YAML."""
    workspace = Workspace(os.environ.get("DATASCOPE_WORKSPACE"))
    result = workspace.export_mapping_template(
        template_id,
        output_path=str(out) if out else None,
    )
    typer.echo(result["path"])


@app.command()
def recordings(
    project: str = typer.Option(..., "--project", help="Project name or id."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON."),
) -> None:
    """List recordings for a project."""
    workspace = Workspace(os.environ.get("DATASCOPE_WORKSPACE"))
    project_row = _project_by_name_or_id(workspace, project)
    rows = workspace.list_recordings(project_row["id"])
    if json_output:
        _echo_json(rows)
        return
    for recording in rows:
        tags = ",".join(recording["tags"])
        typer.echo(
            f"{recording['id']}  {recording['run_name']}  "
            f"{recording.get('blueprint_id') or ''}  tags=[{tags}]  {recording['path']}"
        )


@app.command()
def tag(
    recording_id: str,
    add: list[str] = typer.Option([], "--add", help="Tag to add. Repeatable."),
    remove: list[str] = typer.Option([], "--remove", help="Tag to remove. Repeatable."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON."),
) -> None:
    """Add or remove recording tags."""
    workspace = Workspace(os.environ.get("DATASCOPE_WORKSPACE"))
    recording = workspace.update_recording(recording_id, add_tags=add, remove_tags=remove)
    if json_output:
        _echo_json(recording)
        return
    typer.echo(f"{recording['id']} tags={','.join(recording['tags'])}")


@app.command()
def query(
    project: str = typer.Option(..., "--project", help="Project name or id."),
    template: str = typer.Option(..., "--template", help="Query template id."),
    recording: list[str] = typer.Option([], "--recording", help="Recording id. Repeatable."),
    threshold: float | None = typer.Option(None, "--threshold", help="Threshold for supported templates."),
    limit: int = typer.Option(1000, "--limit", help="Maximum rows."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON."),
) -> None:
    """Run a local DataScope query template."""
    workspace = Workspace(os.environ.get("DATASCOPE_WORKSPACE"))
    project_row = _project_by_name_or_id(workspace, project)
    params = {"threshold": threshold} if threshold is not None else {}
    result = workspace.run_query(
        project_row["id"],
        template,
        recording_ids=recording or None,
        params=params,
        limit=limit,
    )
    _echo_json(result)


@app.command("export-query")
def export_query(
    project: str = typer.Option(..., "--project", help="Project name or id."),
    template: str = typer.Option(..., "--template", help="Query template id."),
    recording: list[str] = typer.Option([], "--recording", help="Recording id. Repeatable."),
    threshold: float | None = typer.Option(None, "--threshold", help="Threshold for supported templates."),
    fmt: str = typer.Option("csv", "--format", help="csv or parquet."),
    out: Path | None = typer.Option(None, "--out", help="Optional output path."),
    limit: int = typer.Option(1000, "--limit", help="Maximum rows."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON."),
) -> None:
    """Export a local DataScope query result."""
    workspace = Workspace(os.environ.get("DATASCOPE_WORKSPACE"))
    project_row = _project_by_name_or_id(workspace, project)
    params = {"threshold": threshold} if threshold is not None else {}
    result = workspace.export_query(
        project_row["id"],
        template,
        recording_ids=recording or None,
        params=params,
        limit=limit,
        fmt=fmt,
        output_path=str(out) if out else None,
    )
    if json_output:
        _echo_json(result)
        return
    typer.echo(f"Exported {result['rows']} rows to {result['path']}")


@app.command()
def compare(
    recording_id: list[str] = typer.Argument(..., help="Recording ids to compare."),
    project: str = typer.Option(..., "--project", help="Project name or id."),
    metric: list[str] = typer.Option([], "--metric", help="Metric key or path token. Repeatable."),
    mode: str = typer.Option("summary", "--mode", help="summary or series."),
    limit: int = typer.Option(1000, "--limit", help="Maximum rows."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON."),
) -> None:
    """Compare scalar/state rows across recordings."""
    workspace = Workspace(os.environ.get("DATASCOPE_WORKSPACE"))
    project_row = _project_by_name_or_id(workspace, project)
    result = workspace.compare(project_row["id"], recording_id, metric_keys=metric, mode=mode, limit=limit)
    if json_output or mode == "series":
        _echo_json(result)
        return
    for row in result["rows"]:
        typer.echo(
            f"{row['recording_id']}  {row['key']}  {row['entity_path']}  "
            f"{json.dumps(row['value'], ensure_ascii=False)}"
        )


@plugin_app.command("list")
def plugin_list(json_output: bool = typer.Option(False, "--json", help="Print JSON.")) -> None:
    """List installed plugins."""
    workspace = Workspace(os.environ.get("DATASCOPE_WORKSPACE"))
    rows = workspace.list_plugins()
    if json_output:
        _echo_json(rows)
        return
    for plugin in rows:
        typer.echo(f"{plugin['id']}  {plugin['version']}  {plugin['status']}  {plugin['path']}")


@plugin_app.command("validate")
def plugin_validate(path: Path) -> None:
    """Validate a local plugin manifest and entrypoints."""
    workspace = Workspace(os.environ.get("DATASCOPE_WORKSPACE"))
    _echo_json(workspace.validate_plugin(str(path)))


@plugin_app.command("install")
def plugin_install(
    path: Path,
    disabled: bool = typer.Option(False, "--disabled", help="Install but keep disabled."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON."),
) -> None:
    """Install a local plugin directory or plugin.yaml."""
    workspace = Workspace(os.environ.get("DATASCOPE_WORKSPACE"))
    plugin = workspace.install_plugin(str(path), enabled=not disabled)
    if json_output:
        _echo_json(plugin)
        return
    typer.echo(f"Installed plugin {plugin['id']} ({plugin['status']})")


@template_app.command("list")
def template_list(json_output: bool = typer.Option(False, "--json", help="Print JSON.")) -> None:
    """List builtin and installed templates."""
    workspace = Workspace(os.environ.get("DATASCOPE_WORKSPACE"))
    rows = workspace.list_templates()
    if json_output:
        _echo_json(rows)
        return
    for template in rows:
        status = "enabled" if template["enabled"] else "disabled"
        typer.echo(f"{template['id']}  {template['version']}  {status}  {template['app_id']}")


@template_app.command("validate")
def template_validate(path: Path) -> None:
    """Validate a local template manifest."""
    workspace = Workspace(os.environ.get("DATASCOPE_WORKSPACE"))
    _echo_json(workspace.validate_template(str(path)))


@template_app.command("install")
def template_install(
    path: Path,
    disabled: bool = typer.Option(False, "--disabled", help="Install but keep disabled."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON."),
) -> None:
    """Install a local template manifest."""
    workspace = Workspace(os.environ.get("DATASCOPE_WORKSPACE"))
    template = workspace.install_template(str(path), enabled=not disabled)
    if json_output:
        _echo_json(template)
        return
    typer.echo(f"Installed template {template['id']}")


@batch_app.command("import")
def batch_import(
    pattern: list[str] = typer.Argument(..., help="Source paths or glob patterns."),
    project: str = typer.Option(..., "--project", help="Project name or id."),
    template: str = typer.Option("sensor_monitor", "--template", help="Template id."),
    out: str = typer.Option("batch_run", "--out", help="Output recording prefix."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON."),
) -> None:
    """Import multiple sources into a project."""
    workspace = Workspace(os.environ.get("DATASCOPE_WORKSPACE"))
    project_row = _project_by_name_or_id(workspace, project)
    result = workspace.batch_import(project_row["id"], pattern, template_id=template, output_prefix=out)
    if json_output:
        _echo_json(result)
        return
    typer.echo(
        f"{result['id']}  {result['status']}  total={result['total']}  "
        f"succeeded={result['succeeded']}  failed={result['failed']}"
    )


@project_app.command("export")
def project_export(
    project: str = typer.Option(..., "--project", help="Project name or id."),
    out: Path | None = typer.Option(None, "--out", help="Output .zip path or export directory."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON."),
) -> None:
    """Export a project package zip."""
    workspace = Workspace(os.environ.get("DATASCOPE_WORKSPACE"))
    project_row = _project_by_name_or_id(workspace, project)
    result = workspace.export_project(project_row["id"], output_path=str(out) if out else None)
    if json_output:
        _echo_json(result)
        return
    typer.echo(f"Exported project to {result['path']}")


@project_app.command("import")
def project_import(
    package: Path,
    name: str | None = typer.Option(None, "--name", help="Optional imported project name."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON."),
) -> None:
    """Import a previously exported DataScope project package zip."""
    workspace = Workspace(os.environ.get("DATASCOPE_WORKSPACE"))
    result = workspace.import_project_package(str(package), project_name=name)
    if json_output:
        _echo_json(result)
        return
    typer.echo(
        f"Imported project {result['project']['name']} "
        f"({result['project']['id']}) with {len(result['recordings'])} recordings"
    )


def _project_by_name_or_id(workspace: Workspace, value: str) -> dict:
    for project in workspace.list_projects():
        if project["id"] == value or project["name"] == value:
            return project
    raise typer.BadParameter(f"Project not found: {value}")


def _adapter_for_cli_path(path: Path):
    workspace = Workspace(os.environ.get("DATASCOPE_WORKSPACE"))
    try:
        return adapter_for_path(str(path))
    except ValueError:
        return workspace._adapter_for_path(str(path))  # noqa: SLF001


def _echo_json(value) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    app()
