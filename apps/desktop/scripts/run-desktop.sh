#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

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

ensure_node
cleanup_stale_desktop_processes

cd "$APP_DIR"
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
