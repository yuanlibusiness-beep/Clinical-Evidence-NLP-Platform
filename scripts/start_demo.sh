#!/usr/bin/env bash
# One-command local run on macOS/Linux: API on :8000, UI on :3000. No API key needed.
#   ./scripts/start_demo.sh        (Ctrl+C stops both)
set -euo pipefail
cd "$(dirname "$0")/.."

PY=${PYTHON:-python3}
command -v "$PY" >/dev/null || { echo "Python 3.10+ not found"; exit 1; }
command -v npm  >/dev/null || { echo "Node.js (npm) not found"; exit 1; }
[ -f .env ] || cp .env.example .env

if [ ! -x backend/.venv/bin/python ]; then
  echo "[1/2] Creating backend/.venv and installing Python deps (first run only)..."
  "$PY" -m venv backend/.venv
  backend/.venv/bin/python -m pip install --upgrade pip >/dev/null
  backend/.venv/bin/python -m pip install -r backend/requirements.txt
fi
if [ ! -d frontend/node_modules ]; then
  echo "[2/2] Installing frontend deps (first run only)..."
  (cd frontend && npm install --no-audit --no-fund)
fi

(cd backend && exec .venv/bin/python -m uvicorn app.main:app --port 8000) &
API_PID=$!
(cd frontend && exec npm run dev) &
UI_PID=$!
trap 'kill $API_PID $UI_PID 2>/dev/null' EXIT INT TERM

echo "API  http://localhost:8000/docs"
echo "UI   http://localhost:3000   (Ctrl+C to stop)"
wait
