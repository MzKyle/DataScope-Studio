# Mapping YAML

Mapping YAML v2 连接 source fields、时间轴和 Rerun entity path。旧版无
`schema_version` 的文件会在加载时迁移为 v2，历史 `unit: seconds` 按自动识别处理。

```yaml
mapping:
  schema_version: 2
  id: mapping_source_001
  source: source_001
  app_id: datascope.sensor_monitor.v1
  recording_id: run_001
  template_id: sensor_monitor
  mapping_template_id: robot_sensor_v1
  status: draft
  timelines:
    primary:
      name: timestamp
      source_field: timestamp
      unit: auto
      effective_unit: unix_ms
  streams:
    - stream_id: stream_battery
      name: battery
      rule_key: battery
      origin: mapping_template
      enabled: true
      required: true
      source_fields: [battery]
      semantic_type: scalar
      entity_path: /metrics/battery
      archetype: Scalars
      view: TimeSeriesView
      confidence: 0.95
```

`archetype` 和 `view` 由 `semantic_type` 派生。桌面端允许编辑时间字段/单位、
source fields、semantic type、entity path 和 enabled 状态。

## 时间单位

支持 `auto`、`relative_s`、`unix_s`、`unix_ms`、`unix_us`、`unix_ns` 和
`datetime`。校验阶段会生成固定的 `effective_unit`，转换阶段不再逐行猜测。

每行始终记录 `row` sequence。时间值无效时会清除主时间线；查询索引保存
`null`，不会用行号伪装成时间。

## Mapping 模板

Mapping 模板与 Rerun blueprint 模板是不同 registry。模板 YAML 保存：

- source family 和默认可视化模板
- 时间字段、别名、正则和单位
- 稳定 rule key、字段角色、required/enabled
- semantic type、entity path 和 expected unit

字段匹配顺序固定为：精确名称、归一化名称、别名、正则。多个候选不会自动
选择，而是返回 `ambiguous_field_match`。

## 校验

错误会阻断确认和构建，例如必需字段缺失、歧义、非法/重复 entity path、
不支持的 semantic type 和坐标轴缺失。

警告允许继续，例如非单调时间、空值、时间解析失败、混合/可疑单位。

MCAP 参与模板、语义校验和 diff，但 entity path 由 Rerun MCAP importer
管理，桌面端显示为只读。
