# DataScope Studio — 详细操作说明（中文）

本文档面向开发者和使用者，涵盖环境准备、后端/CLI、桌面前端启动、前端交互说明，以及一键可视化多元数据的详细步骤与常见故障排查。

**重要前置条件**
- 操作系统：Linux（说明中有一些针对 Debian/Ubuntu 的包）。
- Python 3.10+（建议使用系统 `python3`）。
- Node.js >= 20.19.0（桌面端开发/运行需要）。
- Rust / Cargo（仅在构建 Tauri 原生部分或预先缓存编译时需要）。

## 1. 本地准备（一次性）
- 在项目根目录运行：
```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```
- 如果要运行桌面端，确保 Node 版本满足要求；项目脚本会自动在 `$HOME/.local` 或 `$HOME/.nvm` 下查找 Node 20.19/20.20，亦可自行安装并加入 `PATH`。
- Linux 上若要构建 Tauri，需要安装系统依赖（Debian/Ubuntu 示例）：
```bash
sudo apt-get update
sudo apt-get install -y pkg-config build-essential libgtk-3-dev libwebkit2gtk-4.1-dev libjavascriptcoregtk-4.1-dev libsoup-3.0-dev libayatana-appindicator3-dev librsvg2-dev libxdo-dev libssl-dev
```

## 2. 启动后端（开发模式）
- 激活虚拟环境并启动 FastAPI（开发模式）：
```bash
. .venv/bin/activate
uvicorn datascope_api.main:app --reload --host 127.0.0.1 --port 8000
```
- 健康检查：
```bash
curl --noproxy 127.0.0.1 http://127.0.0.1:8000/api/health
# 或 在当前会话临时移除代理
unset http_proxy https_proxy
curl http://127.0.0.1:8000/api/health
```
- 常见问题：若你的环境中设置了 `http_proxy`/`https_proxy`，本地请求可能被代理导致 `502`，请使用 `--noproxy 127.0.0.1` 或 `unset` 来绕过本机代理（仓库已对桌面脚本做相应修补）。

## 3. CLI（`datascope`）示例
- 检查文件/运行：
```bash
datascope inspect tests/fixtures/sample_sensor.csv
datascope import tests/fixtures/sample_sensor.csv --project demo --out run_001
datascope open ~/.datascope-studio/projects/<project_id>/recordings/run_001.rrd
```
- 批量、导出与查询示例见仓库 `RUNNING.md`（已包含常用命令）。

## 4. 启动桌面端（开发）
- 在项目根先确保 `.venv` 已创建并安装依赖（见第1步）。
- 然后进入桌面目录：
```bash
cd apps/desktop
npm install
npm run tauri:dev
```
- `npm run tauri:dev` 流程说明：
  - 脚本会先检查 `http://127.0.0.1:8000/api/health`，如果未运行会尝试使用项目根的 `.venv` 自动启动后端；若代理阻塞健康检查会导致失败（可参考上面代理绕过方案）。
  - 脚本会清理项目内残留的旧 Tauri/Vite/静态服务进程，然后构建前端并运行 Tauri。
  - 默认使用性能优先图形模式；如果 WebKit 仍然崩溃，可以改用 `npm run tauri:dev:safe`。
- 如果遇到 `Connection terminated unexpectedly`，请清理残留进程后重试：
```bash
pkill -f 'target/debug/datascope-studio' || true
pkill -f 'npm run tauri:dev' || true
pkill -f 'bash scripts/run-desktop.sh' || true
pkill -f 'vite --host 127.0.0.1' || true
pkill -f 'http.server 1420' || true
```
如果清理后仍然出现 `Connection terminated unexpectedly`：
```bash
npm run tauri:dev:safe
```

## 5. 前端（桌面）交互详解

主导航为快速查看、项目、设置，默认进入快速查看。产品边界以根目录《产品设计.md》为准。

1. 在快速查看选择或拖入数据；无需先创建项目。
2. 查看自动预览和 Mapping 就绪状态；仅在需要时展开高级映射修复。
3. 生成可视化并在 Rerun 打开。桌面快速查看跳过查询索引。
4. 需要保存时选择“转入项目”：保留当前 Mapping，重新导入并校验，在项目内重新生成记录。
5. 项目工具提供导入、批量导入、任务和项目包；记录详情提供概览、检查、筛选。
6. 自定义查询、对比和插件等在对应高级区域；设置管理预设与插件，不单独展示 Recipe。

