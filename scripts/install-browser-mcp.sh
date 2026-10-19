#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Run as root: sudo bash scripts/install-browser-mcp.sh" >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_DIR="$ROOT_DIR/services/browser-mcp"
CONFIG="/home/jarvis/.openjarvis/config.toml"
MCP_JSON="/home/jarvis/.openjarvis/mcp-servers.json"
ENV_FILE="/home/jarvis/.openjarvis/serve.env"
IMAGE="firbo-browser-mcp:0.2.0"
WRAPPER="/usr/local/sbin/firbo-browser-mcp"
SESSION_WRAPPER="/usr/local/sbin/firbo-browser-session-create"
SUDOERS="/etc/sudoers.d/firbo-browser-mcp"

for required in "$SERVICE_DIR/Dockerfile" "$SERVICE_DIR/package.json" "$SERVICE_DIR/server.mjs" "$SERVICE_DIR/create-session.mjs" "$SERVICE_DIR/firbo_browser_route.py" "$CONFIG" "$ENV_FILE"; do
  [[ -f "$required" ]] || { echo "Missing required file: $required" >&2; exit 1; }
done
command -v docker >/dev/null || { echo "docker is required" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }

echo "=== BUILD FIRBO BROWSER MCP IMAGE ==="
docker build --pull=false -t "$IMAGE" "$SERVICE_DIR"

echo "=== INSTALL ROOT-OWNED CONTAINER WRAPPER ==="
cat >"$WRAPPER" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
exec /usr/bin/docker run --rm -i \
  --network bridge \
  --read-only \
  --tmpfs /tmp:rw,nosuid,size=1024m \
  --tmpfs /home/pwuser/.cache:rw,nosuid,size=256m \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --memory 1536m \
  --cpus 1.5 \
  --pids-limit 256 \
  --shm-size 768m \
  -e FIRBO_BROWSER_MAX_SESSIONS=3 \
  -e FIRBO_BROWSER_IDLE_MS=1200000 \
  firbo-browser-mcp:0.2.0
EOF
chmod 0755 "$WRAPPER"
chown root:root "$WRAPPER"

cat >"$SESSION_WRAPPER" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
exec /usr/bin/docker run --rm \
  --network none \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=32m \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --memory 128m \
  --cpus 0.25 \
  --pids-limit 32 \
  --entrypoint node \
  firbo-browser-mcp:0.2.0 /app/create-session.mjs
EOF
chmod 0755 "$SESSION_WRAPPER"
chown root:root "$SESSION_WRAPPER"

cat >"$SUDOERS" <<'EOF'
jarvis ALL=(root) NOPASSWD: /usr/local/sbin/firbo-browser-mcp
jarvis ALL=(root) NOPASSWD: /usr/local/sbin/firbo-browser-session-create
EOF
chmod 0440 "$SUDOERS"
visudo -cf "$SUDOERS"

echo "=== MERGE MCP CONFIG SAFELY ==="
python3 - "$CONFIG" "$MCP_JSON" <<'PY'
import json, pathlib, re, sys, tomllib

config_path = pathlib.Path(sys.argv[1])
servers_path = pathlib.Path(sys.argv[2])
raw = config_path.read_text()
parsed = tomllib.loads(raw)

mcp = parsed.get("tools", {}).get("mcp", {})
value = mcp.get("servers", "")
servers = []
if isinstance(value, str) and value.strip():
    text = value.strip()
    if text.startswith("["):
        servers = json.loads(text)
    else:
        path = pathlib.Path(text).expanduser()
        if not path.is_absolute():
            path = config_path.parent / path
        if path.exists():
            data = json.loads(path.read_text())
            servers = data if isinstance(data, list) else [data]

if not isinstance(servers, list):
    raise SystemExit("Existing MCP servers config is not a list")

# Remove superseded Stagehand hosts. "firbo-stagehand" was the old raw
# code_execute server and can delay startup or expose an unsafe generic code tool.
servers = [
    s for s in servers
    if isinstance(s, dict)
    and s.get("name") not in {"firbo-browser-session", "firbo-stagehand"}
]
servers.append({
    "name": "firbo-browser-session",
    "command": "sudo",
    "args": ["-n", "/usr/local/sbin/firbo-browser-mcp"],
    "include_tools": ["browser_session_execute", "browser_session_snapshot", "browser_session_close"],
})
servers_path.write_text(json.dumps(servers, indent=2) + "\n")

lines = raw.splitlines()
sections = {}
current = None
for idx, line in enumerate(lines):
    m = re.match(r"^\s*\[([^]]+)\]\s*$", line)
    if m:
        current = m.group(1).strip()
        sections.setdefault(current, []).append(idx)

def bounds(section):
    starts = sections.get(section, [])
    if not starts:
        return None
    start = starts[0]
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^\s*\[[^]]+\]\s*$", lines[i]):
            end = i
            break
    return start, end

def set_key(section, key, rendered):
    global lines
    b = bounds(section)
    if b is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([f"[{section}]", f"{key} = {rendered}"])
        rebuild_sections()
        return
    start, end = b
    pat = re.compile(rf"^\s*{re.escape(key)}\s*=")
    for i in range(start + 1, end):
        if pat.match(lines[i]):
            lines[i] = f"{key} = {rendered}"
            return
    lines.insert(end, f"{key} = {rendered}")
    rebuild_sections()

def rebuild_sections():
    sections.clear()
    for idx, line in enumerate(lines):
        m = re.match(r"^\s*\[([^]]+)\]\s*$", line)
        if m:
            sections.setdefault(m.group(1).strip(), []).append(idx)

