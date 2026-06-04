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
| `POST` | `/api/projects/{project_id}/sources` | 导入 source |
| `POST` | `/api/sources/{source_id}/inspect` | inspect source |
| `GET` | `/api/sources/{source_id}/streams` | streams |
| `GET` | `/api/sources/{source_id}/preview` | preview |
| `GET` | `/api/sources/{source_id}/mapping/suggest` | mapping 建议 |
| `POST` | `/api/sources/{source_id}/mapping` | 保存 mapping |
| `POST` | `/api/recordings/build` | 构建 `.rrd + .rbl` |
| `POST` | `/api/viewer/open` | 外部打开 Rerun |

## Catalog / Query

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/api/projects/{project_id}/recordings` | recording 列表 |
| `GET` | `/api/recordings/{recording_id}` | recording 详情 |
| `PATCH` | `/api/recordings/{recording_id}` | 更新 run name、tags、params |
| `GET` | `/api/projects/{project_id}/query/templates` | 查询模板 |
| `POST` | `/api/projects/{project_id}/query` | 执行查询 |
| `POST` | `/api/projects/{project_id}/query/export` | 导出查询结果 |
| `POST` | `/api/compare` | 多 recording 对比 |

## Extension / Batch

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/api/plugins` | 插件列表 |
| `POST` | `/api/plugins/install` | 安装插件 |
| `POST` | `/api/plugins/validate` | 校验插件 |
| `GET` | `/api/templates` | 模板列表 |
| `POST` | `/api/templates/install` | 安装模板 |
| `POST` | `/api/batch/import` | 批量导入 |
| `GET` | `/api/batch/{batch_id}` | 批量任务状态 |
