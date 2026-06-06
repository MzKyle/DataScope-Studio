# 状态模型

## Job 状态

Job 状态固定为：

```text
pending | running | succeeded | failed
```

转换、批量导入、导出等长任务都会登记到 `jobs` 或 batch 表中，供桌面端和 CLI 查询。

## Source 生命周期

```text
imported -> inspected -> mapped -> converted
```

当前实现不会强制每一步都修改同一个状态字段，但用户工作流遵循这个顺序。

## Catalog 表

| 表 | 说明 |
| --- | --- |
| `projects` | 项目元数据和 workspace path |
| `sources` | 数据源副本、类型、checksum |
| `streams` | inspect 后推断出的语义流 |
| `mappings` | Mapping v2 YAML、draft/confirmed 状态 |
| `schema_profiles` | 按 source checksum 缓存的字段与时间统计 |
| `mapping_template_registry` | 工作区全局 Mapping 模板 |
| `recordings` | `.rrd`、`.rbl`、tags、params |
| `jobs` | 转换和后台任务 |
| `query_rows` | 本地查询索引 |
| `query_exports` | 查询导出记录 |

V1.0 扩展还包含 plugin、template、batch job 相关表。
