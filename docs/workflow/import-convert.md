# 导入与转换

## 桌面端流程

1. 在“快速查看”选择或拖入本地数据，无需项目。
2. 查看自动预览、字段映射及 Ready / Review / Blocked 状态。
3. 必要时展开高级 Mapping，修复时间、单位、字段或实体路径并重新校验。
4. 生成可视化，然后在 Rerun 打开。桌面快速查看不建立查询索引。
5. 选择“转入项目”以保留当前映射：选择或创建项目，重新导入原数据并校验，之后在项目内重新生成记录。

项目导入、批量导入和 CLI 继续建立查询索引。转入项目不搬迁临时 RRD/RBL；失败保留临时会话，后续重试复用已经导入的目标数据源。

无表头 CSV 的列名在导入前配置；Mapping 仅引用源字段。高级构建选项保留输出目录、校验、decoder、优化和 Catalog 配置。构建结果包含 artifact_info；正式项目记录还包含 query_index。任何映射编辑都撤销确认状态。


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
