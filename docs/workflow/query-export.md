# 查询与导出

记录详情的“筛选”默认只处理当前记录；自定义查询在高级面板。多记录对比和项目级检查需从项目工具显式选择。规则检查得分仅反映现有规则命中；Topic 时间范围检查不等于逐消息同步。

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
