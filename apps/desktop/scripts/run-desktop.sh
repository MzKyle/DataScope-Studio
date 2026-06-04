#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$APP_DIR/../.." && pwd)"
API_URL="http://127.0.0.1:8000/api/health"
API_PID=""

node_version_ok() {
  local version major minor
  version="$(node -v 2>/dev/null || true)"
  version="${version#v}"
  major="${version%%.*}"
  minor="${version#*.}"
  minor="${minor%%.*}"
  [[ "$major" =~ ^[0-9]+$ ]] || return 1
  [[ "$minor" =~ ^[0-9]+$ ]] || return 1
  (( major > 20 || (major == 20 && minor >= 19) ))
}

ensure_node() {
  if node_version_ok; then
    return
  fi

  local candidate
  for candidate in \
    "$HOME/.local/node-v20.20.1-linux-x64/bin" \
    "$HOME/.local/node-v20.19.5-linux-x64/bin" \
    "$HOME/.nvm/versions/node/v20.20.1/bin" \
    "$HOME/.nvm/versions/node/v20.19.5/bin"; do
    if [[ -x "$candidate/node" ]]; then
      PATH="$candidate:$PATH"
      export PATH
      if node_version_ok; then
        echo "Using Node $(node -v) from $candidate"
        return
      fi
    fi
  done

  echo "Node >=20.19.0 is required. Current node is: $(node -v 2>/dev/null || echo missing)" >&2
  echo "Install Node 20.19+ or add it to PATH, then rerun npm run tauri:dev." >&2
  exit 1
}

cleanup_stale_desktop_processes() {
  pkill -f "$APP_DIR/src-tauri/target/debug/datascope-studio" >/dev/null 2>&1 || true
}

api_ready() {
  curl -fsS --noproxy 127.0.0.1 --max-time 2 "$API_URL" >/dev/null 2>&1
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

ensure_api() {
  if api_ready; then
    echo "DataScope API already running at $API_URL"
    return
  fi

  if api_port_in_use; then
    kill_stale_datascope_api
  fi

  if api_ready; then
    echo "DataScope API already running at $API_URL"
    return
  fi

  if api_port_in_use; then
    echo "Port 8000 is already in use, but $API_URL is not healthy." >&2
    ss -ltnp 2>/dev/null | awk '$4 ~ /:8000$/ {print}' >&2
    exit 1
  fi

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
      return
    fi
    sleep 1
  done

  echo "DataScope API did not become ready at $API_URL" >&2
  exit 1
}

ensure_node
cleanup_stale_desktop_processes
ensure_api

cd "$APP_DIR"
build_frontend_if_needed() {
  local dist_index="$APP_DIR/dist/index.html"
  if [[ "${DATASCOPE_FORCE_BUILD:-0}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]]; then
    echo "DATASCOPE_FORCE_BUILD is set; rebuilding desktop frontend."
    npm run build
    return
  fi

  if [[ ! -f "$dist_index" ]]; then
    echo "Desktop frontend build output is missing; building once."
    npm run build
    return
  fi

  local changed
  changed="$(
    find \
      "$APP_DIR/src" \
      "$APP_DIR/index.html" \
      "$APP_DIR/package.json" \
      "$APP_DIR/package-lock.json" \
      "$APP_DIR/tsconfig.json" \
      "$APP_DIR/vite.config.ts" \
      -newer "$dist_index" -print -quit 2>/dev/null
  )"
  if [[ -n "$changed" ]]; then
    echo "Desktop frontend changed since last build; rebuilding."
    npm run build
    return
  fi

  echo "Desktop frontend build is up to date. Set DATASCOPE_FORCE_BUILD=1 to rebuild."
}

build_frontend_if_needed

cd "$APP_DIR/src-tauri"
if [[ "${DATASCOPE_SAFE_GRAPHICS:-0}" =~ ^(1|true|TRUE|yes|YES|on|ON)$ ]]; then
  echo "Starting Tauri in safe graphics mode. This is more stable on some Linux GPU setups, but slower."
  WEBKIT_DISABLE_COMPOSITING_MODE=1 \
  WEBKIT_DISABLE_DMABUF_RENDERER=1 \
  WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1 \
  LIBGL_ALWAYS_SOFTWARE=1 \
  GSK_RENDERER=cairo \
  GDK_BACKEND=x11 \
  NO_AT_BRIDGE=1 \
  cargo run --no-default-features
else
  echo "Starting Tauri in performance graphics mode. Use DATASCOPE_SAFE_GRAPHICS=1 if WebKit crashes."
  WEBKIT_DISABLE_DMABUF_RENDERER=1 \
  NO_AT_BRIDGE=1 \
  cargo run --no-default-features
fi
