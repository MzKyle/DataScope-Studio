# HTTP API

默认服务地址：

```text
http://127.0.0.1:8000
```

## Project

| Method | Path | 说明 |
| --- | --- | --- |
| `POST` | `/api/projects` | 创建项目 |
| `GET` | `/api/projects` | 项目列表 |
| `GET` | `/api/projects/{project_id}` | 项目详情 |
| `POST` | `/api/projects/{project_id}/export` | 导出项目 zip |
| `POST` | `/api/projects/import` | 导入项目 zip |

## Source / Mapping / Recording

| Method | Path | 说明 |
| --- | --- | --- |
| `POST` | `/api/projects/{project_id}/sources` | 导入 source，可通过 `import_options.csv` 控制 CSV 表头和列名 |
| `GET` | `/api/projects/{project_id}/sources` | 项目 source 列表 |
| `POST` | `/api/sources/{source_id}/inspect` | inspect source |
| `GET` | `/api/sources/{source_id}/streams` | streams |
| `GET` | `/api/sources/{source_id}/preview` | preview |
| `GET` | `/api/sources/{source_id}/mapping/suggest` | mapping 建议 |
| `POST` | `/api/sources/{source_id}/mapping/preview` | mapping、schema profile、预览和校验 |
| `POST` | `/api/sources/{source_id}/mapping/validate` | 校验 mapping |
| `POST` | `/api/sources/{source_id}/mapping` | 保存 mapping draft |
| `POST` | `/api/mappings/{mapping_id}/confirm` | 校验并确认 mapping |
| `POST` | `/api/recordings/build` | 构建 `.rrd + .rbl`，可通过 `output_dir` 指定共同输出目录 |
| `POST` | `/api/projects/{project_id}/estimates/build/{source_id}` | 估算构建空间，可通过 `output_dir` 查询参数指定目标磁盘 |
| `POST` | `/api/viewer/open` | 外部打开 Rerun |

导入无表头 CSV：

```json
{
  "path": "/data/pose.csv",
  "storage_mode": "copy",
  "import_options": {
    "csv": {
      "header_mode": "no_header",
      "column_names": ["timestamp", "x", "y", "z", "rx", "ry", "rz"]
    }
  }
}
```

`header_mode` 支持 `auto`、`header`、`no_header`。`column_names` 的数量必须与
CSV 实际列数一致且名称唯一。省略 `import_options` 时保持自动识别行为。

构建到共同产物目录：

```json
{
  "project_id": "<project_id>",
  "source_id": "<source_id>",
  "mapping_id": "<mapping_id>",
  "template_id": "sensor_monitor",
  "output_name": "pose",
  "output_dir": "/data/rerun-artifacts"
}
```

省略 `output_dir` 时，`.rrd` 和 `.rbl` 继续分别写入项目内的 `recordings/` 与
`blueprints/`。空间估算可调用
`POST /api/projects/{project_id}/estimates/build/{source_id}?output_dir=<目录>`。

## Catalog / Query

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/api/projects/{project_id}/recordings` | recording 列表 |
| `GET` | `/api/recordings/{recording_id}` | recording 详情 |
| `PATCH` | `/api/recordings/{recording_id}` | 更新 run name、tags、params |
| `GET` | `/api/projects/{project_id}/query/templates` | 查询模板 |
| `POST` | `/api/projects/{project_id}/query` | 执行查询 |
| `POST` | `/api/projects/{project_id}/query/export` | 导出查询结果 |
| `GET` | `/api/projects/{project_id}/diagnostics/presets` | 诊断阈值 preset |
| `POST` | `/api/projects/{project_id}/diagnostics` | 执行诊断 |
| `POST` | `/api/projects/{project_id}/diagnostics/export` | 持久化导出 JSON/CSV/HTML 诊断报告 |
| `GET` | `/api/projects/{project_id}/diagnostics/exports` | 诊断导出记录 |
| `POST` | `/api/compare` | 多 recording 对比 |
| `GET` | `/api/jobs/settings` | 当前 API 进程后台任务并发设置 |
| `PATCH` | `/api/jobs/settings` | 更新 `max_workers`，范围 `1..4` |

## Extension / Batch

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/api/plugins` | 插件列表 |
| `POST` | `/api/plugins/install` | 安装插件 |
| `POST` | `/api/plugins/validate` | 校验插件 |
| `GET` | `/api/templates` | 模板列表 |
| `POST` | `/api/templates/install` | 安装模板 |
| `GET` | `/api/mapping-templates` | Mapping 模板列表 |
| `POST` | `/api/mapping-templates` | 从已保存 mapping 创建模板 |
| `PUT` | `/api/mapping-templates/{template_id}` | 更新模板规则 |
| `DELETE` | `/api/mapping-templates/{template_id}` | 删除模板 |
| `POST` | `/api/mapping-templates/import` | 导入 Mapping 模板 YAML |
| `POST` | `/api/mapping-templates/{template_id}/export` | 导出 Mapping 模板 YAML |
| `POST` | `/api/mapping-templates/{template_id}/apply` | 将模板应用到 source |
| `POST` | `/api/projects/{project_id}/mapping-diff` | 比较模板在两个 source 上的结果 |
| `POST` | `/api/batch/import` | 批量导入 |
| `GET` | `/api/projects/{project_id}/batches` | 批量任务列表 |
| `POST` | `/api/projects/{project_id}/estimates/batch-import` | 批量导入磁盘估算 |
| `GET` | `/api/batch/{batch_id}` | 批量任务状态 |
| `POST` | `/api/batch/{batch_id}/items/{item_id}/retry` | 重试失败或已取消的单项 |
| `POST` | `/api/batch/{batch_id}/items/{item_id}/cancel` | 取消 pending/running 单项 |

构建前若存在 blocking error，API 返回 `409` 和
`error.code = mapping_validation_failed`，响应内包含完整 validation report。
