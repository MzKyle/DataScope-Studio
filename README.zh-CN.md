# DataScope Studio

[English](README.md) | [简体中文](README.zh-CN.md)

![DataScope Studio](docs/assets/cover.png)

DataScope Studio 用于把机器人、工业设备和传感器数据转换成可交互的
[Rerun](https://rerun.io/) 可视化。选择本地数据，检查自动生成的 Mapping，构建
Recording，然后直接在 Rerun 中查看，无需为每种数据编写单独的可视化脚本。

[下载 DataScope Studio](https://github.com/MzKyle/DataScope-Studio/releases) |
[阅读完整文档](docs/README.md)

## DataScope 能做什么

- 用统一、可重复的流程检查不同类型的数据。
- 自动识别时间戳、标量、状态、日志、图像、检测结果和点云。
- 生成可复用的 Rerun `.rrd` Recording 和 `.rbl` Blueprint。
- 在本地管理项目、Recording、任务、标签、参数和查询导出。
- 查询错误日志、低电量、检测失败和状态持续时间等常见问题。
- 导出完整项目包，并在其他机器上重新打开。

## 支持的数据

| 数据源 | 示例 |
| --- | --- |
| 表格与日志 | CSV、JSONL |
| 计算机视觉 | 图像目录和检测标注 sidecar |
| 点云 | PLY、PCD、NPY、NPZ 文件或帧目录 |
| 机器人 Recording | MCAP 元数据和转换流程 |

DataScope 采用本地优先设计。源数据、Mapping、Recording 和 SQLite 目录默认保留
在本机工作区中，只有主动导出项目包时才会复制数据。

## 快速安装

从 [GitHub Releases](https://github.com/MzKyle/DataScope-Studio/releases) 下载对应安装包：

| 系统 | 安装包 |
| --- | --- |
| Windows 10/11 x64 | `DataScope-Studio-v0.2.0-windows-x86_64-setup.exe` |
| macOS Apple Silicon | `DataScope-Studio-v0.2.0-macos-aarch64.dmg` |
| macOS Intel | `DataScope-Studio-v0.2.0-macos-x86_64.dmg` |
| Debian/Ubuntu x64 | `DataScope-Studio-v0.2.0-linux-amd64.deb` |
| 其他 Linux x64 | `DataScope-Studio-v0.2.0-linux-x86_64.AppImage` |

安装包已经包含桌面应用、本地 API、Python 运行时和 Rerun，不需要另外安装
Python、Node.js、npm 或 Rerun。

`v0.2.0` 是未签名的预发布版本：

- **Windows：** 如果出现 SmartScreen，确认文件来自本仓库后，点击“更多信息”与
  “仍要运行”。
- **macOS：** 将 DataScope Studio 拖入“应用程序”。首次启动时按住 Control
  点击应用并选择“打开”；也可以在“系统设置 > 隐私与安全性”中允许打开。
- **Linux AppImage：** 首次启动前添加执行权限：

```bash
chmod +x DataScope-Studio-v0.2.0-linux-x86_64.AppImage
./DataScope-Studio-v0.2.0-linux-x86_64.AppImage
```

Debian 安装包使用：

```bash
sudo apt install ./DataScope-Studio-v0.2.0-linux-amd64.deb
```

## 完成第一次可视化

1. 打开 DataScope Studio，创建或选择项目。
2. 选择 CSV、JSONL、图像目录、点云或 MCAP 数据源。
3. 点击“导入并自动 Mapping”。
4. 检查识别出的数据流和预览，必要时修正时间字段或语义 Mapping。
5. 点击“校验 Mapping”，然后点击“确认 Mapping”。
6. 点击“生成 `.rrd + .rbl`”。
7. 点击“在 Rerun 中打开”查看结果。

项目默认保存在 `~/.datascope-studio`。过去导出的项目包可以通过仪表盘中的
“打开项目包”重新载入。

## 文档

- [安装与打包](docs/guide/package-install.md)
- [导入与转换流程](docs/workflow/import-convert.md)
- [故障排查](docs/faq/troubleshooting.md)
- [开发环境与启动](docs/guide/run-app.md)
- [架构与 API 文档](docs/architecture/README.md)

## 许可证

DataScope Studio 使用 [Apache License 2.0](LICENSE)。
