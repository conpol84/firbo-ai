"""Offline contract test using the installed OpenJarvis agent and executor.

Run with the existing OpenJarvis venv. No network, credentials or browser is
used. Unlike route stubs, these tests execute the real function-calling loop.
"""
import asyncio
import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from test_browser_route_execution import Request, Router, Tool, scope
from openjarvis.agents.orchestrator import OrchestratorAgent
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

SESSION = "11111111-1111-4111-8111-111111111111"
NAME = "browser_session_execute"


def native_call(code, session=SESSION, name=NAME):
    return {"content":"", "finish_reason":"tool_calls", "tool_calls":[{
        "id":"fixture-call", "name":name,
        "arguments":json.dumps({"session_id":session, "code":code})}],
        "usage":{"completion_tokens":341}}


class FixtureTool(BaseTool):
    def __init__(self):
        self.initial = Tool()
        self.actions = []
        self.on_action = None

    @property
    def spec(self):
        return ToolSpec(name=NAME, description="Read a public fixture page", parameters={
            "type":"object", "properties":{"session_id":{"type":"string"},
            "code":{"type":"string"}}, "required":["session_id","code"]})

    def execute(self, **params):
        code = params["code"]
        if code in ("fixture-search", "fixture-read"):
            self.actions.append(code)
            if self.on_action:
                self.on_action()
            value = ({"results":[{"title":"Cyprus", "url":"https://en.wikipedia.org/wiki/Cyprus"}]}
                     if code == "fixture-search" else
                     {"text":"Cyprus is an island country in the eastern Mediterranean Sea."})
            payload = {"ok":True,"page":{"url":"https://en.wikipedia.org/wiki/Cyprus",
                       "title":"Cyprus - Wikipedia"},"value":value}
            return ToolResult(tool_name=NAME, success=True, content=json.dumps(payload))
        result = self.initial.execute(**params)
        return ToolResult(tool_name=NAME, success=result.success, content=result.content)


class Engine:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []
        self.after_generate = None

    def generate(self, messages, **options):
        self.calls.append((list(messages), options))
        result = next(self.results)
        if self.after_generate:
            self.after_generate()
        return result


class NativeContract(unittest.TestCase):
    def setUp(self):
        scope["OrchestratorAgent"] = OrchestratorAgent
        router = Router()
        scope["install_firbo_browser_route"](router)
        self.handler = router.handler
        self.tool = FixtureTool()

    def run_route(self, engine):
        request = Request("Open https://www.wikipedia.org and search for Cyprus, open the Cyprus article and read its first paragraph.", self.tool)
        request.app.state.engine = engine
        return asyncio.run(self.handler(request))

    def make_agent(self, engine, *, started=None, budget=None):
        self.request = Request("unused", self.tool)
        self.responses = []
        return scope["_make_browser_agent"](
            engine,"test/quality",self.tool,self.request.app,SESSION,10,
            time.monotonic() if started is None else started,self.responses,
            budget if budget is not None else {"models":0,"tools":0})

    def test_native_calls_execute_and_tool_messages_reach_next_turn(self):
        engine = Engine([native_call("fixture-search"), native_call("fixture-read"),
                         {"content":"Read the article", "finish_reason":"stop"}])
        status, result = self.run_route(engine)
        self.assertEqual(status,200)
        self.assertEqual(result["status"],"COMPLETED")
        self.assertEqual(self.tool.actions,["fixture-search","fixture-read"])
        self.assertEqual(result["verified_steps"],["navigate","read","search"])
        for messages, options in engine.calls:
            self.assertEqual(options["model"],"test/quality")
            self.assertEqual(options["temperature"],1)
            self.assertEqual(options["max_tokens"],1800)
            self.assertEqual([x["function"]["name"] for x in options["tools"]],[NAME])
        self.assertTrue(any(str(m.role.value)=="tool" for m in engine.calls[1][0]))
        self.assertEqual(result["diagnostics"]["model_responses"][0]["finish_reason"],"tool_calls")

    def test_plain_prose_cannot_complete_the_task(self):
        engine = Engine([{"content":"I read and searched everything", "finish_reason":"stop"}]*2)
        _, result = self.run_route(engine)
        self.assertEqual(result["status"],"FAILED")
        self.assertEqual(result["missing_steps"],["read","search"])
        self.assertEqual(len(engine.calls),2)
        self.assertEqual(self.tool.actions,[])

    def test_truncated_calls_are_not_executed_or_implicitly_continued(self):
        response = dict(native_call("fixture-read"), finish_reason="length")
        engine = Engine([response]*2)
        _, result = self.run_route(engine)
        self.assertEqual(result["status"],"FAILED")
        self.assertEqual(self.tool.actions,[])
        self.assertEqual(len(engine.calls),2)
        self.assertEqual([r["finish_reason"] for r in result["diagnostics"]["model_responses"]],["length"]*2)

    def test_stop_after_model_reply_prevents_execution(self):
        engine = Engine([native_call("fixture-read")])
        agent = self.make_agent(engine)
        engine.after_generate = lambda: scope["_mark_browser_session_closed"](self.request.app,SESSION)
        agent.run("Read the fixture")
        self.assertEqual(self.tool.actions,[])
        self.assertEqual(len(engine.calls),1)

    def test_stop_between_batched_calls_prevents_later_call(self):
        response = native_call("fixture-search")
        response["tool_calls"] += native_call("fixture-read")["tool_calls"]
        engine = Engine([response])
        agent = self.make_agent(engine)
        self.tool.on_action = lambda: scope["_mark_browser_session_closed"](self.request.app,SESSION)
        agent.run("Read the fixture")
        self.assertEqual(self.tool.actions,["fixture-search"])
        self.assertEqual(len(engine.calls),1)

    def test_wrong_session_and_malformed_arguments_are_rejected(self):
        bad = native_call("fixture-read")
        bad["tool_calls"][0]["arguments"] = "not-json"
        for response in [native_call("fixture-read",session="wrong"),bad,
                         native_call("fixture-read",name="shell_exec")]:
            engine = Engine([response,{"content":"Stopped","finish_reason":"stop"}])
            self.make_agent(engine).run("Read fixture")
            self.assertEqual(self.tool.actions,[])

    def test_approval_with_a_tool_call_never_executes_it(self):
        response = dict(native_call("fixture-read"),content="FIRBO_BROWSER_NEEDS_APPROVAL: sign-in")
        engine = Engine([response])
        _, result = self.run_route(engine)
        self.assertEqual(result["status"],"PAUSED")
        self.assertEqual(len(engine.calls),1)
        self.assertEqual(self.tool.actions,[])

    def test_deadline_and_shared_model_budget_block_new_model_calls(self):
        for started, budget in [(time.monotonic()-71,{"models":0,"tools":0}),
                                (time.monotonic(),{"models":10,"tools":0})]:
            engine = Engine([])
            self.make_agent(engine,started=started,budget=budget).run("Read fixture")
            self.assertEqual(engine.calls,[])

    def test_diagnostics_do_not_include_response_or_arguments(self):
        engine = Engine([{"content":"PRIVATE RESPONSE", "finish_reason":"PRIVATE FINISH",
                          "usage":{"completion_tokens":"PRIVATE USAGE"}}]*2)
        _, result = self.run_route(engine)
        self.assertNotIn("PRIVATE",json.dumps(result["diagnostics"]))


if __name__ == "__main__":
    unittest.main()