规则检查得分只反映现有规则输出；未命中不代表全面健康。Topic 时间范围差异不等于逐消息同步验证。

## 6. 一键可视化多元数据（使用场景与具体步骤）
“多元数据” 指同一次运行中包含多种时序/异构流，例如：电池电压、温度、IMU、相机帧、检测框等。以下示例展示如何从一份 CSV（或 Image+annotations）做到“一键可视化”：

示例 A：CSV（时序多传感器）
1. 准备 CSV，示例列：`timestamp,entity_id,voltage,temperature,x,y,z`。时间列（ISO 或浮点秒）应命名或在 mapping 中选择为时间列。
2. 在桌面应用选择项目，输入 CSV 路径（或拖拽文件）。
3. 点击 `Inspect`，等待流信息和预览加载。
4. 在模板建议中选 `sensor_monitor` 或合适模板；应用会自动建议 mapping（把 `timestamp` 对应为时间，把 `entity_id` 做为实体标识，把 `x,y,z` 识别为坐标流）。
5. 校验预览数据，若识别错误可在映射界面修改字段映射（例如把 `voltage` 标记为标量流，`temperature` 标量流）。
6. 点击 `Save mapping`，再点击 `Build recording`，等待构建完成。
7. 构建完成后点击 `Open in Rerun`：Rerun viewer 会直接打开并显示多路流的可视化层：
   - 时间轴上可播放/跳转；
   - 左侧/上方选择可见的流（电压、温度、IMU、图像等）；
   - 标量流可切换为图表展示（时序曲线）；
   - 相机/检测框会以图像图层渲染，支持缩放与图层开关。

“**一键**”的含义：在界面中完成 `Inspect` → `Save mapping` → `Build recording` → `Open` 这条流水线后，Rerun 会自动加载对应流并渲染，达到即时可视化多元数据的效果。

示例 B：图像数据（带 annotations.json）
- 按照 DataScope CV sidecar 格式组织文件（`images/`, `annotations.json`, 可选 `predictions.json`）。
- 在导入时选择数据集根目录，项目会把图像、bounding boxes、masks、keypoints 转为可视化流，构建后在 Viewer 中即刻可见。

## 7. 进阶：批量导入与对比
- 批量导入：在 `Batch import` 输入文件路径 glob（例如 `./runs/*.csv`），指定模板与输出前缀，执行后系统会分条构建 recording。
- 对比：在 `Compare` 面板选择两个或多个 recording id 并指定 metric（例如 `battery`），运行后界面会返回对比摘要和各项数值，支持导出。

## 8. 故障排查与提示
- 后端健康检查失败：优先检查是否有本地代理影响（`http_proxy`），使用 `--noproxy 127.0.0.1` 或 `unset http_proxy https_proxy`。
- Node 版本错误：脚本会提示 `Node >=20.19.0 is required`，请安装合适版本或把已安装 Node 加入 PATH。
- Tauri 编译错误：确认系统依赖（WebKitGTK/GTK）已安装并能被 `pkg-config` 找到。
- 界面显示 `Connection terminated unexpectedly`：通常是旧 WebKit 进程残留，执行前述 `pkill -f` 清理并重试；仍然崩溃时使用 `npm run tauri:dev:safe`，但安全模式会牺牲交互流畅度。

## 9. 常见命令速查
- 启动后端（开发）：
```bash
. .venv/bin/activate
uvicorn datascope_api.main:app --reload --host 127.0.0.1 --port 8000
```
- 启动桌面端（开发）：
```bash
cd apps/desktop
npm install
npm run tauri:dev
```
- 检查健康：
```bash
curl --noproxy 127.0.0.1 http://127.0.0.1:8000/api/health
```
- 导入 CSV 并构建（CLI）：
```bash
datascope import /path/to/data.csv --project demo --template sensor_monitor --out run_001
datascope open ~/.datascope-studio/projects/<project_id>/recordings/run_001.rrd
```

---

更多开发、架构、API、CLI 和故障排查说明见 docsify 文档站：

```bash
cd docs
python3 -m http.server 4173
```

然后访问 `http://127.0.0.1:4173/`。
