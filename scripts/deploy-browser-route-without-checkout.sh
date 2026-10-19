#!/usr/bin/env bash
# Checkout-free, pinned release of ONE OpenJarvis browser Python module.
# No git checkout, docker build, service install, Caddy, secrets, or DB changes.
set -Eeuo pipefail
umask 077
PIN=e3cb766caf36f2aab868bf6131f4f51f2d8419cf
BASE=https://raw.githubusercontent.com/conpol84/firbo-ai
VENV=/home/jarvis/.openjarvis/.venv/bin/python
MODE=--check
if [[ $# -gt 0 ]]; then MODE="$1"; fi
die() { echo "FIRBO_BROWSER_RELEASE_BLOCKED: $*" >&2; exit 1; }
[[ "$MODE" == --check || "$MODE" == --apply ]] || die "expected --check or --apply"
[[ $(id -u) -eq 0 ]] || die "run as root"
for binary in curl git python3 sudo sha256sum systemctl; do
  command -v "$binary" >/dev/null || die "missing $binary"
done
[[ -x "$VENV" ]] || die "OpenJarvis Python virtualenv missing"
TMP="$(mktemp -d /tmp/firbo-browser-only.XXXXXXXX)"
cleanup() { rm -rf -- "$TMP"; }
trap cleanup EXIT
fetch_exact() {
  path="$1"
  expected="$2"
  target="$TMP/$path"
  mkdir -p "$(dirname "$target")"
  curl --fail --silent --show-error --location --proto '=https' \
    --tlsv1.2 --retry 2 --max-time 30 \
    --output "$target" "$BASE/$PIN/$path" \
    || die "pinned GitHub download failed: $path"
  actual="$(git hash-object "$target")"
  [[ "$actual" == "$expected" ]] || die "source integrity mismatch: $path"
}
fetch_exact services/browser-mcp/firbo_browser_route.py 4713422cccdfb9f0a1a6dfb4220220b9941e6f1a
fetch_exact tests/test_browser_direct_intent.py a6f0f3282ad430f94e40a68e42f357eead77cfb6
fetch_exact tests/test_generic_browser_goal_acceptance.py e6b9e22e3526e46c8f5084fb203b93605b3685f8
fetch_exact tests/test_youtube_playback_acceptance.py bd8fc94a3d0c76306dd2174bc5103e5ae5373f3b
fetch_exact tests/test_browser_aria_observation.py b40d895e1d9495f9ba3dfdad7e7078e21811fcb1
SOURCE="$TMP/services/browser-mcp/firbo_browser_route.py"
grep -q '^def _browser_goal_acceptance(' "$SOURCE" || die "generic browser acceptance absent"
grep -q '^def _browser_accessibility_observation(' "$SOURCE" || die "AI accessibility snapshot missing"
grep -q '^def _youtube_verified_result(' "$SOURCE" || die "playback verifier absent"
grep -q '^def install_firbo_browser_route(' "$SOURCE" || die "route function absent"
python3 -m py_compile "$SOURCE" || die "candidate Python syntax check failed"
(
cd "$TMP"
python3 -m unittest discover -s tests -p test_browser_direct_intent.py -q
python3 -m unittest discover -s tests -p test_generic_browser_goal_acceptance.py -q
python3 -m unittest discover -s tests -p test_youtube_playback_acceptance.py -q
python3 -m unittest discover -s tests -p test_browser_aria_observation.py -q
) || die "candidate browser regression tests failed"
echo "FIRBO_SOURCE_AND_TESTS_PASS"
SERVER_DIR="$(sudo -u jarvis "$VENV" - <<'PY'
import pathlib, openjarvis.server
print(pathlib.Path(openjarvis.server.__file__).resolve().parent)
PY
)" || die "cannot resolve existing OpenJarvis server module"
ROUTE="$SERVER_DIR/firbo_browser_route.py"
REGISTER="$SERVER_DIR/routes.py"
[[ -f "$ROUTE" && ! -L "$ROUTE" ]] || die "installed browser route absent or symlink"
[[ -f "$REGISTER" && ! -L "$REGISTER" ]] || die "OpenJarvis routes.py absent or symlink"
case "$ROUTE" in
 /home/jarvis/.openjarvis/.venv/lib/*/site-packages/openjarvis/server/firbo_browser_route.py) ;;
 *) die "unexpected target: $ROUTE" ;;
esac
grep -q 'FIRBO_BROWSER_ROUTE_V1' "$REGISTER" || die "route registration missing"
grep -q '^def install_firbo_browser_route(' "$ROUTE" || die "current route not owned by FIRBO"
systemctl is-active --quiet openjarvis.service || die "service not active"
route_http() {
  curl --silent --show-error --max-time 5 \
    --output /dev/null --write-out '%{http_code}' \
    --request POST --header 'content-type: application/json' \
    --data '{}' http://127.0.0.1:8765/v1/firbo/browser || true
}
[[ "$(route_http)" == 401 ]] || die "auth-boundary check expected 401"
echo "FIRBO_OPENJARVIS_ROUTE_401_PASS"
CURRENT="$(sha256sum "$ROUTE" | cut -d' ' -f1)"
TARGET="$(sha256sum "$SOURCE" | cut -d' ' -f1)"
echo "CURRENT_ROUTE_SHA256=$CURRENT"
echo "TARGET_ROUTE_SHA256=$TARGET"
[[ "$CURRENT" != "$TARGET" ]] || { echo FIRBO_BROWSER_ALREADY_CURRENT; exit 0; }
if [[ "$MODE" == --check ]]; then
  echo "FIRBO_BROWSER_ROUTE_UPGRADE_NEEDED"
  exit 0
fi
BACKUP_DIR=/var/backups/firbo-browser-route
install -d -o root -g root -m 0700 "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$BACKUP_DIR/firbo_browser_route.$STAMP.$CURRENT.py"
cp -p -- "$ROUTE" "$BACKUP"
echo "FIRBO_ROUTE_BACKUP=$BACKUP"
ROLLBACK=1
restore() {
  rc=$?
  trap - ERR
  if [[ "$ROLLBACK" == 1 ]]; then
    echo "FIRBO_DEPLOY_FAILED_ROLLBACK_START" >&2
    install -o jarvis -g jarvis -m 0644 -- "$BACKUP" "$ROUTE" || true
    systemctl restart openjarvis.service || true
    echo "FIRBO_PREVIOUS_ROUTE_RESTORED" >&2
  fi
  exit "$rc"
}
trap restore ERR
NEXT="$SERVER_DIR/.firbo_browser_route.$STAMP.new"
install -o jarvis -g jarvis -m 0644 -- "$SOURCE" "$NEXT"
sudo -u jarvis "$VENV" -m py_compile "$NEXT"
mv -- "$NEXT" "$ROUTE"
sudo -u jarvis "$VENV" -m py_compile "$ROUTE" "$REGISTER"
systemctl restart openjarvis.service
READY=0
for attempt in $(seq 1 30); do
 if systemctl is-active --quiet openjarvis.service \
   && curl --fail --silent --max-time 2 http://127.0.0.1:8765/health >/dev/null \
   && [[ "$(route_http)" == 401 ]]; then
   READY=1
   break
 fi
 sleep 1
done
[[ "$READY" == 1 ]] || { echo "POST_DEPLOY_HEALTH_FAILED" >&2; false; }
[[ "$(sha256sum "$ROUTE" | cut -d' ' -f1)" == "$TARGET" ]] \
  || { echo "POST_DEPLOY_BYTES_FAILED" >&2; false; }
ROLLBACK=0
trap - ERR
echo "FIRBO_BROWSER_ROUTE_RELEASE_PASS"
echo "SOURCE_COMMIT=$PIN"
echo "NOTE: real browser/playback, Stop and subscriber isolation still require authenticated acceptance."
