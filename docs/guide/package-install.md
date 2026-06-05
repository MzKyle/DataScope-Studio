# 安装与打包

## 用户安装包

DataScope Studio 的正式安装包内置：

- Tauri 桌面端
- FastAPI 后端
- 独立 Python runtime
- `datascope-core`、`datascope-api`、`datascope-cli`
- Rerun SDK/CLI

用户安装后可以直接打开应用，不需要提前安装 Python、Node、npm、Rerun 或项目 `.venv`。桌面进程会自动选择空闲 localhost 端口并启动后端。

| 平台 | 产物 |
| --- | --- |
| Linux | `.deb`、`.AppImage` |
| Windows | `.msi` |
| macOS | `.dmg` |

## 本地构建安装包

```bash
cd apps/desktop
npm install
npm run runtime:build
npm run tauri:build
```

`tauri:build` 会按当前系统选择安装包格式：Linux 为 `.deb/.AppImage`，Windows 为 `.msi`，macOS 为 `.dmg`，不会构建无关平台格式。

按平台构建：

```bash
npm run package:linux
npm run package:windows
npm run package:macos
```

`runtime:build` 会从 `astral-sh/python-build-standalone` 下载当前平台的独立 CPython，安装 DataScope 和 Rerun 依赖，并在 `apps/desktop/src-tauri/resources/datascope-runtime/` 生成：

- `python/`
- `runtime-manifest.json`
- `THIRD_PARTY_NOTICES.md`

这些生成产物不会提交到 Git。

## 开发用 runtime

如果只是想快速验证 Tauri bundle 资源路径，可以使用当前 Python 生成开发用 runtime：

```bash
cd apps/desktop
npm run runtime:build:dev
```

开发用 runtime 不保证跨机器迁移；正式安装包必须使用 `runtime:build`。

## Python 包

开发时推荐 editable install：

```bash
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

单独安装某个包：

```bash
python -m pip install -e packages/core
python -m pip install -e packages/cli
python -m pip install -e services/api
```

## 桌面构建

```bash
cd apps/desktop
npm install
npm run build
```

## Tauri 检查

```bash
cd apps/desktop/src-tauri
cargo check
```

Linux 打包需要系统已安装 WebKitGTK、GTK 和 Rust 工具链。CI 会自动安装这些依赖。
