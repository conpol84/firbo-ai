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
    configurations = []
    def __init__(self, engine, model, **kwargs):
        self.kwargs = kwargs
        self.model = model
        self.configurations.append(kwargs)
        # Reproduce the live gateway's supported-temperature contract.
        if kwargs.get("temperature") != 1:
            raise ValueError("Only the default (1) value is supported")
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
        Agent.configurations = []
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

    def test_agent_uses_supported_temperature_without_switching_model(self):
        status, result, _ = self.invoke("Open https://example.com and read the first paragraph")
        self.assertEqual(status, 200)
        self.assertEqual(Agent.configurations[0]["temperature"], 1)
        self.assertEqual(Agent.invocations[0][0], "test/quality")
        self.assertEqual(result["status"], "FAILED")  # No content-read evidence in this fixture.

    def test_title_only_read_returns_observed_title_without_model(self):
        status, result, tool = self.invoke("Open https://example.com and read the page title", engine=False)
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "COMPLETED")
        self.assertIn("Example Domain", result["result"])
        self.assertEqual(len(tool.calls), 1)
        self.assertEqual(Agent.invocations, [])

    def test_wrong_expected_title_cannot_complete(self):
        status, result, _ = self.invoke("Open https://example.com and verify the page title is Wrong. Finish after verifying the title.")
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(Agent.invocations, [])

    def test_unverified_read_gets_one_continuation_with_real_evidence(self):
        class RecoveringAgent(Agent):
            def run(self, prompt):
                self.invocations.append((self.model,prompt))
                if len(self.invocations)==1:
                    return types.SimpleNamespace(content="Done",tool_results=[],turns=2)
                payload={"ok":True,"page":{"url":"https://example.com","title":"Example Domain"},
                         "value":{"text":"A sufficiently long paragraph extracted from the actual fixture DOM."}}
                tool_result=types.SimpleNamespace(tool_name="browser_session_execute",success=True,content=json.dumps(payload))
                return types.SimpleNamespace(content="Read the paragraph",tool_results=[tool_result],turns=2)
        scope["NativeReActAgent"]=RecoveringAgent
        status,result,_=self.invoke("Open https://example.com and read the first paragraph")
        self.assertEqual(status,200)
        self.assertEqual(result["status"],"COMPLETED")
        self.assertEqual(result["verified_steps"],["navigate","read"])
        self.assertEqual(len(Agent.invocations),2)
        self.assertEqual(Agent.configurations[1]["max_turns"],3)
        self.assertIn("RUNTIME VERIFICATION FEEDBACK",Agent.invocations[1][1])

    def test_continuation_cannot_complete_from_prose_or_loop_indefinitely(self):
        class NoEvidenceAgent(Agent):
            def run(self,prompt):
                self.invocations.append((self.model,prompt))
                return types.SimpleNamespace(content="I read everything",tool_results=[],turns=1)
        scope["NativeReActAgent"]=NoEvidenceAgent
        _,result,_=self.invoke("Open https://example.com and read the first paragraph")
        self.assertEqual(result["status"],"FAILED")
        self.assertEqual(result["missing_steps"],["read"])
        self.assertEqual(len(Agent.invocations),2)

    def test_continuation_respects_remaining_turns_and_approval(self):
        for turns,reply,expected_calls in [(8,"Done",2),(10,"Done",1),
                                         (1,"FIRBO_BROWSER_NEEDS_APPROVAL: login",1),
                                         (1,"Sign in to confirm you are not a bot",1)]:
            with self.subTest(turns=turns,reply=reply):
                self.setUp()
                class BoundedAgent(Agent):
                    def run(self,prompt):
                        self.invocations.append((self.model,prompt))
                        return types.SimpleNamespace(content=reply,tool_results=[],turns=min(turns,self.kwargs["max_turns"]))
                scope["NativeReActAgent"]=BoundedAgent
                _,result,_=self.invoke("Open https://example.com and read the first paragraph")
                self.assertEqual(len(Agent.invocations),expected_calls)
                if expected_calls==2:
                    self.assertEqual(Agent.configurations[1]["max_turns"],2)
                if reply.startswith("FIRBO_BROWSER_NEEDS_APPROVAL"):
                    self.assertEqual(result["status"],"PAUSED")

    def test_youtube_sign_in_boundary_pauses_without_a_model_call(self):
        original=scope["_youtube_verified_result"]
        self.addCleanup(scope.__setitem__,"_youtube_verified_result",original)
        scope["_youtube_verified_result"]=lambda *args: {
            "ok":False,"needs_user_action":True,"error":"youtube_sign_in_required",
            "tools":[],"video_page_verified":True,"playback_verified":False,
            "video_url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ","video_title":"Test"}
        _,result,_=self.invoke("Open YouTube and search for Mazonakis Ores Mikres and play the first video")
        self.assertEqual(result["status"],"PAUSED")
        self.assertFalse(result["playback_verified"])
        self.assertIn("sign-in",result["result"])
        self.assertEqual(Agent.invocations,[])

    def test_recovery_error_preserves_the_incomplete_receipt(self):
        class FailingRecoveryAgent(Agent):
            def run(self,prompt):
                self.invocations.append((self.model,prompt))
                if len(self.invocations)>1:
                    raise RuntimeError("PRIVATE PROVIDER RESPONSE")
                return types.SimpleNamespace(content="Done",tool_results=[],turns=1)
        scope["NativeReActAgent"]=FailingRecoveryAgent
        status,result,_=self.invoke("Open https://example.com and read the first paragraph")
        self.assertEqual(status,200)
        self.assertEqual(result["status"],"FAILED")
        self.assertEqual(result["tool_count"],1)
        self.assertNotIn("PRIVATE",json.dumps(result))

    def test_slow_first_attempt_does_not_start_another_model_run(self):
        class SlowAgent(Agent):
            def run(self,prompt):
                self.invocations.append((self.model,prompt))
                return types.SimpleNamespace(content="Done",tool_results=[],turns=1)
        scope["NativeReActAgent"]=SlowAgent
        old_time=scope["time"]
        clock=iter([0,55,56])
        scope["time"]=types.SimpleNamespace(monotonic=lambda:next(clock))
        self.addCleanup(scope.__setitem__,"time",old_time)
        _,result,_=self.invoke("Open https://example.com and read the first paragraph")
        self.assertEqual(result["status"],"FAILED")
        self.assertEqual(len(Agent.invocations),1)

    def test_stop_during_first_agent_run_prevents_recovery(self):
        request=Request("Open https://example.com and read the first paragraph",Tool())
        class StoppedAgent(Agent):
            def run(self,prompt):
                self.invocations.append((self.model,prompt))
                scope["_mark_browser_session_closed"](request.app,request.body["session_id"])
                return types.SimpleNamespace(content="Done",tool_results=[],turns=1)
        scope["NativeReActAgent"]=StoppedAgent
        status,result=asyncio.run(self.handler(request))
        self.assertEqual(status,200)
        self.assertFalse(result["execution_verified"])
        self.assertEqual(len(Agent.invocations),1)

    def test_close_marks_the_exact_session_before_closing_mcp(self):
        request=Request("unused",Tool())
        request.body["action"]="close"
        class CloseTool:
            spec=types.SimpleNamespace(name="browser_session_close")
            def execute(self,**kwargs):
                self_session=kwargs["session_id"]
                if not scope["_browser_session_was_closed"](request.app,self_session):
                    raise AssertionError("Stop marker missing before MCP close")
                return types.SimpleNamespace(tool_name=self.spec.name,success=True,content=json.dumps({"ok":True,"session_id":self_session}))
        request.app.state.mcp_tools.append(CloseTool())
        status,result=asyncio.run(self.handler(request))
        self.assertEqual(status,200)
        self.assertEqual(result["status"],"CLOSED")
        self.assertFalse(scope["_browser_session_was_closed"](request.app,"22222222-2222-4222-8222-222222222222"))

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
