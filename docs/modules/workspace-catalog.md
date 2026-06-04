# Workspace 与 Catalog

`Workspace` 是 core 的主入口，负责项目目录、SQLite catalog、数据导入、mapping 保存、recording 构建、查询和项目包。

## 默认位置

```text
~/.datascope-studio
```

每个项目拥有独立目录：

```text
projects/<project_id>/
  raw/
  cache/
  recordings/
  blueprints/
  mappings/
  logs/
  exports/
```

## 核心方法

| 方法 | 说明 |
| --- | --- |
| `create_project()` | 创建项目和目录 |
| `add_source()` | 复制文件或目录到 `raw/` 并登记 source |
| `inspect_source()` | 调 adapter 推断 streams |
| `suggest_mapping()` | 根据 streams 和模板生成 MappingSpec |
| `save_mapping()` | 保存 mapping YAML |
| `build_recording()` | 生成 `.rrd`、`.rbl` 并登记 recording |
| `run_query()` | 执行本地查询模板 |
| `export_project()` | 打包项目 zip |
| `import_project_package()` | 导入已打包项目 |

## Catalog 设计

Catalog 优先使用 SQLite，目标是轻量、可离线、易备份。后续如果引入远程 catalog，也应保持本地 workspace 可独立运行。
