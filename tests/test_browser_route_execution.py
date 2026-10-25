"""Exercise the actual route/agent boundary with deterministic tool fixtures.

No server import, network, model call, credential, or production state is used.
This verifies control flow, not authenticated live-browser acceptance.
"""
import ast
import asyncio
import hmac
import ipaddress
import json
import re
import time
import types
import unicodedata
import unittest
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlsplit, parse_qs

ROOT = Path(__file__).resolve().parents[1]
ROUTE = ROOT / "services/browser-mcp/firbo_browser_route.py"
tree = ast.parse(ROUTE.read_text())
definitions = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
scope = dict(Any=Any, asyncio=asyncio, hmac=hmac, ipaddress=ipaddress, json=json,
             re=re, time=time, types=types, unicodedata=unicodedata, quote_plus=quote_plus,
             urlsplit=urlsplit, parse_qs=parse_qs, Request=object, JSONResponse=object,
             UUID_RE=re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$", re.I),
             MAX_BODY=16384, MAX_GOAL=6000, MAX_TURNS=10,
             EXECUTE_TOOL="browser_session_execute", SNAPSHOT_TOOL="browser_session_snapshot",
             CLOSE_TOOL="browser_session_close")
exec(compile(ast.fix_missing_locations(ast.Module(body=definitions, type_ignores=[])), str(ROUTE), "exec"), scope)
scope["_json"] = lambda status, body: (status, body)


class Router:
    def post(self, *args, **kwargs):
        def install(fn):
            self.handler = fn
            return fn
        return install


class Tool:
    spec = types.SimpleNamespace(name="browser_session_execute")
    def __init__(self, failure=None):
        self.calls = []
        self.failure = failure
        self.url = "about:blank"
    def execute(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure:
            payload = {"ok":False,"error":{"name":self.failure,"message":"PRIVATE PAGE URL PASSWORD"}}
        else:
            match = re.search(r'page.goto\(("[^\"]+")', kwargs["code"])
            if match:
                self.url = json.loads(match.group(1))
            payload = {"ok":True,"page":{"url":self.url,"title":"Example Domain"},
                       "value":{"url":self.url,"title":"Example Domain","accessibility":"- link 'More'"}}
        return types.SimpleNamespace(tool_name=self.spec.name, success=not self.failure, content=json.dumps(payload))


class Agent:
    invocations = []
    results = []
    def __init__(self, engine, model, **kwargs):
        self.kwargs = kwargs
        self.model = model
    def run(self, prompt):
        self.invocations.append((self.model, prompt))
        return types.SimpleNamespace(content="Done", tool_results=self.results)


class Request:
    def __init__(self, goal, tool, auth=True, engine=True):
        self.headers = {"content-type":"application/json"}
        self.headers = type("Headers", (dict,), {"getlist":lambda s,k: ["Bearer fixture-token"] if auth else []})(self.headers)
        self.app = types.SimpleNamespace(state=types.SimpleNamespace(
            api_key="fixture-token", model="test/quality", engine=object() if engine else None,
            mcp_tools=[tool], bus=None))
        self.body = {"action":"run", "goal":goal, **{key:"11111111-1111-4111-8111-111111111111"
                    for key in ["request_id","organization_id","task_id","session_id"]}}
    async def stream(self):
        yield json.dumps(self.body).encode()


class BrowserRouteTests(unittest.TestCase):
    def setUp(self):
        Agent.invocations = []
        Agent.results = []
        scope["NativeReActAgent"] = Agent
        router = Router()
        scope["install_firbo_browser_route"](router)
        self.handler = router.handler
    def invoke(self, goal, **kwargs):
        tool = kwargs.pop("tool", Tool())
        status, result = asyncio.run(self.handler(Request(goal, tool, **kwargs)))
        return status, result, tool

    def test_plain_navigation_works_without_an_llm_and_reports_no_model_call(self):
        status, result, tool = self.invoke("Open https://example.com", engine=False)
        self.assertEqual(status,200)
        self.assertEqual(result["status"],"COMPLETED")
        self.assertFalse(result["diagnostics"]["model_attempted"])
        self.assertIsNone(result["diagnostics"]["configured_model"])
        self.assertEqual(Agent.invocations,[])
        self.assertEqual(len(tool.calls),1)

    def test_find_and_greek_read_never_finish_after_opening_a_page(self):
        for goal in ["Open https://example.com and find the release notes",
                     "Open https://example.com και διάβασε την πρώτη παράγραφο"]:
            status, result, _ = self.invoke(goal)
            self.assertEqual(status,200)
            self.assertEqual(result["status"],"FAILED")
            self.assertFalse(result["execution_verified"])
            self.assertTrue(result["missing_steps"])
            self.assertEqual(result["diagnostics"]["mode"],"react")
            self.assertEqual(result["diagnostics"]["configured_model"],"test/quality")
            self.assertIsNone(result["diagnostics"]["reported_model"])
        self.assertEqual(len(Agent.invocations),2)

    def test_tool_failure_retains_a_safe_cause_without_secret_text(self):
        status, result, _ = self.invoke("Open https://example.com", tool=Tool("TimeoutError"))
        self.assertEqual(result["status"],"FAILED")
        self.assertEqual(result["diagnostics"]["tool_failures"],[{"step":1,"code":"timeout"}])
        self.assertNotIn("PRIVATE",json.dumps(result["diagnostics"]))
        self.assertEqual(Agent.invocations,[])

    def test_missing_model_cannot_complete_a_multistep_task(self):
        status, result, _ = self.invoke("Open https://example.com and find release notes",engine=False)
        self.assertEqual(status,503)
        self.assertEqual(result["error"],"browser_executor_unavailable")
        self.assertFalse(result["diagnostics"]["model_attempted"])

    def test_unauthenticated_requests_do_not_run_tools_or_models(self):
        status, result, tool = self.invoke("Open https://example.com",auth=False)
        self.assertEqual(status,401)
        self.assertEqual(tool.calls,[])
        self.assertEqual(Agent.invocations,[])

    def test_diagnostic_payloads_are_bounded_and_malformed_names_safe(self):
        diagnostic = scope["_browser_execution_diagnostics"]
        calls = [{"success":False,"output":json.dumps({"error":{"name":["bad"],"message":"SECRET"}})}]*100
        out = diagnostic("react","https://secret.example",1000000,calls)
        self.assertEqual(len(out["tool_failures"]),32)
        self.assertEqual(out["elapsed_ms"],600000)
        self.assertIsNone(out["configured_model"])
        self.assertNotIn("SECRET",json.dumps(out))

if __name__ == "__main__":
    unittest.main()
