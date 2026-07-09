#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$APP_DIR/../.." && pwd)"

SAFE_GRAPHICS="${DATASCOPE_SAFE_GRAPHICS:-1}"
DO_BUILD=1
DRY_RUN=0
KEEP_APP=0
WORKSPACE_DIR="${DATASCOPE_WORKSPACE:-}"
WORKSPACE_CREATED=0
REPORT_PATH="${DATASCOPE_ACCEPTANCE_REPORT:-}"
RUN_LOG=""
APP_PID=""

usage() {
  cat <<'USAGE'
Usage: npm run accept:desktop -- [options]

Start the real DataScope Studio desktop app and guide a manual click acceptance run.

Options:
  --safe                 Use safe Linux graphics mode (default).
  --performance          Use performance graphics mode.
  --no-build             Skip frontend build before launch.
  --workspace DIR        Use a specific DATASCOPE_WORKSPACE.
  --report FILE          Write the acceptance report to FILE.
  --keep-app             Leave the desktop process running when the checklist ends.
  --dry-run              Print configuration and checklist without launching the app.
  -h, --help             Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --safe)
      SAFE_GRAPHICS=1
      shift
      ;;
    --performance)
      SAFE_GRAPHICS=0
      shift
      ;;
    --no-build)
      DO_BUILD=0
      shift
      ;;
    --workspace)
      WORKSPACE_DIR="${2:-}"
      if [[ -z "$WORKSPACE_DIR" ]]; then
        echo "--workspace requires a directory." >&2
        exit 2
      fi
      shift 2
      ;;
    --report)
      REPORT_PATH="${2:-}"
      if [[ -z "$REPORT_PATH" ]]; then
        echo "--report requires a file path." >&2
        exit 2
      fi
      shift 2
      ;;
    --keep-app)
      KEEP_APP=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

timestamp="$(date '+%Y%m%d-%H%M%S')"
report_dir="${DATASCOPE_ACCEPTANCE_REPORT_DIR:-/tmp/datascope-desktop-acceptance}"
mkdir -p "$report_dir"

if [[ -z "$REPORT_PATH" ]]; then
  REPORT_PATH="$report_dir/desktop-manual-click-$timestamp.md"
fi

RUN_LOG="$report_dir/desktop-run-$timestamp.log"

if [[ -z "$WORKSPACE_DIR" ]]; then
  WORKSPACE_DIR="$(mktemp -d /tmp/datascope-desktop-acceptance-workspace-XXXXXX)"
  WORKSPACE_CREATED=1
else
  mkdir -p "$WORKSPACE_DIR"
fi

cleanup() {
  if [[ -n "$APP_PID" && "$KEEP_APP" != "1" ]]; then
    kill "$APP_PID" >/dev/null 2>&1 || true
    wait "$APP_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

check_dependency() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing dependency: $command_name" >&2
    exit 1
  fi
}

check_dependency npm
check_dependency cargo

cat > "$REPORT_PATH" <<REPORT
# DataScope Studio 前端桌面手动点击验收报告

- 时间：$(date '+%Y-%m-%d %H:%M:%S %Z')
- 应用目录：$APP_DIR
- Workspace：$WORKSPACE_DIR
- Fixture：$REPO_ROOT/tests/fixtures/sample_sensor.csv
- 运行日志：$RUN_LOG
- 图形模式：$([[ "$SAFE_GRAPHICS" == "1" ]] && echo "safe" || echo "performance")

## 检查结果
REPORT

CHECK_TITLES=(
  "启动与外壳"
  "Dashboard"
  "Import 与 Mapping"
  "Build"
  "Recordings 与 Queries"
  "Diagnostics"
  "Templates 与 Extensions"
  "Settings"
  "错误交互"
  "窗口尺寸 1024x768"
  "窗口尺寸 1366x768"
  "窗口尺寸 1920x1080"
  "生命周期"
)

CHECK_DETAILS=(
  "桌面窗口可见；侧边导航可点击；在线状态可读；无启动错误 toast。"
  "创建项目、选择项目、刷新 workspace；最近 Recording 与任务数量展示合理。"
  "选择 tests/fixtures/sample_sensor.csv；执行导入和自动 Mapping；预览、Schema、Mapping、校验结果可读。"
  "确认 Mapping 后生成 .rrd + .rbl；构建中按钮禁用且进度可见；成功后打开 Rerun 按钮状态合理。"
  "Recording 列表刷新；标签/参数更新；内置查询和自定义查询可运行；导出按钮状态合理。"
  "无报告空状态可读；运行诊断后 summary、findings、evidence、导出记录可查看。"
  "内置模板、插件/模板安装校验入口、批量导入入口状态清晰。"
  "默认导出目录、Rerun 产物目录、日志路径、API 状态和语言切换可用。"
  "缺失项目、无效路径、重复输出名、API 错误都显示局部错误或全局 toast，不出现无反馈失败。"
  "在 1024x768 下顶部、侧边栏、主内容、表格和弹窗不重叠、不溢出。"
  "在 1366x768 下顶部、侧边栏、主内容、表格和弹窗不重叠、不溢出。"
  "在 1920x1080 下顶部、侧边栏、主内容、表格和弹窗不重叠、不溢出。"
  "关闭桌面窗口后本地 API 子进程同步退出；重复启动不会残留旧端口占用。"
)

