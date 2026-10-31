# CLI 命令

CLI 入口是 `datascope`。

## 数据导入

```bash
datascope inspect <path> [--json]
datascope import <path> --project <name> --template <id> --out <name> [--output-dir <目录>] [--json]
datascope open <recording.rrd> [--blueprint <file.rbl>]
```

导入时可用 `--output-dir <目录>` 将 `.rrd` 与 `.rbl` 一起写入指定目录；省略时
保持项目内 `recordings/` 与 `blueprints/` 的默认结构。

## Catalog

```bash
datascope recordings --project <name-or-id> [--json]
datascope tag <recording_id> --add failed --add firmware:v1.2
```

## Mapping

```bash
datascope mapping validate <mapping_id>
datascope mapping confirm <mapping_id>
datascope mapping diff --project demo --template robot_sensor --left <source_id> --right <source_id>

datascope mapping template list
datascope mapping template create --name "Robot Sensor" --source <source_id> --mapping <mapping_id>
datascope mapping template import ./robot-sensor.yaml
datascope mapping template export robot_sensor --out ./exports/
```

## 查询与对比

```bash
datascope query --project demo --template low_battery --threshold 0.2
datascope export-query --project demo --template find_errors --format csv --out errors.csv
datascope diagnose --project demo --preset strict --format html --out ./exports/diagnostics.html
datascope compare <recording_id...> --project demo --metric battery
```

## 插件、模板、批量和项目包

```bash
datascope plugin list
datascope plugin validate <plugin_dir>
datascope plugin install <plugin_dir>

datascope template list
datascope template validate <template.yaml>
datascope template install <template.yaml>

datascope batch import "<glob>" --project demo --template sensor_monitor

datascope project export --project demo --out ~/DataScopeExports
datascope project import ~/DataScopeExports/demo.zip
```

CSV 优化路径可显式选择：

```bash
datascope import telemetry.csv --project demo --query-storage auto
datascope batch import "data/*.csv" --project demo --query-storage auto
```

`--query-storage` 支持 `auto`、`legacy` 和 `typed_sqlite`。完整性能与跨平台门槛通过前，
默认仍为 `legacy`；使用 `legacy` 可为新构建选择兼容布局，已有 Recording 仍按其实际布局读取。
