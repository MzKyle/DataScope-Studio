#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$APP_DIR/../.." && pwd)"
PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
VERIFY_TIMEOUT="${DATASCOPE_FRONTEND_VERIFY_TIMEOUT:-120s}"
WORKSPACE_DIR="$(mktemp -d /tmp/datascope-frontend-verify-XXXXXX)"

cleanup() {
  rm -rf "$WORKSPACE_DIR"
}
trap cleanup EXIT

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing $PYTHON_BIN. Run the PR acceptance gate or create .venv first." >&2
  exit 1
fi

if ! command -v timeout >/dev/null 2>&1; then
  echo "Missing timeout command; install coreutils or run cargo command manually." >&2
  exit 1
fi

cd "$APP_DIR"
npm run build

cd "$APP_DIR/src-tauri"
echo "Starting DataScope Studio frontend smoke with workspace: $WORKSPACE_DIR"
NO_PROXY="127.0.0.1,localhost,${NO_PROXY:-}" \
no_proxy="127.0.0.1,localhost,${no_proxy:-}" \
DATASCOPE_WORKSPACE="$WORKSPACE_DIR" \
DATASCOPE_SAFE_GRAPHICS="${DATASCOPE_SAFE_GRAPHICS:-1}" \
timeout "$VERIFY_TIMEOUT" \
  cargo run --no-default-features -- --frontend-smoke-test

echo "DataScope Studio frontend smoke passed."
