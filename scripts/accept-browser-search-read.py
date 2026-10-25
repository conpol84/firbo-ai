"""One live Wikipedia acceptance run; no credentials or page text printed."""
import http.client
import json
from pathlib import Path
import uuid

GOAL = "Open https://www.wikipedia.org and search for Cyprus, open the Cyprus article and read its first paragraph."
STEPS = {"navigate", "read", "search", "interact", "play"}


def tool_report(tool, index):
    """Count-only evidence for failures and unexpected MCP return shapes."""
    tool = tool if isinstance(tool, dict) else {}
    raw = tool.get("output")
    raw = raw if isinstance(raw, str) else ""
    report = {"tool":index, "success":tool.get("success") is True,
              "output_chars":len(raw), "at_output_limit":len(raw) >= 12000}
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        payload = None
    report["json_object"] = isinstance(payload, dict)
    if not isinstance(payload, dict):
        # Emit only locally defined categories, never the raw exception text.
        report["failure"] = next((code for marker, code in (
            ("[Governance]", "governance_denied"),
            ("Loop guard:", "loop_guard"),
            ("requires confirmation", "confirmation_required"),
            ("timed out after", "tool_timeout"),
            ("MCP tool error:", "mcp_error"),
            ("Tool execution error:", "executor_error"),
            ("Security block:", "security_block"),
        ) if marker in raw), "unclassified")
        return report
    report["payload_ok"] = payload.get("ok") is True
    report["value_present"] = "value" in payload
    value = payload.get("value")
    report["value_type"] = type(value).__name__
    if isinstance(value, str):
        report["value_chars"] = len(value)
    if isinstance(value, dict):
        # Fixed field names only; page-supplied keys and values never printed.
        report["fields"] = {name:{"type":type(value[name]).__name__,
            "length":len(value[name]) if isinstance(value[name], (str,list,dict)) else None}
            for name in ("text","results","items","content","body","paragraph",
                         "firstParagraph","first_paragraph","data","result") if name in value}
        report["other_field_count"] = len(value) - len(report["fields"])
    error = payload.get("error")
    if isinstance(error, dict):
        report["error_name"] = error.get("name") if error.get("name") in (
            "Error","TimeoutError","SyntaxError","ReferenceError","TypeError") else "unknown"
        report["error_kind"] = error.get("kind") if error.get("kind") in (
            "runtime","policy","aborted") else "unknown"
    return report


def main():
    session = None
    verified = closed = False
    try:
        lines = Path("/home/jarvis/.openjarvis/serve.env").read_text().splitlines()
        key = [line.split("=", 1)[1].strip() for line in lines
               if line.startswith("OPENJARVIS_API_KEY=")][-1].strip("\"'")
        if not key:
            raise ValueError()
        ids = {"organization_id":str(uuid.uuid4()), "task_id":str(uuid.uuid4())}

        def post(action, **extra):
            body = dict(ids, action=action, request_id=str(uuid.uuid4()), **extra)
            connection = http.client.HTTPConnection("127.0.0.1", 8765, timeout=120)
            try:
                connection.request("POST", "/v1/firbo/browser", json.dumps(body),
                                   {"Authorization":"Bearer " + key, "Content-Type":"application/json"})
                response = connection.getresponse()
                if response.status != 200:
                    print("FIRBO_BROWSER_HTTP_STATUS", response.status)
                    raise RuntimeError()
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ValueError()
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError()
                return data
            finally:
                connection.close()

        session = str(uuid.UUID(post("start")["session_id"]))
        print("FIRBO_BROWSER_SEARCH_READ_STARTED", flush=True)
        run = post("run", session_id=session, goal=GOAL)
        steps = [s for s in run.get("verified_steps", []) if isinstance(s,str) and s in STEPS]
        missing = [s for s in run.get("missing_steps", []) if isinstance(s,str) and s in STEPS]
        verified = (run.get("contract") == "firbo-browser-execution/v1"
                    and run.get("provider") == "selfhosted-playwright"
                    and run.get("status") == "COMPLETED"
                    and run.get("execution_verified") is True
                    and {"navigate","read","search"}.issubset(steps)
                    and run.get("missing_steps") == [])
        print(json.dumps({"execution_verified":verified, "verified_steps":steps,
                          "missing_steps":missing, "tool_count":len(run.get("tools", []))}))
        diagnostics = run.get("diagnostics") or {}
        print("NATIVE_PROTOCOL", diagnostics.get("agent_protocol") == "function_calling")
        elapsed = diagnostics.get("elapsed_ms")
        print("ELAPSED_MS", min(max(elapsed,0),600000) if type(elapsed) is int else None)
        for index, tool in enumerate(run.get("tools", [])[:32], 1):
            print(json.dumps(tool_report(tool, index), sort_keys=True))
        for index, item in enumerate(diagnostics.get("model_responses", [])[:10], 1):
            reason = item.get("finish_reason")
            safe = {"turn":index, "finish_reason":reason if reason in (
                "stop","length","tool_calls","content_filter","error") else "unknown"}
            for field in ("content_chars","tool_calls","completion_tokens"):
                value = item.get(field)
                safe[field] = min(max(value,0),1000000) if type(value) is int else None
            print(json.dumps(safe))
    except Exception as exc:
        verified = False
        print("FIRBO_BROWSER_ACCEPTANCE_ERROR", type(exc).__name__)
    finally:
        if session:
            try:
                closed = post("close", session_id=session).get("status") == "CLOSED"
                print("FIRBO_BROWSER_SESSION_CLOSED", closed)
            except Exception as exc:
                print("FIRBO_BROWSER_CLOSE_ERROR", type(exc).__name__)
    passed = verified and closed
    print("FIRBO_BROWSER_SEARCH_READ_PASS" if passed else "FIRBO_BROWSER_SEARCH_READ_NOT_VERIFIED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
