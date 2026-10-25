"""One live Wikipedia acceptance run; no credentials or page text printed."""
import http.client
import json
from pathlib import Path
import uuid

GOAL = "Open https://www.wikipedia.org and search for Cyprus, open the Cyprus article and read its first paragraph."
STEPS = {"navigate", "read", "search", "interact", "play"}


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
