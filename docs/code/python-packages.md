# Python 包

## `packages/core`

`datascope_core` 是业务核心。API 和 CLI 不直接实现导入转换逻辑，而是调用 `Workspace`。

关键入口：

- `datascope_core.workspace.Workspace`
- `datascope_core.adapters.registry.adapter_for_path`
- `datascope_core.mapping.suggest_mapping`
- `datascope_core.query.run_query_template`
- `datascope_core.viewer.open_recording`

## `packages/cli`

`datascope_cli` 使用 Typer 实现命令行入口：

```bash
datascope inspect <path>
datascope import <path> --project <name> --template <id> --out <run>
datascope recordings --project <name>
```

## `services/api`

`datascope_api` 使用 FastAPI 暴露本地 HTTP API，桌面端默认连接 `http://127.0.0.1:8000`。
