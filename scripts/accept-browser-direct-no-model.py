"""One no-paid-model OpenJarvis browser acceptance: Start -> Title -> Frame -> Close.

Runs against the EXISTING localhost-only authenticated API on owner's VPS.
Do not use this for multi-step/YouTube/paid-LLM acceptance.
No private page text, image bytes, URLs with credentials, or secrets are printed.
"""
from __future__ import annotations

import http.client
import json
import uuid
from pathlib import Path
from urllib.parse import urlsplit

API_HOST = "127.0.0.1"
API_PORT = 8765
KEY_FILE = Path("/home/jarvis/.openjarvis/serve.env")
GOAL = "Open https://example.com and verify the page title is Example Domain. Finish after verifying the title."
PROVIDER = "selfhosted-playwright"


def read_key(path=KEY_FILE):
    """Read the existing auth key locally. Never print key or file content."""
    try:
        items = [line.split("=", 1)[1].strip().strip("\\\"'") for line in path.read_text().splitlines()
                 if line.startswith("OPENJARVIS_API_KEY=")]
    except (OSError, UnicodeError) as exc:
        raise RuntimeError("internal_auth_unavailable") from None
    if not items or not items[-1]:
        raise RuntimeError("internal_auth_unavailable")
    return items[-1]


def post(key, ids, action, *, timeout=15, max_bytes=131072, **extra):
    """Loopback-only, response-bounded request; no retries, redirects or logs."""
    body = {**ids, "request_id": str(uuid.uuid4()), "action": action, **extra}
    conn = http.client.HTTPConnection(API_HOST, API_PORT, timeout=timeout)
    try:
        conn.request("POST", "/v1/firbo/browser", json.dumps(body).encode("utf-8"),
                     {"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        res = conn.getresponse()
        data = res.read(max_bytes + 1)
        if res.status != 200:
            raise RuntimeError("browser_http_" + str(res.status))
        if len(data) > max_bytes:
            raise RuntimeError("browser_response_oversized")
        payload = json.loads(data)
        if not isinstance(payload, dict):
            raise RuntimeError("browser_bad_envelope")
        for k in ("request_id", "organization_id", "task_id"):
            if payload.get(k) != body[k]:
                raise RuntimeError("browser_scope_mismatch")
        return payload
    finally:
        conn.close()


def start_ok(out):
    try:
        session = str(uuid.UUID(str(out.get("session_id", ""))))
    except (ValueError, AttributeError, TypeError):
        return None
    if (out.get("contract") == "firbo-browser-session/v1"
            and out.get("provider") == PROVIDER
            and out.get("status") == "READY"):
        return session
    return None


def run_ok(out, session):
    if (out.get("contract") != "firbo-browser-execution/v1"
            or out.get("provider") != PROVIDER or out.get("session_id") != session
            or out.get("status") != "COMPLETED" or out.get("execution_verified") is not True):
        return False
    diag = out.get("diagnostics") or {}
    if (diag.get("mode") != "navigation" or diag.get("model_attempted") is not False
            or out.get("tool_count") != 1 or out.get("failed_count") != 0):
        return False
    tools = out.get("tools")
    if not isinstance(tools, list) or len(tools) != 1:
        return False
    tool = tools[0]
    if not isinstance(tool, dict) or tool.get("name") != "browser_session_execute" or tool.get("success") is not True:
        return False
    try:
        v = json.loads(tool.get("output", ""))
        page = v.get("page")
        url = urlsplit(page.get("url"))
        return (v.get("ok") is True and url.scheme == "https"
                and url.hostname in {"example.com", "www.example.com"}
                and page.get("title") == "Example Domain")
    except (ValueError, AttributeError, TypeError):
        return False


def frame_ok(out, session):
    if (out.get("contract") != "firbo-browser-frame/v1"
            or out.get("provider") != PROVIDER or out.get("session_id") != session):
        return False
    frame = out.get("frame") or {}
    image = frame.get("image") if isinstance(frame, dict) else {}
    if not isinstance(image, dict):
        return False
    return (image.get("media_type") == "image/jpeg"
            and image.get("encoding") == "base64"
            and isinstance(image.get("data"), str) and len(image["data"]) > 1000)


def close_ok(out, session):
    return (out.get("contract") == "firbo-browser-close/v1"
            and out.get("session_id") == session and out.get("status") == "CLOSED")


def main():
    print("FIRBO_BROWSER_DIRECT_NO_MODEL_E2E_V1", flush=True)
    key = ""
    session = None
    passed = False
    closed = False
    ids = {"organization_id": str(uuid.uuid4()), "task_id": str(uuid.uuid4())}
    try:
        key = read_key()
        started = post(key, ids, "start", timeout=40)
        session = start_ok(started)
        print("browser_start_contract_pass=" + str(session is not None).lower(), flush=True)
        if session is None:
            raise RuntimeError("browser_start_contract")
        result = post(key, ids, "run", session_id=session, goal=GOAL, timeout=50)
        passed = run_ok(result, session)
        print("browser_direct_navigation_pass=" + str(passed).lower(), flush=True)
        print("browser_model_attempted=" + str((result.get("diagnostics") or {}).get("model_attempted")).lower(), flush=True)
        if passed:
            frame = post(key, ids, "frame", session_id=session, timeout=25, max_bytes=4_194_304)
            passed = frame_ok(frame, session)
            print("browser_frame_pass=" + str(passed).lower(), flush=True)
    except Exception as exc:
        print("browser_acceptance_error_type=" + type(exc).__name__, flush=True)
    finally:
        if session and key:
            try:
                closed = close_ok(post(key, ids, "close", session_id=session, timeout=25), session)
            except Exception as exc:
                print("browser_close_error_type=" + type(exc).__name__, flush=True)
        print("browser_exact_session_closed=" + str(closed).lower(), flush=True)
    accepted = bool(passed and closed)
    print("FIRBO_BROWSER_DIRECT_NO_MODEL_E2E_PASS" if accepted else "FIRBO_BROWSER_DIRECT_NO_MODEL_E2E_FAIL")
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
