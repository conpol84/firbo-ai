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


if __name__ == "__main__":
    unittest.main()
