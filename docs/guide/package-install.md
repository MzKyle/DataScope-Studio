# 安装与打包

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

## Tauri 检查与打包

```bash
cd apps/desktop/src-tauri
cargo check
```

正式打包：

```bash
cd apps/desktop
npm run tauri:build
```

打包需要系统已安装 WebKitGTK、GTK 和 Rust 工具链。
