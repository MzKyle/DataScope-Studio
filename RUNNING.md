# DataScope Studio v0.2.0 运行与安装说明

## 安装版

正式安装包会把桌面端、FastAPI 后端、Python 运行时、DataScope Python 包和 Rerun SDK/CLI 一起打包。用户安装后直接从系统菜单启动 DataScope Studio，不需要手动安装 Python、Node、npm、`.venv`、uvicorn 或 Rerun。

安装版启动时会自动选择一个空闲的 `127.0.0.1:<port>`，由 Tauri 主进程拉起内置后端。应用退出时后端进程会同步退出。后端日志写入系统应用日志目录的 `datascope-api.log`。

本机当前平台构建安装包：

```bash
cd apps/desktop
npm install
npm run runtime:build
npm run tauri:build
```

Linux 只构建 `.deb + .AppImage`：

```bash
cd apps/desktop
npm run package:linux
```

开发机快速验证 runtime 可以使用当前 Python 生成开发用 runtime：

```bash
cd apps/desktop
npm run runtime:build:dev
```

注意：`runtime:build:dev` 只用于开发验证，不作为正式可迁移安装包；正式安装包使用 `runtime:build` 下载独立 CPython runtime。

## 后端和 CLI

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
uvicorn datascope_api.main:app --reload --host 127.0.0.1 --port 8000
```

CLI 示例：

```bash
datascope inspect tests/fixtures/sample_sensor.csv
datascope import tests/fixtures/sample_sensor.csv --project demo --out run_001
datascope open ~/.datascope-studio/projects/<project_id>/recordings/run_001.rrd
```

图片目录导入使用 DataScope CV sidecar 格式。请把 `annotations.json` 和可选的 `predictions.json` 放在图片目录旁边：

```text
dataset/
  images/
    000001.png
    000002.png
  annotations.json
  predictions.json
```

```json
{
  "classes": [{ "id": 1, "label": "person", "color": [255, 80, 80] }],
  "frames": [
    {
      "image": "images/000001.png",
      "time": 0.0,
      "boxes": [{ "bbox": [10, 20, 100, 180], "class_id": 1, "label": "person", "score": 0.92 }],
      "keypoints": [{ "points": [[12, 24], [16, 36]], "class_id": 1, "label": "person" }],
      "masks": [{ "path": "masks/000001.png", "class_id": 1, "label": "person" }]
    }
  ]
}
```

```bash
datascope inspect /path/to/dataset/images
datascope import /path/to/dataset/images --project cv_demo --template cv_detection --out cv_run_001
```

MCAP 导入使用 Rerun 原生转换器：

```bash
datascope inspect /path/to/run.mcap
datascope import /path/to/run.mcap --project robot_demo --template robotics_debug --out robot_run_001
```

3D 点云导入支持单个文件或目录，当前支持 `.ply`、`.pcd`、`.npy`、`.npz`。目录下每个点云文件会作为一帧写入 Rerun `Points3D`：

```bash
datascope inspect /home/kyle/sany/scan_point_cloud
datascope import /home/kyle/sany/scan_point_cloud --project cloud_demo --template robotics_debug --out cloud_run_001
```

桌面端中在“导入数据”输入点云目录路径后点击“检查数据源”，模板会优先推荐 `robotics_debug`。

Run catalog 和本地查询示例：

```bash
datascope recordings --project demo
datascope tag <recording_id> --add failed --add firmware:v1.2
datascope query --project demo --template low_battery --threshold 0.2
datascope query --project demo --template find_errors
datascope query --project cv_demo --template detection_failure --threshold 0.5
datascope query --project robot_demo --template topic_summary
datascope query --project robot_demo --template time_sync
datascope export-query --project demo --template low_battery --threshold 0.2 --format csv
```

v0.2.0 插件、模板、批量导入、Run 对比和项目打包示例：

```bash
datascope plugin validate ./my_plugin
datascope plugin install ./my_plugin
datascope plugin list

datascope template validate ./my_template.yaml
datascope template install ./my_template.yaml
datascope template list

