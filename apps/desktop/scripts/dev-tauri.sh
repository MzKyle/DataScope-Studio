#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$APP_DIR/../.." && pwd)"
API_URL="http://127.0.0.1:8000/api/health"
API_PID=""

cleanup_stale_desktop_processes() {
  pkill -f "$APP_DIR/node_modules/.bin/vite" >/dev/null 2>&1 || true
  pkill -f "$APP_DIR/src-tauri/target/debug/datascope-studio" >/dev/null 2>&1 || true
  pkill -f "target/debug/datascope-studio" >/dev/null 2>&1 || true
}

api_ready() {
  curl -fsS --max-time 2 "$API_URL" >/dev/null 2>&1
}

api_port_pids() {
  ss -ltnp 2>/dev/null \
    | awk '$4 ~ /:8000$/ {print}' \
    | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' \
    | sort -u
}

api_port_in_use() {
  [[ -n "$(api_port_pids)" ]]
}

kill_stale_datascope_api() {
  local killed=0
  while read -r pid; do
    [[ -z "$pid" ]] && continue
    local cmd
    cmd="$(ps -p "$pid" -o cmd= 2>/dev/null || true)"
    if [[ "$cmd" == *"uvicorn datascope_api.main:app"* ]]; then
      echo "Stopping stale DataScope API process $pid"
      kill "$pid" >/dev/null 2>&1 || true
      killed=1
    fi
  done < <(api_port_pids)
  if [[ "$killed" == "1" ]]; then
    for _ in {1..10}; do
      api_port_in_use || return 0
      sleep 1
    done
  fi
}

cleanup() {
  if [[ -n "$API_PID" ]]; then
    kill "$API_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

cleanup_stale_desktop_processes

if api_ready; then
  echo "DataScope API already running at $API_URL"
else
  if api_port_in_use; then
    kill_stale_datascope_api
  fi
  if api_ready; then
    echo "DataScope API already running at $API_URL"
  elif api_port_in_use; then
    echo "Port 8000 is already in use, but $API_URL is not healthy." >&2
    echo "Stop the process using port 8000, then rerun npm run tauri:dev." >&2
    ss -ltnp 2>/dev/null | awk '$4 ~ /:8000$/ {print}' >&2
    exit 1
  fi
fi

if ! api_ready; then
  if [[ ! -x "$REPO_ROOT/.venv/bin/python" ]]; then
    echo "Missing Python venv at $REPO_ROOT/.venv" >&2
    echo "Run the backend setup commands in RUNNING.md first." >&2
    exit 1
  fi
  echo "Starting DataScope API at $API_URL"
  (
    cd "$REPO_ROOT"
    "$REPO_ROOT/.venv/bin/python" -m uvicorn datascope_api.main:app --host 127.0.0.1 --port 8000
  ) &
  API_PID="$!"
  for _ in {1..30}; do
    if api_ready; then
      break
    fi
    sleep 1
  done
  if ! api_ready; then
    echo "DataScope API did not become ready at $API_URL" >&2
    if api_port_in_use; then
      ss -ltnp 2>/dev/null | awk '$4 ~ /:8000$/ {print}' >&2
    fi
    exit 1
  fi
fi

cd "$APP_DIR"
npm run build
vite preview --host 127.0.0.1 --port 1420 --strictPort
