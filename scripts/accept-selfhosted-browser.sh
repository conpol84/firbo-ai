#!/usr/bin/env bash
set -e

ENV_FILE=/home/jarvis/.openjarvis/serve.env
BASE=http://127.0.0.1:8765
test -f "$ENV_FILE"

KEY="$(sed -n 's/^OPENJARVIS_API_KEY=//p' "$ENV_FILE" | tail -n1)"
KEY="${KEY%\"}"; KEY="${KEY#\"}"
KEY="${KEY%\'}"; KEY="${KEY#\'}"
test -n "$KEY"

uuid(){ python3 -c 'import uuid; print(uuid.uuid4())'; }
ORG="$(uuid)"
TASK="$(uuid)"
REQ1="$(uuid)"

post(){
  curl -fsS --max-time 120 \
    -X POST "$BASE/v1/firbo/browser" \
    -H "Authorization: Bearer $KEY" \
    -H "Content-Type: application/json" \
    --data "$1"
}

START="$(post "{\"action\":\"start\",\"request_id\":\"$REQ1\",\"organization_id\":\"$ORG\",\"task_id\":\"$TASK\"}")"
SESSION="$(printf '%s' "$START" | python3 -c '
import json,sys
v=json.load(sys.stdin)
assert v.get("contract")=="firbo-browser-session/v1",v
assert v.get("provider")=="selfhosted-playwright",v
print(v["session_id"])
')"
echo "SELFHOSTED_BROWSER_SESSION_START_PASS"

REQ2="$(uuid)"
RUN="$(post "{\"action\":\"run\",\"request_id\":\"$REQ2\",\"organization_id\":\"$ORG\",\"task_id\":\"$TASK\",\"session_id\":\"$SESSION\",\"goal\":\"Navigate to https://example.com and verify the page title is Example Domain. Finish only after browser tool evidence confirms it.\"}")"
printf '%s' "$RUN" | python3 -c '
import json,sys
v=json.load(sys.stdin)
assert v.get("contract")=="firbo-browser-execution/v1",v
assert v.get("provider")=="selfhosted-playwright",v
assert v.get("status")=="COMPLETED",v
assert v.get("execution_verified") is True,v
assert any(t.get("name")=="browser_session_execute" and t.get("success") is True for t in v.get("tools",[])),v
print("SELFHOSTED_BROWSER_EXECUTION_PASS")
'

REQ3="$(uuid)"
FRAME="$(post "{\"action\":\"frame\",\"request_id\":\"$REQ3\",\"organization_id\":\"$ORG\",\"task_id\":\"$TASK\",\"session_id\":\"$SESSION\"}")"
printf '%s' "$FRAME" | python3 -c '
import json,sys
v=json.load(sys.stdin)
assert v.get("contract")=="firbo-browser-frame/v1",v
assert v.get("provider")=="selfhosted-playwright",v
frame=v.get("frame") or {}
img=frame.get("image") or {}
assert img.get("media_type")=="image/jpeg",v
assert img.get("encoding")=="base64",v
assert len(img.get("data") or "")>1000,v
print("SELFHOSTED_BROWSER_FRAME_PASS")
'

REQ4="$(uuid)"
CLOSE="$(post "{\"action\":\"close\",\"request_id\":\"$REQ4\",\"organization_id\":\"$ORG\",\"task_id\":\"$TASK\",\"session_id\":\"$SESSION\"}")"
printf '%s' "$CLOSE" | python3 -c '
import json,sys
v=json.load(sys.stdin)
assert v.get("contract")=="firbo-browser-close/v1",v
assert v.get("status")=="CLOSED",v
print("SELFHOSTED_BROWSER_CLOSE_PASS")
'

echo "FIRBO_SELFHOSTED_BROWSER_ACCEPTANCE_PASS"
