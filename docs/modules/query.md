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

## 查询性能

转换完成后会把可查询内容写入 `query_rows`，后续查询优先读取这张轻量表，而不是
重新解析原始数据或 `.rrd` 文件。`low_battery`、`find_errors`、
`detection_failure` 和 `topic_summary` 等常见模板会通过 SQLite cursor 逐行处理，
并在达到请求的 `limit` 后停止，降低大型项目中的内存占用和首批结果等待时间。

需要跨多个 recording 对比时，应优先传入 recording 过滤条件和模板过滤条件；导出
大结果集时保持 CSV 为基础格式，Parquet 仅在本地安装 `pyarrow` 后启用。

## 机器人离线诊断

离线诊断按需计算 `DiagnosticReport`。普通运行不写入数据库；用户显式导出时会把
JSON、CSV 或 HTML 报告写入项目 `exports/`，并在 `diagnostic_exports` 中登记。
诊断报告复用 `query_rows` 和 source metadata，默认不反序列化 ROS/MCAP 消息内容。

默认检查项包括：

| 检查 | 说明 |
| --- | --- |
| `topic_coverage` | 统计 `tf_tree`、`trajectory`、`point_cloud`、`camera_image`、`imu`、`joint_state`、`diagnostics`、`robot_model` 等角色 |
| `convertibility` | 检查 ROS2 DB3 skipped/unconvertible topics |
| `message_volume` | 检查 source 和 topic 的 message_count |
| `time_sync` | 比较 topic 时间范围，统一归一化到秒 |
| `logs_and_states` | 复用 `find_errors` 的日志与状态结果 |
| `battery` | 复用 `low_battery`，默认阈值 `0.2` |
| `cv_detection` | 复用 `detection_failure`，默认置信度阈值 `0.5` |

默认阈值：

| 参数 | 默认值 |
| --- | --- |
| `battery_low` | `0.2` |
| `detection_confidence` | `0.5` |
| `time_sync_warn_s` | `0.1` |
| `time_sync_critical_s` | `1.0` |

评分从 100 开始，critical finding 扣 30 分、warning 扣 10 分、info 扣 2 分，最低 0。
任一 critical 或总分低于 60 为 `critical`；任一 warning 或总分低于 85 为 `warning`；否则为 `ok`。

## 导出

CSV 导出必须可用。Parquet 导出依赖 `pyarrow`，缺失时返回明确错误。
诊断报告导出支持 JSON、CSV 和 HTML；CSV 以 findings 为主表，完整报告使用 JSON。
