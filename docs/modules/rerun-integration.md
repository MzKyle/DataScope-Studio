# Rerun 集成

DataScope Studio 通过 Rerun Python SDK 写入 recording，通过外部 `rerun` CLI 打开 viewer。

## 输出文件

| 文件 | 说明 |
| --- | --- |
| `.rrd` | Rerun recording，包含时间序列、图像、点云、状态等数据 |
| `.rbl` | Rerun blueprint，包含默认视图布局 |

## Entity Path 约定

| 场景 | 示例路径 |
| --- | --- |
| 传感器标量 | `/metrics`、`/sensors` |
| 状态 | `/states` |
| 日志 | `/logs` |
| 图像 | `/camera/image` |
| 检测框 | `/camera/gt/boxes`、`/camera/pred/boxes` |
| 点云 | `/sensors/lidar/points` |

## Viewer 打开

桌面端、API 和 CLI 都调用同一个 viewer 工具函数。如果系统没有安装 `rerun` CLI，转换仍可完成，但打开 viewer 会返回明确错误。
