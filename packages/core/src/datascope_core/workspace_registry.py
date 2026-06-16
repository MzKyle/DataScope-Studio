from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from datascope_core.adapters.registry import adapter_for_path, adapter_for_type
from datascope_core.mapping import mapping_from_yaml_dict, mapping_to_yaml_dict
from datascope_core.mapping_templates import (
    apply_mapping_template,
    diff_template_applications,
    load_mapping_template,
    save_mapping_template,
    template_from_mapping,
    validate_mapping_template,
)
from datascope_core.mapping_validation import build_validation_report
from datascope_core.plugin_registry import (
    instantiate_entrypoint,
    load_plugin_manifest,
    validate_plugin,
)
from datascope_core.template_registry import (
    BUILTIN_TEMPLATES,
    load_template_manifest,
    validate_template,
)
from datascope_core.workspace_utils import (
    mapping_template_from_row,
    plugin_from_row,
    source_info_from_row,
    template_from_row,
    utc_now,
)


class WorkspaceRegistryMixin:
    root: Path

    def list_plugins(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("select * from plugins order by installed_at desc").fetchall()
        return [plugin_from_row(row) for row in rows]

    def validate_plugin(self, path: str) -> dict[str, Any]:
        return validate_plugin(path)

    def install_plugin(self, path: str, enabled: bool = True) -> dict[str, Any]:
        validation = self.validate_plugin(path)
        if not validation["valid"]:
            raise ValueError("; ".join(validation["errors"]))
        manifest = load_plugin_manifest(path)
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                insert into plugins
                  (id, name, version, path, status, manifest_json, installed_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                  name = excluded.name,
                  version = excluded.version,
                  path = excluded.path,
                  status = excluded.status,
                  manifest_json = excluded.manifest_json,
                  updated_at = excluded.updated_at
                """,
                (
                    manifest.id,
                    manifest.name,
                    manifest.version,
                    manifest.path,
                    "enabled" if enabled else "disabled",
                    json.dumps(manifest.to_dict(), ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return self.get_plugin(manifest.id)

    def get_plugin(self, plugin_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("select * from plugins where id = ?", (plugin_id,)).fetchone()
        if row is None:
            raise KeyError(f"Plugin not found: {plugin_id}")
        return plugin_from_row(row)

    def list_templates(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "select * from template_registry order by source, name"
            ).fetchall()
        return [template_from_row(row) for row in rows]

    def template_app_ids(self) -> dict[str, str]:
        return {
            template["id"]: template["app_id"]
            for template in self.list_templates()
            if template["enabled"]
        }

    def validate_template(self, path: str) -> dict[str, Any]:
        return validate_template(path)

    def install_template(self, path: str, enabled: bool = True) -> dict[str, Any]:
        validation = self.validate_template(path)
        if not validation["valid"]:
            raise ValueError("; ".join(validation.get("errors", [])))
        manifest = load_template_manifest(path)
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                insert into template_registry
                  (id, name, version, app_id, source, path, manifest_json, enabled, installed_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                  name = excluded.name,
                  version = excluded.version,
                  app_id = excluded.app_id,
                  source = excluded.source,
                  path = excluded.path,
                  manifest_json = excluded.manifest_json,
                  enabled = excluded.enabled,
                  updated_at = excluded.updated_at
                """,
                (
                    manifest.id,
                    manifest.name,
                    manifest.version,
                    manifest.app_id,
                    manifest.source,
                    manifest.path,
                    json.dumps(manifest.to_dict(), ensure_ascii=False),
                    1 if enabled else 0,
                    now,
                    now,
                ),
            )
        return self.get_template(manifest.id)

    def get_template(self, template_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "select * from template_registry where id = ?",
                (template_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Template not found: {template_id}")
        return template_from_row(row)

    def list_mapping_templates(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "select * from mapping_template_registry order by name"
            ).fetchall()
        return [mapping_template_from_row(row) for row in rows]

    def get_mapping_template(self, template_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "select * from mapping_template_registry where id = ?",
                (template_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Mapping template not found: {template_id}")
        return mapping_template_from_row(row)

    def save_mapping_template(
        self,
        payload: dict[str, Any],
        *,
        enabled: bool = True,
    ) -> dict[str, Any]:
        validation = validate_mapping_template(payload)
        if not validation["valid"]:
            raise ValueError("; ".join(validation["errors"]))
        template = validation["template"]
        path = self.root / "mapping_templates" / f"{template['id']}.yaml"
        save_mapping_template({"mapping_template": template}, path)
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                insert into mapping_template_registry
                  (id, name, version, source_family, visual_template_id, path,
                   config_json, enabled, installed_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                  name = excluded.name,
                  version = excluded.version,
                  source_family = excluded.source_family,
                  visual_template_id = excluded.visual_template_id,
                  path = excluded.path,
                  config_json = excluded.config_json,
                  enabled = excluded.enabled,
                  updated_at = excluded.updated_at
                """,
                (
                    template["id"],
                    template["name"],
                    template["version"],
                    template["source_family"],
                    template.get("visual_template_id") or "sensor_monitor",
                    str(path),
                    json.dumps({"mapping_template": template}, ensure_ascii=False),
                    1 if enabled else 0,
                    now,
                    now,
                ),
            )
        return self.get_mapping_template(template["id"])

    def create_mapping_template(
        self,
        name: str,
        source_id: str,
        mapping_id: str,
        *,
        template_id: str | None = None,
    ) -> dict[str, Any]:
        source = self.get_source(source_id)
        mapping = self.get_mapping(mapping_id)
        if mapping["source_id"] != source_id:
            raise ValueError("Mapping does not belong to source")
        spec = mapping_from_yaml_dict(mapping["config"])
        payload = template_from_mapping(
            name,
            spec,
            source_info_from_row(source),
            template_id=template_id,
        )
        return self.save_mapping_template(payload)

    def import_mapping_template(
        self,
        path: str,
        *,
        enabled: bool = True,
    ) -> dict[str, Any]:
        return self.save_mapping_template(load_mapping_template(path), enabled=enabled)

    def export_mapping_template(
        self,
        template_id: str,
        output_path: str | None = None,
    ) -> dict[str, Any]:
        template = self.get_mapping_template(template_id)
        source_path = Path(template["path"])
        if output_path:
            requested = Path(output_path).expanduser()
            destination = (
                requested / source_path.name
                if requested.exists() and requested.is_dir()
                else requested
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)
        else:
            destination = source_path
        return {"template_id": template_id, "path": str(destination)}

    def delete_mapping_template(self, template_id: str) -> dict[str, Any]:
        template = self.get_mapping_template(template_id)
        with self._connect() as conn:
            conn.execute(
                "delete from mapping_template_registry where id = ?",
                (template_id,),
            )
        Path(template["path"]).unlink(missing_ok=True)
        return {"deleted": template_id}

    def apply_mapping_template(
        self,
        template_id: str,
        source_id: str,
    ) -> dict[str, Any]:
        template = self.get_mapping_template(template_id)
        source = self.get_source(source_id)
        streams = self.get_streams(source_id)
        if not streams:
            self.inspect_source(source_id)
            streams = self.get_streams(source_id)
        source_info = source_info_from_row(source)
        profile = self.get_schema_profile(source_id)
        spec, match_issues = apply_mapping_template(
            template["config"],
            source_info,
            streams,
            profile,
        )
        spec.app_id = self.template_app_ids().get(
            spec.template_id or "",
            "datascope.sensor_monitor.v1",
        )
        report = self.validate_mapping_spec(source_id, spec)
        report = build_validation_report(
            source_info,
            spec,
            profile,
            [*match_issues, *report["issues"]],
        )
        enriched_match_issues = build_validation_report(
            source_info,
            spec,
            profile,
            match_issues,
        )["issues"]
        spec.effective_timeline_unit = report["effective_timeline_unit"]
        return {
            "mapping": mapping_to_yaml_dict(spec)["mapping"],
            "validation": report,
            "match_issues": enriched_match_issues,
        }

    def diff_mapping_template(
        self,
        project_id: str,
        template_id: str,
        left_source_id: str,
        right_source_id: str,
    ) -> dict[str, Any]:
        source_ids = {source["id"] for source in self.list_sources(project_id)}
        if left_source_id not in source_ids or right_source_id not in source_ids:
            raise ValueError("Both diff sources must belong to the selected project")
        left_result = self._mapping_application_for_diff(template_id, left_source_id)
        right_result = self._mapping_application_for_diff(template_id, right_source_id)
        result = diff_template_applications(
            mapping_from_yaml_dict({"mapping": left_result["mapping"]}),
            mapping_from_yaml_dict({"mapping": right_result["mapping"]}),
            left_result["validation"]["issues"],
            right_result["validation"]["issues"],
        )
        result.update(
            {
                "template_id": template_id,
                "left_source_id": left_source_id,
                "right_source_id": right_source_id,
            }
        )
        return result

    def _mapping_application_for_diff(
        self,
        template_id: str,
        source_id: str,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select config_json from mappings
                where source_id = ?
                order by updated_at desc
                """,
                (source_id,),
            ).fetchall()
        for row in rows:
            config = json.loads(row["config_json"] or "{}")
            mapping = config.get("mapping", {})
            if mapping.get("mapping_template_id") != template_id:
                continue
            spec = mapping_from_yaml_dict(config)
            return {
                "mapping": mapping_to_yaml_dict(spec)["mapping"],
                "validation": self.validate_mapping_spec(source_id, spec),
                "match_issues": [],
            }
        return self.apply_mapping_template(template_id, source_id)

    def _adapter_for_type(self, source_type: str):
        try:
            return adapter_for_type(source_type)
        except ValueError:
            plugin_adapter = self._plugin_adapter_for_type(source_type)
            if plugin_adapter is None:
                raise
            return plugin_adapter

    def _adapter_for_path(self, path: str, source_type: str | None = None):
        if source_type:
            return self._adapter_for_type(source_type)
        try:
            return adapter_for_path(path)
        except ValueError:
            return self._adapter_for_type(self._detect_plugin_source_type(Path(path)))

    def _detect_plugin_source_type(self, source_path: Path) -> str:
        for adapter in self._enabled_plugin_adapters():
            suffixes = {
                suffix.lower()
                for suffix in getattr(adapter, "supported_extensions", [])
            }
            if source_path.is_file() and source_path.suffix.lower() in suffixes:
                return str(getattr(adapter, "adapter_id"))
            if source_path.is_dir() and not suffixes:
                return str(getattr(adapter, "adapter_id"))
        raise ValueError(f"Unsupported source type for path: {source_path}")

    def _plugin_adapter_for_type(self, source_type: str):
        for adapter in self._enabled_plugin_adapters():
            if getattr(adapter, "adapter_id", None) == source_type:
                return adapter
        return None

    def _enabled_plugin_adapters(self) -> list[Any]:
        adapters = []
        for plugin in self.list_plugins():
            if plugin["status"] != "enabled":
                continue
            manifest = plugin["manifest"]
            for entrypoint in manifest.get("entrypoints", {}).get("adapters", {}).values():
                adapter = instantiate_entrypoint(plugin["path"], entrypoint)
                if not hasattr(adapter, "adapter_id"):
                    raise ValueError(f"Plugin adapter missing adapter_id: {entrypoint}")
                adapters.append(adapter)
        return adapters

    def _register_builtin_templates(self) -> None:
        now = utc_now()
        with self._connect() as conn:
            for template in BUILTIN_TEMPLATES:
                conn.execute(
                    """
                    insert into template_registry
                      (id, name, version, app_id, source, path, manifest_json, enabled, installed_at, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    on conflict(id) do update set
                      name = excluded.name,
                      version = excluded.version,
                      app_id = excluded.app_id,
                      source = excluded.source,
                      manifest_json = excluded.manifest_json,
                      enabled = 1,
                      updated_at = excluded.updated_at
                    """,
                    (
                        template["id"],
                        template["name"],
                        template["version"],
                        template["app_id"],
                        "builtin",
                        None,
                        json.dumps(template, ensure_ascii=False),
                        1,
                        now,
                        now,
                    ),
                )
