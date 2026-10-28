"""Tests for PR40 pinned route release and NO MODEL direct DOM read acceptance.

No SSH, provider calls, browser startup or network is used by these tests.
"""
import hashlib
import importlib.util
import json
import subprocess
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ROUTE=ROOT/"services/browser-mcp/firbo_browser_route.py"
DEPLOY=ROOT/"scripts/deploy-browser-read-v1.sh"
ACCEPT=ROOT/"scripts/accept-browser-direct-read-no-model.py"
EXPECTED_ROUTE="06cb981ab0c7c3fee69fad1fb6dc40822cec62ced7f82faba2aa70880b42f8ba"
# New source-only verifier adjustment; the historical pinned release remains immutable.
EXPECTED_CURRENT_ROUTE="4829c541697be2a04a6acb7fae39f26d95b698aad607cfc91c43ef4993d927e3"
EXPECTED_PREVIOUS="e23b5aa1cd6bdaa223cd80283dc3fe6aaa471a666b03255d84d0c337b7e39bbf"
PINNED="2fa884437a4f46aebf139223475398d9ee2404f2"
spec=importlib.util.spec_from_file_location("firbo_browser_direct_read_acceptance",ACCEPT)
accept=importlib.util.module_from_spec(spec)
spec.loader.exec_module(accept)
SESSION="11111111-1111-4111-8111-111111111111"
PUBLIC_URL="https://example.com"
TEXT=("This domain is intended for illustrative examples in documents. "
      "The paragraph is read from the live fixture DOM, not invented by the model.")

def fake_receipt():
    return {
        "contract":"firbo-browser-execution/v1",
        "provider":"selfhosted-playwright",
        "session_id":SESSION,
        "status":"COMPLETED",
        "execution_verified":True,
        "tool_count":2,"failed_count":0,"tool_observations":2,
        "verified_steps":["navigate","read"],"missing_steps":[],
        "diagnostics":{"mode":"navigation","model_attempted":False},
        "result":"First visible paragraph from Example Domain: "+TEXT,
        "tools":[
          {"name":"browser_session_execute","success":True,
            "output":json.dumps({"ok":True,"page":{"url":PUBLIC_URL,"title":"Example Domain"}})},
          {"name":"browser_session_execute","success":True,
            "output":json.dumps({"ok":True,"page":{"url":PUBLIC_URL,"title":"Example Domain"},
              "value":{"url":PUBLIC_URL,"title":"Example Domain",
                "selection":"first_visible_paragraph","text":TEXT}})}
        ]
    }

class DirectReadReleaseTests(unittest.TestCase):
    def test_real_source_and_pinned_release_integrity(self):
        source=ROUTE.read_bytes()
        self.assertEqual(hashlib.sha256(source).hexdigest(),EXPECTED_CURRENT_ROUTE)
        release=DEPLOY.read_text()
        self.assertIn("PINNED_COMMIT="+PINNED,release)
        self.assertIn("REVIEWED_TARGET_SHA256="+EXPECTED_ROUTE,release)
        self.assertIn("EXPECTED_INSTALLED_PR37_SHA256="+EXPECTED_PREVIOUS,release)
        self.assertIn('"$CANDIDATE_SHA" == "$REVIEWED_TARGET_SHA256"',release)
        self.assertIn('"$CURRENT_SHA" == "$EXPECTED_INSTALLED_PR37_SHA256"',release)
        self.assertNotIn("SKIP_SHA",release)
        self.assertNotIn("ALLOW_UNKNOWN",release)
        self.assertNotIn("curl -k",release)
        self.assertNotIn("rm -rf /home/jarvis",release)
        self.assertEqual(subprocess.run(["bash","-n",str(DEPLOY)],
          capture_output=True,text=True).returncode,0)
    def test_host_release_is_scoped_reversible_and_auth_bound(self):
        s=DEPLOY.read_text()
        for token in ["--check","--apply","firbo-browser-route-release.lock",
                      'cp -p -- "$ROUTE" "$BACKUP"',"rollback_on_error",
                      "FIRBO_BROWSER_PREVIOUS_MODULE_RESTORED",
                      "FIRBO_BROWSER_AUTH_BOUNDARY_PASS",
                      "FIRBO_BROWSER_SOURCE_TESTS_PASS",
                      "FIRBO_BROWSER_NATIVE_TOOL_CONTRACT_PASS",
                      "FIRBO_BROWSER_READ_ROUTE_RELEASE_PASS"]:
            self.assertIn(token,s)
        self.assertIn('"$CODE" == 401',s)
        self.assertIn('git -C "$ROOT" archive "$PINNED_COMMIT"',s)
        self.assertNotIn("supabase db",s)
        self.assertNotIn("docker restart",s)
        self.assertEqual(accept.GOAL,"Open https://example.com and read the first paragraph")
    def test_exact_no_model_read_receipt(self):
        self.assertTrue(accept.run_ok(fake_receipt(),SESSION))
        self.assertEqual(accept.PROVIDER,"selfhosted-playwright")
    def test_reject_forged_or_partial_completions(self):
        for mutate in [
            lambda r:r.update(status="FAILED"),
            lambda r:r.update(tool_count=1),
            lambda r:r.update(execution_verified=False),
            lambda r:r.update(tool_observations=1),
            lambda r:r["diagnostics"].update(model_attempted=True),
            lambda r:r["diagnostics"].update(mode="react"),
            lambda r:r.update(missing_steps=["read"]),
            lambda r:r["tools"][1].update(success=False),
            lambda r:r.update(tools=r["tools"][:1]),
            lambda r:r.update(session_id="22222222-2222-4222-8222-222222222222"),
            lambda r:r.update(result="Unverified browser prose"),
        ]:
            with self.subTest(mutate=str(mutate)):
                receipt=fake_receipt()
                mutate(receipt)
                self.assertFalse(accept.run_ok(receipt,SESSION))
        for key,bad in [("text","short"),("selection","wrong"),("url","https://other.example.com"),
                        ("title","Other Title")]:
            receipt=fake_receipt()
            obs=json.loads(receipt["tools"][1]["output"])
            obs["value"][key]=bad
            receipt["tools"][1]["output"]=json.dumps(obs)
            self.assertFalse(accept.run_ok(receipt,SESSION))

if __name__=="__main__":
    unittest.main()
