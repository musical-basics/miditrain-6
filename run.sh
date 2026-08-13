#!/usr/bin/env bash
#
# One command: boots the visualizer and opens it.
#
#   ./run.sh              boot on :3000 (or PORT=xxxx ./run.sh)
#   ./run.sh --no-open    boot without opening a browser
#
# Kills whatever is already holding the port first, so re-running this is
# always safe — no "port in use" and no orphaned dev server from last time.

set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-3000}"
OPEN=1
for arg in "$@"; do
  case "$arg" in
    --no-open) OPEN=0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

# ── free the port ───────────────────────────────────────────────────────────
# Kill by port (catches any stray process), then by name (catches a dev server
# that already crashed off its port but still holds the .next lock).
pids="$(lsof -ti tcp:"$PORT" 2>/dev/null || true)"
if [ -n "$pids" ]; then
  echo "Port $PORT in use by PID(s): $pids — stopping them."
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null || true
  sleep 1
  still="$(lsof -ti tcp:"$PORT" 2>/dev/null || true)"
  if [ -n "$still" ]; then
    # shellcheck disable=SC2086
    kill -9 $still 2>/dev/null || true
    sleep 1
  fi
fi
pkill -f "next dev" 2>/dev/null || true
pkill -f "next-server" 2>/dev/null || true

cd visualizer

# ── deps (only when they're actually stale) ─────────────────────────────────
if [ ! -d node_modules ] || [ package.json -nt node_modules ]; then
  echo "Installing dependencies..."
  pnpm install
fi

# ── boot, wait for it to answer, then open ──────────────────────────────────
echo "Booting visualizer on http://localhost:$PORT ..."
pnpm dev --port "$PORT" &
DEV_PID=$!

# Ctrl-C should take the dev server down with it, not orphan it.
trap 'kill $DEV_PID 2>/dev/null || true' INT TERM

for _ in $(seq 1 60); do
  if curl -sf -o /dev/null "http://localhost:$PORT"; then
    echo "Ready."
    [ "$OPEN" -eq 1 ] && open "http://localhost:$PORT/compare" 2>/dev/null || true
    break
  fi
  # if the dev server died during startup, stop waiting and surface it
  if ! kill -0 "$DEV_PID" 2>/dev/null; then
    echo "Dev server exited during startup." >&2
    wait "$DEV_PID"
    exit 1
  fi
  sleep 1
done

echo "Comparison GUI: http://localhost:$PORT/compare"
echo "Piano roll:     http://localhost:$PORT"
echo "(Ctrl-C to stop)"
wait "$DEV_PID"
