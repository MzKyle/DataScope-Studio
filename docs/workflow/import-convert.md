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

对于没有表头的 CSV，在导入前把“CSV 表头”设为“无表头”，并按原始列顺序填写
列名。Mapping 编辑器中的 `source_fields` 只引用已经存在的源字段，不会重命名
CSV 列。

转换任务中的“Rerun 产物目录”用于指定 `.rrd` 与 `.rbl` 的共同输出目录。留空时
保持默认项目结构：`recordings/<name>.rrd` 与 `blueprints/<name>.rbl`。

自动 Mapping 首次保存为 draft。任何编辑都会撤销 confirmed 状态，必须重新
校验和确认。Mapping 模板可以跨项目复用，并可通过 YAML 导入/导出。

## CLI 流程

```bash
datascope inspect /path/to/source
datascope import /path/to/source --project demo --template sensor_monitor --out run_001 \
  --output-dir ~/DataScopeArtifacts
datascope recordings --project demo
```

## 支持数据源

| 数据源 | 示例 |
| --- | --- |
| CSV | `/data/run.csv` |
| TSV / 文本表格 | `/data/run.tsv`、`/data/run.txt` |
| 文本日志 | `/data/run.log` |
| JSONL | `/data/events.jsonl` |
| 图像文件 | `/data/frame_001.tif` |
| 图像目录 | `/data/cv_dataset/images` |
| 点云文件 | `/data/frame_001.ply` |
| 文本点云文件 | `/data/frame_001.xyz`、`/data/frame_001.pts` |
| 点云目录 | `/data/point_cloud_run` |
| MCAP | `/data/run.mcap` |
| ROS2 SQLite Bag | `/data/run.db3` 或 `/data/rosbag2_run/` |
