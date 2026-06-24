# 模块全景

## Monorepo 模块

| 路径 | 模块 | 说明 |
| --- | --- | --- |
| `apps/desktop` | Desktop | Tauri + React 桌面端 |
| `services/api` | API | FastAPI 服务，暴露项目、导入、查询、导出接口 |
| `packages/core` | Core | Python 核心库，包含 adapters、workspace、mapping、query、Rerun 写入 |
| `packages/cli` | CLI | Typer 命令行工具 |
| `tests` | Tests | 单元测试、集成测试和 fixtures |
| `docs` | Docs | docsify 文档站 |

## Python 包布局

Python 包使用 `src/` layout：

```text
packages/core/src/datascope_core/
packages/cli/src/datascope_cli/
services/api/src/datascope_api/
```

公开 import 名保持稳定：

```python
from datascope_core.workspace import Workspace
from datascope_api.main import app
from datascope_cli.main import app as cli_app
```

## Core 内部模块

| 模块 | 职责 |
| --- | --- |
| `adapters/` | 识别和读取不同数据源 |
| `models.py` | SourceInfo、StreamInfo、MappingSpec 等共享模型 |
| `mapping.py` | 自动 mapping 建议和 YAML 读写 |
| `templates.py` | 内置模板匹配和 blueprint 保存 |
| `rerun_writer.py` | CSV/JSONL/文本表格等 tabular 数据写入 Rerun |
| `query.py` | 本地 query index、查询模板和导出 |
| `workspace.py` | SQLite catalog、项目目录和端到端流程 |
| `plugin_registry.py` | 本地插件 manifest 校验与注册 |
| `template_registry.py` | 本地模板安装与启用管理 |