datascope batch import "./runs/*.csv" --project demo --template sensor_monitor --out batch_run
datascope compare <recording_id_1> <recording_id_2> --project demo --metric battery
datascope project export --project demo --out demo.datascope.zip
```

## 桌面端

桌面前端需要 Node `>=20.19.0`。

第一次运行前，请先完成 Python 依赖安装，确保项目根目录存在 `.venv`：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

之后启动开发版桌面端只需要运行：

```bash
cd apps/desktop
npm install
npm run tauri:dev
```

`npm run tauri:dev` 会由 Tauri 主进程使用项目根目录 `.venv` 自动启动 FastAPI 后端，并自动选择空闲端口。开发启动不再依赖固定 `127.0.0.1:8000`。

如果你想手动启动后端并让桌面端复用它，可以设置：

```bash
DATASCOPE_DEV_BACKEND=1 DATASCOPE_API_PORT=8000 npm run tauri:dev
```

`npm run tauri:dev` 会先清理本项目残留的旧 Tauri 进程，再按需增量构建前端静态包，最后直接运行 Tauri。当前启动链路不依赖 `127.0.0.1:1420`。

如果终端默认还是 Node 12，启动脚本会优先使用本机已有的 Node 20：

```bash
/home/kyle/.local/node-v20.20.1-linux-x64/bin
/home/kyle/.local/node-v20.19.5-linux-x64/bin
```

如果这些目录不存在，请先安装 Node `>=20.19.0` 或把它加入 `PATH`。

默认 `npm run tauri:dev` 使用性能优先的图形模式，只保留低成本的 WebKitGTK 兼容设置，交互会更流畅。

如果窗口里仍然显示 `Connection terminated unexpectedly`，通常是旧窗口/旧 WebKit 进程还在，先按 `Ctrl+C` 停掉当前启动命令，然后清理本项目残留进程：

```bash
pkill -f 'target/debug/datascope-studio'
pkill -f 'npm run tauri:dev'
pkill -f 'bash scripts/run-desktop.sh'
pkill -f 'vite --host 127.0.0.1'
pkill -f 'http.server 1420'
```

再重新启动：

```bash
npm run tauri:dev
```

如果清理后仍然崩溃，再使用安全图形模式启动：

```bash
npm run tauri:dev:safe
```

安全图形模式等价于 `DATASCOPE_SAFE_GRAPHICS=1 npm run tauri:dev`，会启用 `WEBKIT_DISABLE_COMPOSITING_MODE=1`、`LIBGL_ALWAYS_SOFTWARE=1`、`GSK_RENDERER=cairo`、`GDK_BACKEND=x11` 等回退设置。它更稳定，但会明显降低界面流畅度；只建议在普通模式仍然崩溃时使用。

如果使用 `DATASCOPE_DEV_BACKEND=1 DATASCOPE_API_PORT=8000` 复用外部后端，可以用下面的命令确认后端健康：

```bash
curl http://127.0.0.1:8000/api/health
```

注意：`/api/health` 只支持普通 GET，请不要用 `curl -I` 检查后端，否则 FastAPI 会返回 `405 Method Not Allowed`。

Linux WebKitGTK 某些 GPU/沙箱组合会导致窗口显示 `Connection terminated unexpectedly`。项目默认只设置 `WEBKIT_DISABLE_DMABUF_RENDERER=1` 和 `NO_AT_BRIDGE=1`；完整软件渲染回退需要使用上面的安全图形模式。

如果仍然不稳定，可以先单独完成 Rust 编译缓存，再启动桌面端：

```bash
cd apps/desktop/src-tauri
cargo build --no-default-features
cd ..
npm run tauri:dev
```

在 Linux 上，Tauri 还需要 WebKit/GTK 原生开发包。Debian/Ubuntu 可以安装：

```bash
sudo apt-get update
sudo apt-get install -y \
  pkg-config \
  build-essential \
  libgtk-3-dev \
  libwebkit2gtk-4.1-dev \
  libjavascriptcoregtk-4.1-dev \
  libsoup-3.0-dev \
  libayatana-appindicator3-dev \
  librsvg2-dev \
  libxdo-dev \
  libssl-dev
```

安装后可以确认这些 Tauri 编译依赖已经被 `pkg-config` 找到：

```bash
pkg-config --exists gdk-3.0 && echo "gdk-3.0 OK"
pkg-config --exists javascriptcoregtk-4.1 && echo "javascriptcoregtk-4.1 OK"
pkg-config --exists libsoup-3.0 && echo "libsoup-3.0 OK"
```

## 测试

```bash
. .venv/bin/activate
pytest
```