print_checklist() {
  echo
  echo "Manual click acceptance checklist:"
  for index in "${!CHECK_TITLES[@]}"; do
    printf "%2d. %s - %s\n" "$((index + 1))" "${CHECK_TITLES[$index]}" "${CHECK_DETAILS[$index]}"
  done
  echo
}

if [[ "$DRY_RUN" == "1" ]]; then
  echo "Dry run only. No desktop process will be launched."
  echo "Report: $REPORT_PATH"
  echo "Workspace: $WORKSPACE_DIR"
  echo "Run log: $RUN_LOG"
  print_checklist
  exit 0
fi

cd "$APP_DIR"
if [[ "$DO_BUILD" == "1" ]]; then
  npm run build
fi

echo "Starting DataScope Studio desktop app for manual click acceptance."
echo "Report: $REPORT_PATH"
echo "Workspace: $WORKSPACE_DIR"
echo "Run log: $RUN_LOG"

(
  DATASCOPE_WORKSPACE="$WORKSPACE_DIR" \
  DATASCOPE_SAFE_GRAPHICS="$SAFE_GRAPHICS" \
  bash scripts/run-desktop.sh
) >"$RUN_LOG" 2>&1 &
APP_PID="$!"

sleep 5
if ! kill -0 "$APP_PID" >/dev/null 2>&1; then
  echo "Desktop app exited during startup. See log: $RUN_LOG" >&2
  tail -n 80 "$RUN_LOG" >&2 || true
  exit 1
fi

if command -v wmctrl >/dev/null 2>&1; then
  echo "wmctrl detected. The script will try to resize the DataScope Studio window for size checks."
else
  echo "wmctrl not found. Resize the DataScope Studio window manually for size checks."
fi

resize_window_if_possible() {
  local width="$1"
  local height="$2"
  if command -v wmctrl >/dev/null 2>&1; then
    wmctrl -r "DataScope Studio" -e "0,0,0,${width},${height}" >/dev/null 2>&1 || true
  fi
}

prompt_result() {
  local title="$1"
  local detail="$2"
  local result note screenshot

  echo
  echo "[$title]"
  echo "$detail"
  case "$title" in
    "窗口尺寸 1024x768")
      resize_window_if_possible 1024 768
      ;;
    "窗口尺寸 1366x768")
      resize_window_if_possible 1366 768
      ;;
    "窗口尺寸 1920x1080")
      resize_window_if_possible 1920 1080
      ;;
  esac

  while true; do
    read -r -p "Result [p=pass, f=fail, s=skip, q=quit]: " result
    case "$result" in
      p | P)
        result="PASS"
        break
        ;;
      f | F)
        result="FAIL"
        break
        ;;
      s | S)
        result="SKIP"
        break
        ;;
      q | Q)
        result="QUIT"
        break
        ;;
      *)
        echo "Please enter p, f, s, or q."
        ;;
    esac
  done

  read -r -p "Note, issue, or evidence path (optional): " note
  screenshot=""
  if [[ "$result" == "FAIL" ]]; then
    read -r -p "Screenshot path for this failure (optional): " screenshot
  fi

  {
    echo
    echo "### $title"
    echo
    echo "- 结果：$result"
    echo "- 验收点：$detail"
    if [[ -n "$note" ]]; then
      echo "- 记录：$note"
    fi
    if [[ -n "$screenshot" ]]; then
      echo "- 截图：$screenshot"
    fi
  } >> "$REPORT_PATH"

  [[ "$result" != "QUIT" ]]
}

print_checklist
read -r -p "Press Enter after the DataScope Studio window is visible..."

for index in "${!CHECK_TITLES[@]}"; do
  prompt_result "${CHECK_TITLES[$index]}" "${CHECK_DETAILS[$index]}" || break
done

{
  echo
  echo "## 收尾"
  echo
  echo "- 结束时间：$(date '+%Y-%m-%d %H:%M:%S %Z')"
  echo "- 桌面进程 PID：$APP_PID"
  echo "- Workspace：$WORKSPACE_DIR"
  echo "- 运行日志：$RUN_LOG"
} >> "$REPORT_PATH"

if [[ "$KEEP_APP" != "1" ]]; then
  read -r -p "Stop desktop app now? [Y/n]: " stop_answer
  if [[ "$stop_answer" =~ ^[nN] ]]; then
    KEEP_APP=1
    echo "Desktop app left running with PID $APP_PID."
  fi
fi

if [[ "$WORKSPACE_CREATED" == "1" ]]; then
  read -r -p "Delete temporary workspace? [y/N]: " delete_workspace
  if [[ "$delete_workspace" =~ ^[yY] ]]; then
    rm -rf "$WORKSPACE_DIR"
    echo "Deleted workspace: $WORKSPACE_DIR"
  else
    echo "Workspace kept: $WORKSPACE_DIR"
  fi
fi

echo "Manual click acceptance report written to: $REPORT_PATH"
