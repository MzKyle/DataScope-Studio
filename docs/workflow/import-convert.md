# 导入与转换

## 桌面端流程

1. 创建或选择项目。
2. 点击“选择数据源”，选择文件或文件夹。
3. 点击“检查数据源”。
4. 查看 streams、preview 和模板建议。
5. 保存 mapping。
6. 构建 recording。
7. 点击“在 Rerun 中打开”。

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
