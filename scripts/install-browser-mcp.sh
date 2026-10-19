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
IMAGE="firbo-browser-mcp:0.1.0"
WRAPPER="/usr/local/sbin/firbo-browser-mcp"
SUDOERS="/etc/sudoers.d/firbo-browser-mcp"

for required in "$SERVICE_DIR/Dockerfile" "$SERVICE_DIR/package.json" "$SERVICE_DIR/server.mjs" "$CONFIG" "$ENV_FILE"; do
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
ENV_FILE=/home/jarvis/.openjarvis/serve.env
KEY="$(sed -n 's/^BROWSERBASE_API_KEY=//p' "$ENV_FILE" | tail -n1)"
KEY="${KEY%\"}"; KEY="${KEY#\"}"
KEY="${KEY%\'}"; KEY="${KEY#\'}"
[[ -n "$KEY" ]] || { echo "BROWSERBASE_API_KEY missing" >&2; exit 1; }
exec /usr/bin/docker run --rm -i \
  --network bridge \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --memory 512m \
  --cpus 1.0 \
  --pids-limit 128 \
  -e BROWSERBASE_API_KEY="$KEY" \
  -e FIRBO_BROWSER_MAX_SESSIONS=3 \
  firbo-browser-mcp:0.1.0
EOF
chmod 0755 "$WRAPPER"
chown root:root "$WRAPPER"

cat >"$SUDOERS" <<'EOF'
jarvis ALL=(root) NOPASSWD: /usr/local/sbin/firbo-browser-mcp
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

servers = [s for s in servers if isinstance(s, dict) and s.get("name") != "firbo-browser-session"]
servers.append({
    "name": "firbo-browser-session",
    "command": "sudo",
    "args": ["-n", "/usr/local/sbin/firbo-browser-mcp"],
    "include_tools": ["browser_session_execute", "browser_session_close"],
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
    merged = list(dict.fromkeys([*tools_enabled, "browser_session_execute", "browser_session_close"]))
    set_key("tools", "enabled", json.dumps(merged))

set_key("tools.mcp", "enabled", "true")
set_key("tools.mcp", "servers", json.dumps(servers_path.name))

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
if '"id":1' not in out1 or '"id":2' not in out2 or "browser_session_execute" not in out2:
    err = proc.stderr.read()[-2000:]
    raise SystemExit(f"MCP handshake failed\nstdout={out1}\n{out2}\nstderr={err}")
print("FIRBO_BROWSER_MCP_HANDSHAKE_PASS")
PY

echo "=== RESTART OPENJARVIS ==="
systemctl restart openjarvis.service
sleep 3
systemctl is-active --quiet openjarvis.service
echo "OPENJARVIS_ACTIVE"

echo "=== DISCOVERY CHECK ==="
journalctl -u openjarvis.service -n 120 --no-pager | grep -E 'browser_session_execute|firbo-browser-session|MCP' | tail -40 || true

echo "FIRBO_BROWSER_MCP_INSTALL_PASS"
