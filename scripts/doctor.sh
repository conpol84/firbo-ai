#!/usr/bin/env bash
set -u

check() {
  local name="$1" url="$2"
  if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
    printf "%-14s OK  %s\n" "$name" "$url"
    return 0
  fi
  printf "%-14s FAIL %s\n" "$name" "$url"
  return 1
}

failed=0
check "OmniRoute" "http://127.0.0.1:20128/api/monitoring/health" || failed=1
check "OpenJarvis" "http://127.0.0.1:8000/health" || failed=1
check "FIRBO" "http://127.0.0.1:8787/health" || failed=1
exit "$failed"
