# DataScope Studio

![DataScope Studio](assets/cover.png)

DataScope Studio 面向机器人与传感器工程师，把本地离线数据变成可回放、可检查、可复用的 Rerun 记录。默认从快速查看开始，按需进入项目。产品边界和各类数据的接入/预览/回放/查询/检查范围以[产品设计](../产品设计.md)为准。

[下载桌面安装包](https://github.com/MzKyle/DataScope-Studio/releases)

## 适用场景

- 工业设备、机器人、传感器数据的本地检查与归档。
- 多源数据导入后快速生成 Rerun 可视化。
- 在本地对 run、tag、参数、查询结果做轻量 catalog 管理。
- 通过 CLI/API/桌面端复用同一套 import -> mapping -> convert 工作流。

## 当前能力

| 能力 | 说明 |
| --- | --- |
| 数据源 | CSV、TSV/TXT/LOG、JSONL、图片文件/目录、点云文件/目录、MCAP、ROS2 DB3 bag |
| 映射 | 自动识别时间列、标量、状态、日志、图像、检测框、点云 |
| 输出 | Rerun `.rrd` 与 `.rbl` |
| Catalog | projects、sources、streams、mappings、recordings、jobs、query exports |
| 查询 | 低电量、错误日志、低置信度或无检测结果样本、topic summary、状态持续时间、Topic 时间范围差异 |
| 扩展 | 本地插件、模板 registry、批量导入、项目包导出/导入 |

## 快速导航

- [安装与打包](guide/package-install.md)
- [导入与转换](workflow/import-convert.md)
- [故障排查](faq/troubleshooting.md)
- [环境依赖](guide/prerequisites.md)
- [开发运行](guide/run-app.md)
- [3 分钟新用户测试](usability/new-user-3min-test.md)
- [架构总览](architecture/README.md)
- [HTTP API](interfaces/api.md)
- [CLI 命令](interfaces/cli.md)
