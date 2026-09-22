#!/usr/bin/env bash
# Start the FastAPI backend and Vite web UI together.
# Usage (from anywhere):
#   ./scripts/dev.sh
#   npm run dev
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

API_PORT="${FPA_API_PORT:-8765}"
WEB_PORT="${FPA_WEB_PORT:-5173}"

if [ ! -x "$ROOT/venv/bin/python" ]; then
  echo "Creating venv..."
  PY=python3
  if [ -x "${HOME}/.pyenv/versions/3.12.4/bin/python3" ]; then
    PY="${HOME}/.pyenv/versions/3.12.4/bin/python3"
  fi
  "$PY" -m venv "$ROOT/venv"
  "$ROOT/venv/bin/pip" install -U pip
  "$ROOT/venv/bin/pip" install -r "$ROOT/requirements.txt"
fi

if [ ! -d "$ROOT/web/node_modules" ]; then
  echo "Installing web dependencies..."
  npm --prefix "$ROOT/web" install
fi

API_PID=""
cleanup() {
  if [ -n "$API_PID" ] && kill -0 "$API_PID" 2>/dev/null; then
    kill "$API_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

kill_port_listeners() {
  local port="$1"
  local pids=""
  if command -v lsof >/dev/null 2>&1; then
    pids="$(lsof -nP -iTCP:"${port}" -sTCP:LISTEN -t 2>/dev/null || true)"
  fi
  if [ -n "$pids" ]; then
    echo "Stopping process(es) on :${port}..."
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 0.3
    # shellcheck disable=SC2086
    kill -9 $pids 2>/dev/null || true
  fi
}

# Always (re)start the API so new routes / code changes apply. A leftover
# process from an earlier session was causing 404s (e.g. /arrange/clear).
kill_port_listeners "$API_PORT"
echo "Starting API on :${API_PORT}..."
FPA_API_PORT="$API_PORT" FPA_API_RELOAD=1 "$ROOT/venv/bin/python" -m api.app &
API_PID=$!
for _ in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo "API process exited before becoming healthy."
    exit 1
  fi
  sleep 0.1
done
if ! curl -sf "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1; then
  echo "API did not start on :${API_PORT}"
  exit 1
fi

echo "Web UI: http://localhost:${WEB_PORT}"
(sleep 1.2; open "http://localhost:${WEB_PORT}" >/dev/null 2>&1 || true) &

cd "$ROOT/web"
npm run dev -- --port "$WEB_PORT" --strictPort
