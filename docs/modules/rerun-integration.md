# Rerun 集成

DataScope Studio 通过 Rerun Python SDK 写入 recording，通过外部 `rerun` CLI 打开 viewer。

## 输出文件

| 文件 | 说明 |
| --- | --- |
| `.rrd` | Rerun recording，包含时间序列、图像、点云、状态等数据 |
| `.rbl` | Rerun blueprint，包含默认视图布局 |

构建任务只有在 `.rrd` 和 `.rbl` 都已写入且文件非空时才算成功。成功结果会返回
`artifact_info`，并在 recording 的 `params.rerun_artifact` 中保存同一份元数据：

- `recording_size_bytes` / `blueprint_size_bytes`
- `app_id`、`template_id`、`rerun_recording_id`
- `source_type`、`converter`、`rerun_version`
- `mcap_decoders`、`rrd_optimize_profile`、`artifact_validation`
- `artifact_checks`、`catalog_registration`

`converter` 用于区分当前 Rerun 链路：表格、图像和点云使用
`rerun_python_sdk`，MCAP 使用 `rerun_mcap_cli`，ROS2 DB3 使用
`ros2_db3_to_mcap_to_rerun_cli`。

默认构建保持兼容：MCAP importer 不显式选择 decoder，`.rrd` 不做 optimize，
artifact 只做存在与非空校验。用户启用高级选项后，可以指定 MCAP decoder、
运行 `rerun rrd optimize --profile live|object-store`、执行 `verify`/`strict`
校验，或把 `.rrd` 注册到会话内托管的本地 Rerun Catalog。
桌面/API 的 managed local 模式会按会话启动 `rerun server`；CLI 不保留后台
server，启用 `--catalog-dataset` 时必须同时传 `--catalog-url`。

Recording 列表还会基于当前文件路径动态返回 `artifact_status`，用于提示 artifact
是否就绪、缺失或为空。

## Entity Path 约定

| 场景 | 示例路径 |
| --- | --- |
| 传感器标量 | `/metrics`、`/sensors` |
| 状态 | `/states` |
| 日志 | `/logs` |
| 图像 | `/camera/image` |
| 检测框 | `/camera/gt/boxes`、`/camera/pred/boxes` |
| 点云 | `/sensors/lidar/points` |

CV prediction score 会继续写入兼容路径 `/camera/pred/scores`，同时写入稳定的
`/camera/pred/scores/min` 和 `/camera/pred/scores/mean`。点云写入支持显式
RGB：`.xyzrgb` 文本点云、PLY/PCD 中的 `r/g/b` 或 `red/green/blue` 字段。
PCD packed `rgb` 浮点编码暂不解析。

## Viewer 打开

桌面端、API 和 CLI 都调用同一个 viewer 工具函数。打开前会检查 recording 路径和
blueprint 路径是否存在；缺失时返回 `viewer_recording_missing` 或
`viewer_blueprint_missing`。如果系统没有安装 `rerun` CLI，转换仍可完成，但打开
viewer 会返回明确错误。
