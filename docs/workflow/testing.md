# 测试验收

本文档定义 DataScope Studio 发布前验收流程。普通 PR 至少执行快速质量门；发布前必须执行 release profile，并补充桌面与安装包冒烟。

## 质量门入口

PR / 每次提交快速门：

```bash
python packaging/release/strict_acceptance.py \
  --profile pr \
  --rebuild-python-env \
  --install-desktop-deps
```

发布前严格门：

```bash
python packaging/release/strict_acceptance.py \
  --profile release \
  --rebuild-python-env \
  --install-desktop-deps
```

发布前如需在本机同时验证正式 runtime 与安装包构建：

```bash
python packaging/release/strict_acceptance.py \
  --profile release \
  --rebuild-python-env \
  --install-desktop-deps \
  --include-tauri-build
```

`--include-tauri-build` 会自动包含正式 `npm run runtime:build`。该步骤可能下载独立 Python runtime，耗时明显长于普通测试。

## 自动测试覆盖

`strict_acceptance.py --profile pr` 会执行：

- Python 环境版本、Node `>=20.19`、Cargo 可用性检查。
- `git diff --check`。
- 跟踪文件污染检查，禁止 `.venv`、`node_modules`、`target`、`.rrd`、`.rbl`、`.zip`、`.sqlite`、`.env` 等本地生成物进入版本库。
- `python packaging/release/sanity_check.py`。
- `python -m pytest -q`。
- `cd apps/desktop && npm test`。
- `cd apps/desktop && npm run build`。
- `cd apps/desktop/src-tauri && cargo check --locked`。

`strict_acceptance.py --profile release` 额外执行 `tests/stability`：

- 连续导入、inspect、mapping、构建 `.rrd + .rbl`、查询，默认 50 轮。
- `max_workers=1/2/4` 批量导入一致性。
- 混合成功/失败批量任务，修复输入后 retry 失败项。
- API `/api/health` 与核心请求循环，默认 30 分钟。
- Linux 上检查进程 RSS 增长；超过阈值视为稳定性失败。

可临时缩短 release profile 以做本地排障：

```bash
python packaging/release/strict_acceptance.py \
  --profile release \
  --stability-loops 3 \
  --health-duration-seconds 30
```

## 单项命令

需要单独排障时可直接运行：

```bash
. .venv/bin/activate
python -m pytest -q

cd apps/desktop
npm test
npm run build

cd src-tauri
cargo check --locked
```

Release sanity：

```bash
. .venv/bin/activate
python packaging/release/sanity_check.py
```

## 桌面与安装包冒烟

开发桌面端：

```bash
cd apps/desktop
npm run tauri:dev
```

Linux 图形兼容模式：

```bash
cd apps/desktop
npm run tauri:dev:safe
```

手工冒烟必须覆盖：

- 创建项目。
- 选择 CSV 或 JSONL fixture。
- 导入并自动 Mapping。
- 预览、校验并确认 Mapping。
- 生成 `.rrd + .rbl`。
- 打开 Recordings / Queries / Diagnostics 页面。
- 查看设置页中的 desktop/backend 日志路径。
- 退出应用后确认后端进程同步退出。

安装包发布前由 GitHub release matrix 验证 Windows x64、macOS Apple Silicon、macOS Intel、Linux `.deb` 与 AppImage。Linux 本机可额外执行：

```bash
cd apps/desktop
npm run package:linux
```

## 清理本地生成物

默认 dry-run：

```bash
cd apps/desktop
npm run clean:local
```

确认后删除：

```bash
cd apps/desktop
npm run clean:local -- --apply
```
