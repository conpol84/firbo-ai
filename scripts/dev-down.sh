#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT/.firbo/run"

for name in orchestrator openjarvis omniroute; do
  pidfile="$RUN_DIR/$name.pid"
  if [[ ! -f "$pidfile" ]]; then
    continue
  fi
  pid="$(cat "$pidfile")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    for _ in {1..20}; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.1
    done
    kill -9 "$pid" 2>/dev/null || true
    echo "Stopped $name (pid $pid)."
  fi
  rm -f "$pidfile"
done
