# DataScope Studio 测试验收方法

本文档定义 DataScope Studio 前端与后端的测试验收标准。默认每次功能验收先执行 PR 快速门；发布前再执行 Release 严格门和安装包冒烟。

## 1. 验收分层

### PR 快速门

适用于普通功能开发、交互优化、后端接口调整和提交前自检。

```bash
/usr/bin/python3 packaging/release/strict_acceptance.py \
  --profile pr \
  --rebuild-python-env \
  --install-desktop-deps
```

该入口会覆盖：

- Python、Node、Cargo 环境检查。
- `git diff --check`。
- 跟踪文件污染检查，避免 `.venv`、`node_modules`、`target`、`.rrd`、`.rbl`、`.zip`、`.sqlite`、`.env` 等本地生成物入库。
- `python packaging/release/sanity_check.py`。
- Python 后端、核心库、CLI 测试：`python -m pytest -q`。
- React/Tauri 前端测试：`cd apps/desktop && npm test`。
- 前端生产构建：`cd apps/desktop && npm run build`。
- Tauri shell 编译检查：`cd apps/desktop/src-tauri && cargo check --locked`。

### Release 严格门

适用于发布前冻结、版本 tag 前验收和回归测试。

```bash
/usr/bin/python3 packaging/release/strict_acceptance.py \
  --profile release \
  --rebuild-python-env \
  --install-desktop-deps
```

Release profile 会在 PR 快速门基础上执行 `tests/stability`，覆盖连续导入、Mapping、构建、查询、批量任务、API 健康循环和内存增长检查。

本地排障时可以缩短稳定性参数：

```bash
/usr/bin/python3 packaging/release/strict_acceptance.py \
  --profile release \
  --stability-loops 3 \
  --health-duration-seconds 30
```

### 完整打包验收

适用于正式安装包发布前。该命令会构建 bundled Python runtime 和 Tauri 安装包，耗时明显更长。

```bash
/usr/bin/python3 packaging/release/strict_acceptance.py \
  --profile release \
  --rebuild-python-env \
  --install-desktop-deps \
  --include-tauri-build
```

## 2. 后端 API 冒烟验收

自动测试通过后，使用临时 workspace 单独验证 FastAPI 与核心工作流。

```bash
export DATASCOPE_WORKSPACE="$(mktemp -d /tmp/datascope-smoke-XXXXXX)"
. .venv/bin/activate
python -m datascope_api.launcher --host 127.0.0.1 --port 8000
```

另开终端执行：

```bash
curl --noproxy 127.0.0.1 http://127.0.0.1:8000/api/health
curl --noproxy 127.0.0.1 http://127.0.0.1:8000/api/status
```

必须覆盖：

- 创建项目：`POST /api/projects`。
- 导入 fixture：`POST /api/projects/{project_id}/sources/import-workflow`，使用 `tests/fixtures/sample_sensor.csv`。
- 校验 Mapping：`POST /api/sources/{source_id}/mapping/validate`。
- 确认 Mapping：`POST /api/mappings/{mapping_id}/confirm`。
- 构建 Recording：`POST /api/recordings/build`。
- 轮询任务：`GET /api/jobs/{job_id}`，直到 `succeeded` 或失败状态。
- 查询结果：`GET /api/projects/{project_id}/recordings` 与 `POST /api/projects/{project_id}/query`。
- 失败路径：错误参数返回结构化 `{ "error": { "code", "message" } }`，服务日志可读。

验收结束后停止 API 进程并删除临时 workspace。

## 3. 前端交互验收

启动桌面开发版：

```bash
cd apps/desktop
npm run tauri:dev
```

Linux 图形兼容模式：

```bash
cd apps/desktop
npm run tauri:dev:safe
```

手动验收必须覆盖：

