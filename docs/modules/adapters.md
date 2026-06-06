# 数据适配器

Adapter 是 DataScope Core 对不同数据源的统一抽象。公开协议包含：

```python
inspect(path) -> SourceInfo
infer_streams(source) -> list[StreamInfo]
preview(source, stream_id, limit=100) -> dict
convert(request) -> None
```

Workspace 会为所有 adapter 生成统一 schema profile。CSV/JSONL 提供字段类型、
空值比例、每列时间解析/单调性和推断单位；图像、点云、MCAP 使用 adapter
metadata 和语义流提供等价检查信息。第三方 adapter 无专用校验钩子时使用通用规则。

## 内置适配器

| Adapter | 数据源 | 主要输出 |
| --- | --- | --- |
| CSV | `.csv` | scalar、scalar_group、state、text_log、2D/3D 几何 |
| JSONL | `.jsonl` / `.ndjson` | 展平字段后的 scalar/state/log/几何 |
| Image Folder | 图片目录 + `annotations.json` / `predictions.json` | image、boxes2d、scores、keypoints、masks |
| Point Cloud | `.ply` / `.pcd` / `.npy` / `.npz` 文件或目录 | point_cloud |
| MCAP | `.mcap` | topic metadata、robot/TF/URDF 元数据 |

## Source Type 识别

`detect_source_type()` 支持文件后缀和目录扫描：

- 图片目录识别为 `image_folder`。
- 点云目录识别为 `point_cloud`。
- 不含支持文件的目录会返回明确错误。

## 时间列

时间字段优先识别 `timestamp`、`time`、`t`、`datetime`。数值时间会通过统一归一化工具识别相对秒、Unix 秒、毫秒、微秒和纳秒，避免大整数写入 Rerun 时溢出。

Mapping v2 校验后固定 effective unit。无效时间行保留 `row` sequence，但不会
继承上一条主时间线，也不会在查询索引中回退为行号。