tools_enabled = parsed.get("tools", {}).get("enabled")
if isinstance(tools_enabled, list):
    merged = [name for name in tools_enabled if name != "code_execute"]
    merged = list(dict.fromkeys([*merged, "browser_session_execute", "browser_session_snapshot", "browser_session_close"]))
    set_key("tools", "enabled", json.dumps(merged))

set_key("tools.mcp", "enabled", "true")
# OpenJarvis versions in production reliably accept inline JSON here. Do not
# depend on file-path expansion behavior that changed across releases.
set_key("tools.mcp", "servers", repr(json.dumps(servers, separators=(",", ":"))))

new_raw = "\n".join(lines) + "\n"
tomllib.loads(new_raw)

backup = config_path.with_suffix(config_path.suffix + ".browser-mcp.bak")
backup.write_text(raw)
config_path.write_text(new_raw)
PY

chown jarvis:jarvis "$CONFIG" "$MCP_JSON"
chmod 0600 "$MCP_JSON"

echo "=== VERIFY CONTAINER MCP HANDSHAKE ==="
python3 - <<'PY'
import json, subprocess

proc = subprocess.Popen(
    ["sudo", "-u", "jarvis", "sudo", "-n", "/usr/local/sbin/firbo-browser-mcp"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True,
)
messages = [
    {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"firbo-install","version":"1"}}},
    {"jsonrpc":"2.0","method":"notifications/initialized","params":{}},
    {"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}},
]
for msg in messages:
    proc.stdin.write(json.dumps(msg) + "\n")
proc.stdin.flush()
out1 = proc.stdout.readline().strip()
out2 = proc.stdout.readline().strip()
proc.terminate()
try:
    proc.wait(timeout=5)
except subprocess.TimeoutExpired:
    proc.kill()
if '"id":1' not in out1 or '"id":2' not in out2 or "browser_session_execute" not in out2 or "browser_session_snapshot" not in out2:
    err = proc.stderr.read()[-2000:]
    raise SystemExit(f"MCP handshake failed\nstdout={out1}\n{out2}\nstderr={err}")
print("FIRBO_BROWSER_MCP_HANDSHAKE_PASS")
PY

echo "=== INSTALL RESTRICTED FIRBO BROWSER ROUTE ==="
OPENJARVIS_SERVER_DIR="$(
  sudo -u jarvis /home/jarvis/.openjarvis/.venv/bin/python - <<'PY'
import pathlib
import openjarvis.server
print(pathlib.Path(openjarvis.server.__file__).resolve().parent)
PY
)"
ROUTES_FILE="$OPENJARVIS_SERVER_DIR/routes.py"
ROUTE_MODULE="$OPENJARVIS_SERVER_DIR/firbo_browser_route.py"
test -f "$ROUTES_FILE"

cp "$SERVICE_DIR/firbo_browser_route.py" "$ROUTE_MODULE"
chown jarvis:jarvis "$ROUTE_MODULE"
chmod 0644 "$ROUTE_MODULE"

python3 - "$ROUTES_FILE" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
raw = path.read_text()
hook = """# FIRBO_BROWSER_ROUTE_V1
from openjarvis.server.firbo_browser_route import install_firbo_browser_route
install_firbo_browser_route(router)
"""
if "FIRBO_BROWSER_ROUTE_V1" not in raw:
    marker = '__all__ = ["router"]'
    if marker not in raw:
        raise SystemExit("OpenJarvis routes.py registration marker not found")
    backup = path.with_suffix(path.suffix + ".firbo-browser.bak")
    backup.write_text(raw)
    raw = raw.replace(marker, hook + "\n" + marker, 1)
    path.write_text(raw)
PY

chown jarvis:jarvis "$ROUTES_FILE"
sudo -u jarvis /home/jarvis/.openjarvis/.venv/bin/python -m py_compile   "$ROUTE_MODULE" "$ROUTES_FILE"
echo "FIRBO_BROWSER_ROUTE_SOURCE_VALID"

echo "=== VERIFY FIXED SESSION-CREATOR WRAPPER ==="
test -x "$SESSION_WRAPPER"
sudo -u jarvis sudo -n -l "$SESSION_WRAPPER" >/dev/null
echo "FIRBO_BROWSER_SESSION_CREATOR_READY"

echo "=== RESTART OPENJARVIS ==="
systemctl restart openjarvis.service

echo "=== WAIT FOR OPENJARVIS HTTP READY ==="
READY=0
for _ in $(seq 1 30); do
  if curl -fsS --max-time 1 http://127.0.0.1:8765/health >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 1
done
if [[ "$READY" != "1" ]]; then
  echo "OPENJARVIS_HTTP_NOT_READY"
  systemctl status openjarvis.service --no-pager -l || true
  journalctl -u openjarvis.service -n 160 --no-pager || true
  exit 1
fi
systemctl is-active --quiet openjarvis.service
echo "OPENJARVIS_HTTP_READY"

echo "=== DISCOVERY CHECK ==="
journalctl -u openjarvis.service -n 160 --no-pager | grep -E 'browser_session_execute|firbo-browser-session|firbo-stagehand|code_execute|MCP|firbo/browser' | tail -60 || true

echo "=== ROUTE AUTH CHECK ==="
HTTP_CODE="$(curl -sS --max-time 3 -o /tmp/firbo-browser-route-check.json -w '%{http_code}' \
  -X POST http://127.0.0.1:8765/v1/firbo/browser \
  -H 'content-type: application/json' \
  --data '{}' || true)"
test "$HTTP_CODE" = "401"
echo "FIRBO_BROWSER_ROUTE_AUTH_PASS"

echo "FIRBO_SELFHOSTED_BROWSER_MCP_INSTALL_PASS"
