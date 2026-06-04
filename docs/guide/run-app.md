# 开发运行

## 启动桌面端

```bash
cd apps/desktop
npm install
npm run tauri:dev
```

`npm run tauri:dev` 会执行 `apps/desktop/scripts/run-desktop.sh`：

- 检查 Node 版本。
- 检查 `http://127.0.0.1:8000/api/health`。
- 如果后端未运行，则用仓库根目录 `.venv` 自动启动 FastAPI。
- 当前端源码有变化时增量构建 Vite 产物。
- 启动 Tauri 桌面窗口。

## 单独启动 API

```bash
. .venv/bin/activate
uvicorn datascope_api.main:app --reload --host 127.0.0.1 --port 8000
```

健康检查：

```bash
curl --noproxy 127.0.0.1 http://127.0.0.1:8000/api/health
```

## CLI

```bash
. .venv/bin/activate
datascope inspect tests/fixtures/sample_sensor.csv
datascope import tests/fixtures/sample_sensor.csv --project demo --template sensor_monitor --out run_001
```

## 本地工作区

默认工作区在：

```text
~/.datascope-studio
```

项目导出的 zip 包默认进入：

```text
~/DataScope Studio Exports
```
