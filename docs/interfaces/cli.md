# CLI 命令

CLI 入口是 `datascope`。

## 数据导入

```bash
datascope inspect <path> [--json]
datascope import <path> --project <name> --template <id> --out <name> [--json]
datascope open <recording.rrd> [--blueprint <file.rbl>]
```

## Catalog

```bash
datascope recordings --project <name-or-id> [--json]
datascope tag <recording_id> --add failed --add firmware:v1.2
```

## 查询与对比

```bash
datascope query --project demo --template low_battery --threshold 0.2
datascope export-query --project demo --template find_errors --format csv --out errors.csv
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
