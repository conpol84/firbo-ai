#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT/.firbo/run"
LOG_DIR="$ROOT/.firbo/logs"
mkdir -p "$RUN_DIR" "$LOG_DIR"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

need git
need curl
need python3
need uv
need node
need npm

cd "$ROOT"
git submodule update --init --recursive

if [[ ! -d "$ROOT/packages/openjarvis/.venv" ]]; then
  (cd "$ROOT/packages/openjarvis" && uv sync --extra server)
fi

if [[ ! -d "$ROOT/packages/omniroute/node_modules" ]]; then
  (cd "$ROOT/packages/omniroute" && npm install)
fi

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  python3 -m venv "$ROOT/.venv"
fi
"$ROOT/.venv/bin/python" -m pip install -q -r "$ROOT/services/orchestrator/requirements.txt"

healthy() {
  curl -fsS --max-time 3 "$1" >/dev/null 2>&1
}

start_bg() {
  local name="$1"
  local logfile="$2"
  local pidfile="$3"
  shift 3
  if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "$name already running (pid $(cat "$pidfile"))."
    return
  fi
  nohup "$@" >"$logfile" 2>&1 &
  echo $! >"$pidfile"
  echo "Started $name (pid $!)."
}

if ! healthy "http://127.0.0.1:20128/api/monitoring/health"; then
  start_bg "OmniRoute" "$LOG_DIR/omniroute.log" "$RUN_DIR/omniroute.pid"     node "$ROOT/packages/omniroute/bin/omniroute.mjs" serve --headless --port 20128
fi

if ! healthy "http://127.0.0.1:8000/health"; then
  (
    cd "$ROOT/packages/openjarvis"
    if [[ -f "$RUN_DIR/openjarvis.pid" ]] && kill -0 "$(cat "$RUN_DIR/openjarvis.pid")" 2>/dev/null; then
      echo "OpenJarvis already running (pid $(cat "$RUN_DIR/openjarvis.pid"))."
    else
      nohup uv run jarvis serve --port 8000 >"$LOG_DIR/openjarvis.log" 2>&1 &
      echo $! >"$RUN_DIR/openjarvis.pid"
      echo "Started OpenJarvis (pid $!)."
    fi
  )
fi

if ! healthy "http://127.0.0.1:8787/health"; then
  start_bg "FIRBO orchestrator" "$LOG_DIR/orchestrator.log" "$RUN_DIR/orchestrator.pid"     "$ROOT/.venv/bin/python" -m uvicorn services.orchestrator.app:app --app-dir "$ROOT" --host 127.0.0.1 --port 8787
fi

for i in {1..60}; do
  omni=0; jarvis=0; firbo=0
  healthy "http://127.0.0.1:20128/api/monitoring/health" && omni=1
  healthy "http://127.0.0.1:8000/health" && jarvis=1
  healthy "http://127.0.0.1:8787/health" && firbo=1
  if [[ "$omni" == 1 && "$jarvis" == 1 && "$firbo" == 1 ]]; then
    echo "FIRBO stack is ready."
    echo "  OmniRoute:  http://127.0.0.1:20128"
    echo "  OpenJarvis: http://127.0.0.1:8000"
    echo "  FIRBO:      http://127.0.0.1:8787"
    exit 0
  fi
  sleep 1
done

echo "Stack did not become healthy. Check $LOG_DIR." >&2
"$ROOT/scripts/doctor.sh" || true
exit 1
