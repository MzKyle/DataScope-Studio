# 环境依赖

## 基础环境

| 依赖 | 建议版本 | 用途 |
| --- | --- | --- |
| Python | 3.10+ | core、API、CLI、测试 |
| Node.js | 20.19+ | Vite / React / Tauri CLI |
| Rust / Cargo | stable | Tauri 原生壳构建 |
| Rerun CLI | 可选 | 打开 `.rrd` recording |

## Linux Tauri 依赖

Debian / Ubuntu 示例：

```bash
sudo apt-get update
sudo apt-get install -y \
  pkg-config build-essential \
  libgtk-3-dev libwebkit2gtk-4.1-dev libjavascriptcoregtk-4.1-dev \
  libsoup-3.0-dev libayatana-appindicator3-dev librsvg2-dev \
  libxdo-dev libssl-dev
```

## Python 开发依赖

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

`requirements-dev.txt` 使用 editable install，把 `packages/core`、`packages/cli` 和 `services/api` 直接安装到当前虚拟环境。

## Node 版本

桌面脚本会优先使用当前 `PATH` 中的 Node。如果版本不足，会尝试查找：

- `$HOME/.local/node-v20.20.1-linux-x64/bin`
- `$HOME/.local/node-v20.19.5-linux-x64/bin`
- `$HOME/.nvm/versions/node/v20.20.1/bin`
- `$HOME/.nvm/versions/node/v20.19.5/bin`
