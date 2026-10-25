"""Acceptance runner privacy, truthful exit status, and exact-session cleanup."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / "scripts/accept-browser-search-read.py"
spec = importlib.util.spec_from_file_location("browser_acceptance", path)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class AcceptanceRunnerTests(unittest.TestCase):
    def exercise(self, *, complete=True, run_http=200, close_http=200):
        secret = "PRIVATE_TEST_SECRET"
        session = "11111111-1111-4111-8111-111111111111"
        actions = []
        class Connection:
            def __init__(self, host, port, timeout):
                assert (host, port, timeout) == ("127.0.0.1",8765,120)
            def request(self, method, endpoint, body, headers):
                assert (method,endpoint) == ("POST","/v1/firbo/browser")
                assert headers["Authorization"] == "Bearer " + secret
                self.body = json.loads(body)
                actions.append(self.body)
            def getresponse(self):
                action = self.body["action"]
                code = run_http if action == "run" else close_http if action == "close" else 200
                payload = ({"session_id":session} if action == "start" else
                           {"status":"CLOSED"} if action == "close" else {
                               "contract":"firbo-browser-execution/v1", "provider":"selfhosted-playwright",
                               "status":"COMPLETED" if complete else "FAILED", "execution_verified":complete,
                               "verified_steps":["navigate","read","search"] if complete else ["navigate"],
                               "missing_steps":[] if complete else ["read","search"],
                               "tools":[{"output":secret}], "result":secret,
                               "diagnostics":{"agent_protocol":"function_calling", "model_responses":[{
                                   "finish_reason":secret,"content":secret,"completion_tokens":secret}]}})
                return type("Response",(),{"status":code,"read":lambda _,limit:json.dumps(payload).encode()[:limit]})()
            def close(self): pass
        output = io.StringIO()
        with patch.object(runner.Path,"read_text",return_value="OPENJARVIS_API_KEY=" + secret), \
                patch.object(runner.http.client,"HTTPConnection",Connection), contextlib.redirect_stdout(output):
            rc = runner.main()
        self.assertNotIn(secret,output.getvalue())
        self.assertEqual([a["action"] for a in actions],["start","run","close"])
        self.assertEqual(actions[-1]["session_id"],session)
        self.assertEqual(actions[-1]["task_id"],actions[0]["task_id"])
        return rc, output.getvalue()

    def test_verified_run_and_close_are_required_for_pass(self):
        rc,out = self.exercise()
        self.assertEqual(rc,0)
        self.assertIn("FIRBO_BROWSER_SEARCH_READ_PASS",out)

    def test_missing_evidence_fails_and_still_closes(self):
        rc,out = self.exercise(complete=False)
        self.assertEqual(rc,1)
        self.assertNotIn("FIRBO_BROWSER_SEARCH_READ_PASS",out)

    def test_http_failure_does_not_leak_body_and_still_closes(self):
        self.assertEqual(self.exercise(run_http=503)[0],1)

    def test_failed_close_cannot_report_acceptance_pass(self):
        self.assertEqual(self.exercise(close_http=503)[0],1)

    def test_tool_shapes_distinguish_missing_and_wrong_named_evidence(self):
        def report(value):
            return runner.tool_report({"success":True,"output":json.dumps(value)},1)
        missing = report({"ok":True,"page":{"title":"Private title"}})
        self.assertFalse(missing["value_present"])
        wrong = report({"ok":True,"value":{"firstParagraph":"Private paragraph"}})
        self.assertEqual(wrong["fields"],{"firstParagraph":{"type":"str","length":17}})
        good = report({"ok":True,"value":{"text":"Extracted paragraph", "results":[{}]}})
        self.assertEqual(good["fields"]["results"]["length"],1)
        self.assertNotIn("Private",json.dumps([missing,wrong,good]))

    def test_errors_emit_only_allowlisted_classes_and_counts(self):
        private = "PRIVATE_URL_TOKEN_AND_PAGE_CONTENT"
        payload = {"ok":False,"error":{"name":"TimeoutError","kind":"runtime","message":private},
                   "page":{"url":private},"value":{private:private,"text":private}}
        report = runner.tool_report({"success":False,"output":json.dumps(payload)},2)
        self.assertEqual(report["error_name"],"TimeoutError")
        self.assertEqual(report["error_kind"],"runtime")
        self.assertEqual(report["other_field_count"],1)
        self.assertNotIn(private,json.dumps(report))
        payload["error"] = {"name":private,"kind":private,"message":private}
        report = runner.tool_report({"output":json.dumps(payload)},2)
        self.assertEqual(report["error_name"],"unknown")
        self.assertEqual(report["error_kind"],"unknown")
        self.assertNotIn(private,json.dumps(report))

    def test_truncation_and_executor_denial_are_distinguishable(self):
        truncated = runner.tool_report({"success":True,"output":"{" + "x"*11999},1)
        self.assertTrue(truncated["at_output_limit"])
        self.assertFalse(truncated["json_object"])
        denial = runner.tool_report({"success":False,"output":"[Governance] PRIVATE"},2)
        self.assertEqual(denial["failure"],"governance_denied")
        self.assertNotIn("PRIVATE",json.dumps(denial))


if __name__ == "__main__":
    unittest.main()
