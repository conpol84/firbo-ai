#!/usr/bin/env bash
# FIRBO locked V1: source-pinned, image-only browser MCP private-egress release.
# Operates on EXISTING OpenJarvis + existing root-owned Docker wrappers only.
# No configuration, Caddy, DB, auth secret, model or route module changes.
# --check is read-only; --apply builds, validates, backups exact old image,
# swaps image tag, restarts OpenJarvis, does one NO-MODEL public read/frame/close.
# If any post-swap check fails, roll back the OLD image before exiting.
set -Eeuo pipefail
umask 077
MODE=--check
if [[ $# -gt 0 ]]; then MODE="$1"; fi
PINNED_SOURCE_COMMIT=e43a9739cae043f787646b62177f4e407c523ebd
IMAGE=firbo-browser-mcp:0.2.0
CANDIDATE=firbo-browser-mcp:egress-guard-pr42
WRAPPER=/usr/local/sbin/firbo-browser-mcp
SESSION_WRAPPER=/usr/local/sbin/firbo-browser-session-create
die(){ echo "FIRBO_EGRESS_RELEASE_BLOCKED: $*" >&2; exit 1; }
[[ "$MODE" == --check || "$MODE" == --apply ]] || die "expected --check or --apply"
[[ $(id -u) -eq 0 ]] || die "requires existing VPS root shell"
for command in git python3 docker curl sha256sum systemctl flock tar chmod; do
 command -v "$command" >/dev/null || die "missing required command $command"
done
exec 9>/run/lock/firbo-browser-route-release.lock
flock -n 9 || die "an OpenJarvis/browser release holds the shared lock"
ROOT="$(git -C "$PWD" rev-parse --show-toplevel 2>/dev/null)" || die "cd to pinned firbo-ai checkout"
REMOTE="$(git -C "$ROOT" config --get remote.origin.url || true)"
case "$REMOTE" in
 https://github.com/conpol84/firbo-ai|https://github.com/conpol84/firbo-ai.git|git@github.com:conpol84/firbo-ai|git@github.com:conpol84/firbo-ai.git|ssh://git@github.com/conpol84/firbo-ai|ssh://git@github.com/conpol84/firbo-ai.git) ;;
 *) die "wrong source repository";;
esac
git -C "$ROOT" cat-file -e "$PINNED_SOURCE_COMMIT^{commit}" || die "reviewed PR42 source commit missing"
[[ -f "$WRAPPER" && ! -L "$WRAPPER" && -f "$SESSION_WRAPPER" && ! -L "$SESSION_WRAPPER" ]] || die "existing wrappers missing or symlinked"
grep -Fq 'firbo-browser-mcp:0.2.0' "$WRAPPER" || die "unexpected existing MCP image tag"
grep -Fq 'firbo-browser-mcp:0.2.0' "$SESSION_WRAPPER" || die "unexpected session factory image tag"
systemctl is-active --quiet openjarvis.service || die "OpenJarvis service is not active"
docker image inspect "$IMAGE" >/dev/null || die "original browser image missing"
TMP="$(mktemp -d /tmp/firbo-egress-release.XXXXXXXX)"
cleanup(){ rm -rf -- "$TMP"; }
trap cleanup EXIT
git -C "$ROOT" archive "$PINNED_SOURCE_COMMIT" \
 services/browser-mcp/Dockerfile \
 services/browser-mcp/package.json \
 services/browser-mcp/server.mjs \
 services/browser-mcp/network-policy.mjs \
 services/browser-mcp/create-session.mjs \
 tests/browser-network-policy.test.mjs \
 scripts/accept-browser-direct-read-no-model.py | tar -xf - -C "$TMP"
SRC="$TMP/services/browser-mcp"
grep -q 'installBrowserNetworkPolicy(context)' "$SRC/server.mjs" || die "missing network guard"
grep -q 'serviceWorkers: "block"' "$SRC/server.mjs" || die "missing service worker guard"
grep -q 'COPY server.mjs create-session.mjs network-policy.mjs' "$SRC/Dockerfile" || die "missing image bundling"
# No Node executable or npm install is required on the VPS host. Verify
# the staged public source using the ALREADY installed, isolated browser image
# as a read-only test runtime before touching its image tag.
for folder in "$TMP" "$TMP/services" "$SRC" "$TMP/tests"; do
 chmod 0755 "$folder"
done
docker run --rm --network none --read-only -v "$TMP:/staged:ro" --entrypoint node "$IMAGE" \
 --check /staged/services/browser-mcp/server.mjs || die "reviewed server syntax failed"
docker run --rm --network none --read-only -v "$TMP:/staged:ro" --entrypoint node "$IMAGE" \
 --check /staged/services/browser-mcp/network-policy.mjs || die "reviewed egress syntax failed"
docker run --rm --network none --read-only -v "$TMP:/staged:ro" --entrypoint node "$IMAGE" \
 --test /staged/tests/browser-network-policy.test.mjs >/dev/null || die "source network negative tests failed"
echo FIRBO_BROWSER_EGRESS_SOURCE_TESTS_PASS
unauth_status(){
 curl -sS --max-time 4 -X POST -H 'content-type: application/json' \
 --data '{}' -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/v1/firbo/browser
}
[[ "$(unauth_status)" == 401 ]] || die "existing browser route auth boundary invalid"
echo FIRBO_BROWSER_EGRESS_AUTH_BOUNDARY_PASS
PREVIOUS_ID="$(docker image inspect --format '{{.Id}}' "$IMAGE")"
[[ -n "$PREVIOUS_ID" ]] || die "current image ID unavailable"
TARGET_HASH="$(sha256sum "$SRC/network-policy.mjs" | cut -d' ' -f1)"
ACTUAL_HASH="$(docker run --rm --network none --entrypoint sha256sum "$IMAGE" /app/network-policy.mjs 2>/dev/null | awk '{print $1}' || true)"
echo "FIRBO_BROWSER_EGRESS_CURRENT_IMAGE_ID=$PREVIOUS_ID"
echo "FIRBO_BROWSER_EGRESS_TARGET_POLICY_SHA256=$TARGET_HASH"
if [[ "$ACTUAL_HASH" == "$TARGET_HASH" ]]; then
 echo FIRBO_BROWSER_EGRESS_IMAGE_ALREADY_CURRENT
 exit 0
fi
if [[ "$MODE" == --check ]]; then
 echo FIRBO_BROWSER_EGRESS_UPGRADE_NEEDED
 echo "Dry-run passed; --apply replaces ONLY the reviewed Docker image tag and restarts OpenJarvis with rollback."
 exit 0
fi
# Image build leaves the installed old image/tag and current service untouched.
docker build --pull=false -t "$CANDIDATE" "$SRC" >/dev/null || die "candidate image build failed"
for file in server.mjs network-policy.mjs create-session.mjs package.json; do
 source_hash="$(sha256sum "$SRC/$file" | cut -d' ' -f1)"
 image_hash="$(docker run --rm --network none --entrypoint sha256sum "$CANDIDATE" "/app/$file" | awk '{print $1}')"
 [[ "$source_hash" == "$image_hash" ]] || die "candidate image differs from pinned $file"
done
# Simulated DNS fixtures inside the BUILT isolated image, never a private request.
docker run --rm --network none --entrypoint node "$CANDIDATE" \
 --input-type=module -e '
import {publicBrowserUrl} from "/app/network-policy.mjs";
const pub=async()=>[{address:"1.1.1.1",family:4}];
const priv=async()=>[{address:"169.254.169.254",family:4}];
if(!await publicBrowserUrl("https://example.com/",{resolve:pub}))process.exit(10);
if(await publicBrowserUrl("http://169.254.169.254/",{resolve:pub}))process.exit(11);
if(await publicBrowserUrl("https://rebind.example/",{resolve:priv}))process.exit(12);
console.log("FIRBO_BROWSER_IMAGE_EGRESS_NEGATIVE_PASS");
' || die "image-level network negative acceptance failed"
echo FIRBO_BROWSER_IMAGE_BYTES_PASS
# Retain exact previous content-addressed image under a root-owned backup tag.
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="firbo-browser-mcp:rollback-$STAMP"
docker tag "$IMAGE" "$BACKUP"
[[ "$(docker image inspect --format '{{.Id}}' "$BACKUP")" == "$PREVIOUS_ID" ]] || die "backup image identity mismatch"
echo "FIRBO_BROWSER_IMAGE_ROLLBACK=$BACKUP"
ROLLBACK_NEEDED=1
restore_on_error(){
 status=$?
 trap - ERR
 if [[ "$ROLLBACK_NEEDED" == 1 ]]; then
  echo FIRBO_BROWSER_IMAGE_ROLLBACK_STARTED >&2
  docker tag "$BACKUP" "$IMAGE" || true
  systemctl restart openjarvis.service || true
  echo FIRBO_BROWSER_PREVIOUS_IMAGE_RESTORED >&2
 fi
 exit "$status"
}
trap restore_on_error ERR
[[ "$(docker image inspect --format '{{.Id}}' "$IMAGE")" == "$PREVIOUS_ID" ]] || die "image changed during preflight"
docker tag "$CANDIDATE" "$IMAGE"
systemctl restart openjarvis.service
READY=0
for _ in $(seq 1 25); do
 if systemctl is-active --quiet openjarvis.service \
 && curl -fsS --max-time 2 http://127.0.0.1:8765/health >/dev/null 2>&1 \
 && [[ "$(unauth_status)" == 401 ]]; then
  READY=1
  break
 fi
 sleep 1
done
[[ "$READY" == 1 ]] || { echo FIRBO_BROWSER_IMAGE_POSTRESTART_HEALTH_FAILED >&2; false; }
[[ "$(docker image inspect --format '{{.Id}}' "$IMAGE")" == "$(docker image inspect --format '{{.Id}}' "$CANDIDATE")" ]] \
 || { echo FIRBO_BROWSER_IMAGE_WRONG_TAG >&2; false; }
# The same owner-accepted one-shot public page test: actual Chromium Start,
# real DOM paragraph, JPEG frame and exact Close, with model_attempted=false.
python3 "$TMP/scripts/accept-browser-direct-read-no-model.py"
ROLLBACK_NEEDED=0
trap - ERR
echo FIRBO_BROWSER_EGRESS_IMAGE_RELEASE_PASS
echo "Keep the original rollback image. Real signed-in browser/network-layer egress acceptance remains a separate V1 gate."
