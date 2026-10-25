#!/usr/bin/env bash
# PINNED route-only deployment for existing OpenJarvis. No bootstrap, Caddy,
# MCP reconfiguration, Docker image, Git checkout or Supabase mutations.
set -Eeuo pipefail
umask 077
PINNED_COMMIT="${2:-}"
EXPECTED_BASE_SHA256=de284eb459227a35c46cf1642003c23635ae190e2b0f508f9b81fc8412b53ce2
# Also permit the exact reviewed PR #29 route if that release was installed.
EXPECTED_PR29_SHA256=b91640bee02142aaa60f5196f5d2cc93aec0f7f71f86540e507ca9f1645f27a7
# Owner-installed PR #30, verified by the 2026-10-25 release receipt.
EXPECTED_PR30_SHA256=73d9c253e55d4885343a63c05bfeb1a7494168b4e54a12449baeb79a65d48c8f
# Owner-installed PR #31; confirmed by release and diagnostic receipts.
EXPECTED_PR31_SHA256=6693f080b4faaa170dd922f75c0a9efbb24c84c121806ebaafd2c4b607460c97
VENV_PY=/home/jarvis/.openjarvis/.venv/bin/python
MODE=--check
if [[ $# -gt 0 ]]; then MODE="$1"; fi
die(){ echo "FIRBO_RELEASE_BLOCKED: $*" >&2; exit 1; }
[[ "$MODE" == --check || "$MODE" == --apply ]] || die "expected --check or --apply"
[[ "$PINNED_COMMIT" =~ ^[0-9a-f]{40}$ ]] || die "supply the reviewed 40-character commit as the second argument"
[[ $(id -u) -eq 0 ]] || die "run as root"
for command in git python3 curl tar sudo flock sha256sum systemctl; do command -v "$command" >/dev/null || die "missing $command"; done
exec 9>/run/lock/firbo-browser-route-release.lock
flock -n 9 || die "another browser release holds the deployment lock"
[[ -x "$VENV_PY" ]] || die "OpenJarvis venv missing"
ROOT="$(git -C "$PWD" rev-parse --show-toplevel 2>/dev/null)" || die "cd to firbo-ai checkout first"
REMOTE="$(git -C "$ROOT" config --get remote.origin.url || true)"
case "$REMOTE" in
 https://github.com/conpol84/firbo-ai|https://github.com/conpol84/firbo-ai.git|git@github.com:conpol84/firbo-ai|git@github.com:conpol84/firbo-ai.git|ssh://git@github.com/conpol84/firbo-ai|ssh://git@github.com/conpol84/firbo-ai.git) ;;
 *) die "wrong repository remote";;
esac
git -C "$ROOT" cat-file -e "$PINNED_COMMIT^{commit}" 2>/dev/null \
 || die "pinned commit not present; fetch existing firbo-ai origin/main and retry"
TMP="$(mktemp -d /tmp/firbo-browser-route.XXXXXXXX)"
cleanup(){ rm -rf -- "$TMP"; }
trap cleanup EXIT
git -C "$ROOT" archive "$PINNED_COMMIT" \
 services/browser-mcp/firbo_browser_route.py \
 scripts/check-browser-native-contract.py \
 scripts/accept-browser-search-read.py \
 tests/test_browser_direct_intent.py \
 tests/test_generic_browser_goal_acceptance.py \
 tests/test_youtube_playback_acceptance.py \
 tests/test_browser_aria_observation.py \
 tests/test_browser_route_execution.py \
 tests/test_browser_acceptance_runner.py | tar -xf - -C "$TMP"
SOURCE="$TMP/services/browser-mcp/firbo_browser_route.py"
grep -q '^def _browser_goal_acceptance(' "$SOURCE" || die "generic acceptance missing"
grep -q '^def _youtube_verified_result(' "$SOURCE" || die "YouTube verifier missing"
grep -q '^def install_firbo_browser_route(' "$SOURCE" || die "route hook missing"
python3 -m py_compile "$SOURCE"
(
 cd "$TMP"
 python3 -m unittest discover -s tests -p test_browser_direct_intent.py -q
 python3 -m unittest discover -s tests -p test_generic_browser_goal_acceptance.py -q
 python3 -m unittest discover -s tests -p test_youtube_playback_acceptance.py -q
 python3 -m unittest discover -s tests -p test_browser_aria_observation.py -q
 python3 -m unittest discover -s tests -p test_browser_route_execution.py -q
 python3 -m unittest discover -s tests -p test_browser_acceptance_runner.py -q
) || die "route tests failed"
# Exercise the real installed framework, not only the dependency-free fixtures.
"$VENV_PY" "$TMP/scripts/check-browser-native-contract.py" -q \
 || die "installed OpenJarvis native tool contract failed"
echo FIRBO_BROWSER_NATIVE_TOOL_CONTRACT_PASS
echo FIRBO_BROWSER_SOURCE_TESTS_PASS
SERVER_DIR="$(sudo -u jarvis "$VENV_PY" - <<'PY'
import pathlib, openjarvis.server
print(pathlib.Path(openjarvis.server.__file__).resolve().parent)
PY
)" || die "could not resolve OpenJarvis server module"
ROUTE="$SERVER_DIR/firbo_browser_route.py"
REGISTER="$SERVER_DIR/routes.py"
[[ -f "$ROUTE" && ! -L "$ROUTE" && -f "$REGISTER" && ! -L "$REGISTER" ]] || die "existing route not found/symlink"
case "$ROUTE" in
 /home/jarvis/.openjarvis/.venv/lib/*/site-packages/openjarvis/server/firbo_browser_route.py) ;;
 *) die "unexpected destination path $ROUTE";;
esac
grep -q 'FIRBO_BROWSER_ROUTE_V1' "$REGISTER" || die "existing route registration missing"
grep -q '^def install_firbo_browser_route(' "$ROUTE" || die "installed module is not the FIRBO route"
systemctl is-active --quiet openjarvis.service || die "OpenJarvis service not active"
unauth_status(){
 curl -sS --max-time 4 -X POST -H 'content-type: application/json' \
 --data '{}' -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/v1/firbo/browser
}
CODE="$(unauth_status)" || die "route auth probe failed"
[[ "$CODE" == 401 ]] || die "expected unauthenticated HTTP 401, got $CODE"
echo FIRBO_BROWSER_AUTH_BOUNDARY_PASS
CURRENT_SHA="$(sha256sum "$ROUTE" | cut -d' ' -f1)"
CANDIDATE_SHA="$(sha256sum "$SOURCE" | cut -d' ' -f1)"
echo "CURRENT_BROWSER_SHA256=$CURRENT_SHA"
echo "TARGET_BROWSER_SHA256=$CANDIDATE_SHA"
if [[ "$CURRENT_SHA" == "$CANDIDATE_SHA" ]]; then
 echo FIRBO_BROWSER_ROUTE_ALREADY_CURRENT
 exit 0
fi
[[ "$CURRENT_SHA" == "$EXPECTED_BASE_SHA256" || "$CURRENT_SHA" == "$EXPECTED_PR29_SHA256" || "$CURRENT_SHA" == "$EXPECTED_PR30_SHA256" || "$CURRENT_SHA" == "$EXPECTED_PR31_SHA256" ]] \
 || die "installed route differs from reviewed baselines; preserve and reconcile local changes first"
if [[ "$MODE" == --check ]]; then
 echo FIRBO_BROWSER_ROUTE_UPGRADE_NEEDED
 echo "Dry-run complete; --apply replaces ONLY the browser route and restarts openjarvis.service."
 exit 0
fi
BACKUP_DIR=/var/backups/firbo-browser-route
install -d -o root -g root -m 0700 "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$BACKUP_DIR/firbo_browser_route.$STAMP.$CURRENT_SHA.py"
[[ "$(sha256sum "$ROUTE" | cut -d' ' -f1)" == "$CURRENT_SHA" ]] \
 || die "installed route changed during preflight"
cp -p -- "$ROUTE" "$BACKUP"
echo "FIRBO_BROWSER_BACKUP=$BACKUP"
ROLLBACK_NEEDED=1
rollback_on_error(){
 rc=$?
 trap - ERR
 if [[ "$ROLLBACK_NEEDED" == 1 ]]; then
  echo FIRBO_BROWSER_RELEASE_FAILED_RESTORING_PREVIOUS_MODULE >&2
  install -o jarvis -g jarvis -m 0644 -- "$BACKUP" "$ROUTE" || true
  systemctl restart openjarvis.service || true
  echo FIRBO_BROWSER_PREVIOUS_MODULE_RESTORED >&2
 fi
 exit "$rc"
}
trap rollback_on_error ERR
NEXT="$SERVER_DIR/.firbo_browser_route.$STAMP.new"
install -o jarvis -g jarvis -m 0644 -- "$SOURCE" "$NEXT"
sudo -u jarvis "$VENV_PY" -m py_compile "$NEXT"
mv -- "$NEXT" "$ROUTE"
sudo -u jarvis "$VENV_PY" -m py_compile "$ROUTE" "$REGISTER"
systemctl restart openjarvis.service
READY=0
for attempt in $(seq 1 25); do
 if systemctl is-active --quiet openjarvis.service \
  && curl -fsS --max-time 2 http://127.0.0.1:8765/health >/dev/null 2>&1 \
  && [[ "$(unauth_status)" == 401 ]]; then
  READY=1
  break
 fi
 sleep 1
done
[[ "$READY" == 1 ]] || { echo FIRBO_BROWSER_POSTRESTART_HEALTH_FAILED >&2; false; }
[[ "$(sha256sum "$ROUTE" | cut -d' ' -f1)" == "$CANDIDATE_SHA" ]] \
 || { echo FIRBO_BROWSER_DEPLOYED_BYTES_DIFFER >&2; false; }
ROLLBACK_NEEDED=0
trap - ERR
echo "FIRBO_BROWSER_ROUTE_RELEASE_PASS SHA=$PINNED_COMMIT"
echo "Authenticated browser/playback and exact Stop still require website acceptance."

