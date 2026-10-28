"""Pinned, no-auto-upgrade browser site-search release guard contracts."""
import subprocess
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DEPLOY=ROOT/"scripts/deploy-browser-site-search-v1.sh"
ROUTE=ROOT/"services/browser-mcp/firbo_browser_route.py"
PINNED="3c3a7da9b77d49ff81c7d9dec1786852b6d67958"
TARGET="8a0f75a58790345d6973b2409e39e459b7acf6d3962ff94a84a6cf916e88c8ef"

class BrowserSiteReleaseTests(unittest.TestCase):
    def test_bash_syntax_and_exact_source(self):
        script=DEPLOY.read_text()
        self.assertEqual(subprocess.run(["bash","-n",str(DEPLOY)],
            capture_output=True,text=True).returncode,0)
        self.assertIn("PINNED_COMMIT="+PINNED,script)
        self.assertIn("REVIEWED_TARGET_SHA256="+TARGET,script)
        self.assertIn('"$CANDIDATE_SHA" == "$REVIEWED_TARGET_SHA256"',script)
        self.assertIn("test_browser_site_search_read.py",script)
    def test_kernel_and_previous_runtime_are_protected(self):
        script=DEPLOY.read_text()
        for required in [
          "--check","--apply","--owner-confirms-no-active-browser-tasks",
          "FIRBO_BROWSER_AUTH_BOUNDARY_PASS","systemctl is-active --quiet openjarvis.service",
          "FIRBO_BROWSER_PREVIOUS_MODULE_RESTORED",
          "FIRBO_BROWSER_SITE_SEARCH_ROUTE_RELEASE_PASS",
          "FIRBO_BROWSER_KERNEL_VERIFY_PASS",
          "browser kernel firewall isolation is not verified",
          "FIRBO_BROWSER_KERNEL_GUARD_POSTRESTART_FAILED",
          "EXPECTED_INSTALLED_PR40_SHA256","EXPECTED_INSTALLED_PR48_SHA256",
          'cp -p -- "$ROUTE" "$BACKUP"',
          "ROLLBACK_NEEDED=1","rollback_on_error",
          '"$(unauth_status)" == 401',
        ]:
            with self.subTest(required=required):self.assertIn(required,script)
        for unsafe in ["SKIP_SHA","ALLOW_UNKNOWN","curl -k","docker compose down",
                       "supabase db reset","rm -rf /home/jarvis"]:
            self.assertNotIn(unsafe,script)
    def test_site_search_is_bounded_and_no_paid_model_or_second_browser(self):
        source=ROUTE.read_text()
        self.assertIn("site_plan = _site_search_read_plan(goal)",source)
        self.assertIn("_site_search_read_run, execute_tool, session_id, site_plan",source)
        self.assertLess(source.index("site_plan = _site_search_read_plan(goal)"),
                        source.index("direct = _direct_browser_plan(goal)"))
        self.assertIn("if _browser_session_was_closed(request.app, session_id)",source)
        self.assertIn("site = await asyncio.to_thread(",source)

if __name__=="__main__":
    unittest.main()