- Dashboard：创建项目、选择项目、刷新 workspace、最近 Recording 与任务数量正确。
- Import：选择 `tests/fixtures/sample_sensor.csv`，执行导入并自动 Mapping，预览、Schema、Mapping、校验结果可读。
- Build：确认 Mapping 后生成 `.rrd + .rbl`，构建中按钮禁用、进度可见，成功后允许打开 Rerun。
- Recordings/Queries：Recording 列表刷新，标签/参数更新，内置查询和自定义查询可运行，导出按钮状态合理。
- Diagnostics：无报告空状态可读，运行诊断后 summary、findings、evidence、导出记录可查看。
- Templates/Extensions：内置模板、插件/模板安装校验入口、批量导入入口状态清晰。
- Settings：默认导出目录、Rerun 产物目录、日志路径、API 状态和语言切换可用。
- 错误交互：缺失项目、无效路径、重复输出名、API 错误都显示局部错误或全局 toast，不出现无反馈失败。
- 生命周期：关闭桌面窗口后，本地 API 子进程同步退出；重复启动不会残留旧端口占用。

窗口尺寸至少检查：

- 1024x768
- 1366x768
- 1920x1080

## 4. 失败处理规则

- PR 快速门失败时，不直接修改业务代码，先记录失败命令、错误摘要、疑似模块和下一步建议。
- 如果失败来自已有工作区改动，应避免回退或覆盖用户改动。
- 如果失败来自环境依赖缺失，记录缺失工具、版本和安装建议。
- 如果前端手动验收失败，记录页面、操作步骤、期望结果、实际结果和截图路径。
- 修复后必须重新运行至少 PR 快速门；发布相关修复必须重新运行 Release 严格门。

## 5. 本次验收记录

- 时间：2026-07-07 09:36:39 CST。
- 分支状态：`main...origin/main [领先 5]`。
- 既有工作区改动：`apps/desktop/src/*` 多处前端文件已有修改，`apps/desktop/src/DashboardSection.test.tsx` 为未跟踪新增文件。
- 本次计划改动：仅新增或更新根目录 `TESTING.md`。
- PR 快速门：通过。
  - 命令：`/usr/bin/python3 packaging/release/strict_acceptance.py --profile pr --rebuild-python-env --install-desktop-deps`。
  - Python：`202 passed, 4 skipped, 1 warning`。
  - Desktop Vitest：`10` 个测试文件通过，`40` 个测试通过。
  - Desktop build：`tsc && vite build` 通过。
  - Tauri shell：`cargo check --locked` 通过。
- 后端 API 冒烟：通过。
  - 使用临时 workspace `/tmp/datascope-smoke-ZMRx49` 和端口 `18080`。
  - 覆盖 `/api/health`、`/api/status`、项目创建、`sample_sensor.csv` import workflow、Mapping 校验、Mapping 确认、Recording build job、job 轮询、recording 列表、`state_duration` 查询。
  - 结果：生成 `.rrd` 与 `.rbl` 产物，recording 数量 `1`，query template 数量 `6`，查询返回 `4` 行。
  - 注意：本机代理会影响 `127.0.0.1` HTTP 请求，脚本需设置 `trust_env=False` 或 `NO_PROXY=127.0.0.1,localhost`。
- 前端自动冒烟：通过。
  - 先使用已构建的 `apps/desktop/dist` 在 `127.0.0.1:1420` 启动临时静态服务，再使用临时 API workspace `/tmp/datascope-ui-api-0d8L0J` 在 `127.0.0.1:8000` 启动后端。
  - 使用 Microsoft Edge headless 访问 `http://127.0.0.1:1420/`。
  - 结果：DOM 渲染出 DataScope Studio 顶栏、Dashboard、Import & Mapping、Recordings & Query、诊断、Recipes & Extensions、设置、工作区卡片和在线状态；未出现“工作区连接或刷新失败”或 `Failed to fetch`。
  - 注意：`127.0.0.1:5177` 不是后端 CORS 白名单 origin，只能作为 Vite 页面可达性检查；标准前端冒烟应使用 `1420`。
- 前端桌面手动点击验收：未执行。
  - 原因：本次默认深度为 PR 快速门；完整 Tauri 窗口点击和 packaged runtime `--smoke-test` 属于 Release/打包验收。
  - 已由 Vitest、生产构建、Tauri `cargo check`、headless DOM 冒烟覆盖基础前端质量。
- Release 严格门与完整打包验收：未执行。
  - 原因：本次按计划只执行 PR 快速门，Release profile 和 `--include-tauri-build` 已作为发布前标准方法落盘。
