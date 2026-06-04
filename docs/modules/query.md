# 查询系统

V0.5 之后，DataScope Studio 在转换时生成轻量 query index，优先写入 SQLite 表 `query_rows`。

## Query Row

`query_rows` 保存：

| 字段 | 说明 |
| --- | --- |
| `recording_id` | 所属 recording |
| `source_id` | 来源数据源 |
| `time` | 归一化后的查询时间 |
| `entity_path` | Rerun entity path |
| `semantic_type` | scalar、state、text_log、boxes2d 等 |
| `key` | 字段名或统计项 |
| `value_json` | JSON 值 |

## 内置查询模板

| 模板 | 用途 |
| --- | --- |
| `find_errors` | 在日志和状态中查找 ERROR/WARN/fault/error |
| `low_battery` | 查找 battery scalar 低于阈值 |
| `detection_failure` | 查找低置信度或无预测框的检测帧 |
| `topic_summary` | 汇总 MCAP topic、role、message_count |
| `state_duration` | 估算状态持续时间 |
| `time_sync` | 查询 timestamp/frame 时间差异 |

## 导出

CSV 导出必须可用。Parquet 导出依赖 `pyarrow`，缺失时返回明确错误。
