from __future__ import annotations

from typing import Any

from datascope_core.workspace import Workspace


def run_import_workflow(
    workspace: Workspace,
    project_id: str,
    *,
    path: str,
    storage_mode: str = "copy",
    import_options: dict[str, Any] | None = None,
    template_id: str | None = None,
) -> dict[str, Any]:
    added = workspace.add_source(
        project_id,
        path,
        storage_mode=storage_mode,
        import_options=import_options or {},
    )
    inspection = workspace.inspect_source(added["id"])
    template_matches = workspace.suggest_templates(added["id"])
    selected_template_id = (
        template_id
        or (
            str(template_matches[0]["template_id"])
            if template_matches
            else "sensor_monitor"
        )
    )
    spec = workspace.suggest_mapping(
        added["id"],
        template_id=selected_template_id,
    )
    saved_mapping = workspace.save_mapping(project_id, added["id"], spec)
    mapping_preview = workspace.mapping_preview(added["id"], spec)
    return {
        "source": inspection["source"],
        "streams": inspection["streams"],
        "template_matches": template_matches,
        "template_id": selected_template_id,
        "mapping": {"mapping": mapping_preview["mapping"]},
        "saved_mapping": saved_mapping,
        "preview": mapping_preview["preview"],
        "schema_profile": mapping_preview["schema_profile"],
        "validation": mapping_preview["validation"],
    }
