# DataScope Studio V1.0 运行说明

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

V1.0 插件、模板、批量导入、Run 对比和项目打包示例：

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

之后启动桌面端只需要运行：

```bash
cd apps/desktop
npm install
npm run tauri:dev
```

`npm run tauri:dev` 会自动检查 `http://127.0.0.1:8000/api/health`。如果后端没有运行，它会使用项目根目录的 `.venv` 自动启动 FastAPI 后端；如果后端已经运行，则复用现有后端。

`npm run tauri:dev` 还会先执行 `npm run dev:tauri`：清理本项目残留的旧 Tauri/Vite 进程，构建前端，并用 `vite preview` 在 `127.0.0.1:1420` 提供静态页面。这样可以避开 Vite HMR websocket 在 Linux WebKit/Tauri 中偶发的 `Connection terminated unexpectedly`。

如果启动时报 `Port 1420 is already in use`，说明已经有一个旧的 Vite/Tauri 前端进程占用了端口。可以先查看占用进程：

```bash
ss -ltnp | grep ':1420'
```

然后结束对应的 `node ... vite` 进程，再重新运行：

```bash
kill <pid>
npm run tauri:dev
```

如果终端或窗口里偶发出现 `Connection terminated unexpectedly`，先确认服务是否仍在：

```bash
curl http://127.0.0.1:8000/api/health
curl -I http://127.0.0.1:1420/
```

注意：`/api/health` 只支持普通 GET，请不要用 `curl -I` 检查后端，否则 FastAPI 会返回 `405 Method Not Allowed`。如果 `1420` 返回 `502 Bad Gateway` 或连接被拒绝，通常表示 `npm run tauri:dev` 已经退出、Vite 正在重启，或者第一次 Rust 编译还没有完成。

如果两个命令都正常，通常只是 Tauri dev/WebView 热更新连接在重载时断开了一次，可以继续使用。如果窗口已经关闭、页面空白，或者 `1420` 不再监听，按 `Ctrl+C` 停掉当前 `npm run tauri:dev`，然后重新运行：

```bash
npm run tauri:dev
```

如果之前留下了孤立的旧窗口进程，可以先清理：

```bash
pkill -f 'target/debug/datascope-studio'
pkill -f 'vite --host 127.0.0.1'
pkill -f 'vite preview --host 127.0.0.1 --port 1420'
```

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
