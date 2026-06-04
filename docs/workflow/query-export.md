# 查询与导出

## 查询请求模型

```json
{
  "template_id": "low_battery",
  "recording_ids": ["recording_x"],
  "params": {"threshold": 0.2},
  "limit": 1000
}
```

## 查询响应模型

```json
{
  "columns": ["recording_id", "time", "entity_path", "key", "value"],
  "rows": []
}
```

## CLI 示例

```bash
datascope query --project demo --template low_battery --threshold 0.2
datascope export-query --project demo --template find_errors --format csv --out errors.csv
```

CSV 导出始终支持。Parquet 需要安装 `pyarrow`。
