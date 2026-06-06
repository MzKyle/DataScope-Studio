# 数据流

## 导入转换链路

```mermaid
sequenceDiagram
    participant UI as Desktop / CLI
    participant API as FastAPI
    participant WS as Workspace
    participant AD as Adapter
    participant RR as Rerun Writer
    participant DB as SQLite

    UI->>API: create project / add source
    API->>WS: add_source()
    WS->>DB: register source
    UI->>API: inspect source
    API->>WS: inspect_source()
    WS->>AD: inspect + infer_streams
    WS->>DB: save streams
    UI->>API: suggest/save draft mapping
    WS->>DB: cache schema profile + mapping YAML
    UI->>API: validate/confirm mapping
    WS->>DB: mark confirmed
    UI->>API: build recording
    WS->>RR: convert to .rrd
    WS->>DB: index query rows + recording
```

## Workspace 文件流

项目目录包含：

```text
raw/          导入源文件副本
cache/        中间缓存
recordings/   .rrd
blueprints/   .rbl
mappings/     mapping YAML
logs/         运行日志
exports/      查询或项目导出
```

默认 workspace 为 `~/.datascope-studio`。项目 zip 导出默认进入 `~/DataScope Studio Exports`，避免藏在隐藏目录里。
