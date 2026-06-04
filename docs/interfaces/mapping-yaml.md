# Mapping YAML

Mapping YAML 连接 source streams 与 Rerun entity path / archetype。

## 结构

```yaml
mapping:
  id: mapping_source_001
  source: source_001
  app_id: datascope.sensor_monitor.v1
  recording_id: run_001
  timelines:
    primary: timestamp
  streams:
    - stream_id: battery
      entity_path: /metrics/battery
      archetype: scalar
      fields:
        - battery
      time_key: timestamp
```

## 常见 archetype

| Archetype | 用途 |
| --- | --- |
| `scalar` | 单个数值 |
| `scalar_group` | 多列数值组 |
| `state` | 离散状态 |
| `text_log` | 文本日志 |
| `image` | 图像 |
| `boxes2d` | 2D 检测框 |
| `point_cloud` | 3D 点云 |

## 模板

模板会影响默认 app id、entity path 和 blueprint：

- `sensor_monitor`
- `cv_detection`
- `robotics_debug`
- `experiment_compare`
