#!/usr/bin/env bash
set -euo pipefail

LOCK_FILE="data/run_live.lock"
if [[ -f "$LOCK_FILE" ]]; then
  EXISTING_PID="$(cat "$LOCK_FILE" 2>/dev/null || true)"
  if [[ -n "$EXISTING_PID" ]] && kill -0 "$EXISTING_PID" 2>/dev/null; then
    echo "run_live already running (PID $EXISTING_PID). Stop it first."
    exit 1
  fi
fi
echo "$$" > "$LOCK_FILE"

python3 src/reset_all.py

python3 src/loop.py &
BOT_PID=$!
# python3 src/price_loop.py &
# PRICE_PID=$!

cleanup() {
  rm -f "$LOCK_FILE"
  kill "$BOT_PID" 2>/dev/null || true
  # kill "$PRICE_PID" 2>/dev/null || true
}
trap cleanup EXIT

# Security: Serve ONLY the UI folder, not the root
# Link data folder so UI can access it
mkdir -p ui/simple/data
# Remove potential existing symlink to avoid recursive mess if run multiple times
rm -f ui/simple/data/dashboard.json
ln -s ../../../data/dashboard.json ui/simple/data/dashboard.json

cd ui/simple && python3 -m http.server 8000
