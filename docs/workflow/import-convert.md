# 导入与转换

## 桌面端流程

1. 创建或选择项目。
2. 点击“选择数据源”，选择文件或文件夹。
3. 点击“导入并自动 Mapping”。
4. 查看 schema profile、字段映射和数据预览。
5. 编辑时间字段/单位、source fields、semantic type 和 entity path。
6. 运行 Mapping 校验；修复 error，按需接受 warning。
7. 确认 Mapping 后构建 recording。
8. 点击“在 Rerun 中打开”。

自动 Mapping 首次保存为 draft。任何编辑都会撤销 confirmed 状态，必须重新
校验和确认。Mapping 模板可以跨项目复用，并可通过 YAML 导入/导出。

## CLI 流程

```bash
datascope inspect /path/to/source
datascope import /path/to/source --project demo --template sensor_monitor --out run_001
datascope recordings --project demo
```

## 支持数据源

| 数据源 | 示例 |
| --- | --- |
| CSV | `/data/run.csv` |
| JSONL | `/data/events.jsonl` |
| 图像目录 | `/data/cv_dataset/images` |
| 点云文件 | `/data/frame_001.ply` |
| 点云目录 | `/data/point_cloud_run` |
| MCAP | `/data/run.mcap` |
| ROS2 SQLite Bag | `/data/run.db3` 或 `/data/rosbag2_run/` |
