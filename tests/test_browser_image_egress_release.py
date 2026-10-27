"""Offline review of the immutable PR42 browser image roll/rollback policy.

No Docker, VPS, browser, provider, network calls or changed user data.
"""
import ast
import re
import subprocess
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"scripts/deploy-browser-egress-guard-image.sh"
POLICY=ROOT/"services/browser-mcp/network-policy.mjs"
SERVER=ROOT/"services/browser-mcp/server.mjs"
DOCKER=ROOT/"services/browser-mcp/Dockerfile"
ACCEPT=ROOT/"scripts/accept-browser-direct-read-no-model.py"
SOURCE_COMMIT="e43a9739cae043f787646b62177f4e407c523ebd"
BASE_IMAGE_SOURCE="f53d632cf49af0c1c483370ecbb038a31489e16d"

class ImageReleaseTests(unittest.TestCase):
    def test_shell_syntax_and_exact_source_pin(self):
        s=SCRIPT.read_text()
        self.assertEqual(subprocess.run(
            ["bash","-n",str(SCRIPT)],capture_output=True,text=True
        ).returncode,0)
        self.assertIn("PINNED_SOURCE_COMMIT="+SOURCE_COMMIT,s)
        self.assertIn('git -C "$ROOT" archive "$PINNED_SOURCE_COMMIT"',s)
        self.assertIn("IMAGE=firbo-browser-mcp:0.2.0",s)
        self.assertIn("MODE=--check",s)
        self.assertIn('--apply',s)
        self.assertNotIn("SKIP_SHA",s)
        self.assertNotIn("ALLOW_UNKNOWN",s)
        self.assertNotIn("git reset --hard",s)
    def test_change_is_image_only_preserving_old_wrappers_and_auth(self):
        s=SCRIPT.read_text()
        self.assertIn("firbo-browser-route-release.lock",s)
        self.assertIn("grep -Fq 'firbo-browser-mcp:0.2.0' \"$WRAPPER\"",s)
        self.assertIn("grep -Fq 'firbo-browser-mcp:0.2.0' \"$SESSION_WRAPPER\"",s)
        self.assertIn("docker build --pull=false",s)
        self.assertIn('docker tag "$IMAGE" "$BACKUP"',s)
        self.assertIn('docker tag "$CANDIDATE" "$IMAGE"',s)
        self.assertIn('docker tag "$BACKUP" "$IMAGE"',s)
        self.assertIn("FIRBO_BROWSER_PREVIOUS_IMAGE_RESTORED",s)
        self.assertIn("FIRBO_BROWSER_IMAGE_POSTRESTART_HEALTH_FAILED",s)
        self.assertIn('[[ "$(unauth_status)" == 401 ]]',s)
        self.assertIn("FIRBO_BROWSER_IMAGE_EGRESS_NEGATIVE_PASS",s)
        self.assertIn("FIRBO_BROWSER_IMAGE_EGRESS_NEGATIVE_PASS",s)
        self.assertIn("accept-browser-direct-read-no-model.py",s)
        self.assertIn("FIRBO_BROWSER_EGRESS_IMAGE_RELEASE_PASS",s)
        for forbidden in ["supabase db","docker system prune","docker compose down",
                          "npm install -g","rm -rf /home/jarvis","ALTER TABLE","DROP DATABASE"]:
            self.assertNotIn(forbidden,s)
    def test_source_image_contains_network_policy_before_live_navigation(self):
        s=SERVER.read_text()
        self.assertIn('installBrowserNetworkPolicy(context)',s)
        self.assertLess(s.index('await installBrowserNetworkPolicy(context)'),s.index('const page = await context.newPage()'))
        self.assertIn('serviceWorkers: "block"',s)
        self.assertIn("network-policy.mjs",DOCKER.read_text())
        policy=POLICY.read_text()
        self.assertIn("const api=context.request",policy)
        self.assertIn("context.routeWebSocket('**/*'",policy)
        self.assertIn("context.route('**/*'",policy)
        self.assertIn("globallyRoutableAddress",policy)
        self.assertTrue(ACCEPT.exists())
    def test_no_unreviewed_npm_or_external_base_image_pull(self):
        text=SCRIPT.read_text()
        self.assertIn("PINNED_EXISTING_IMAGE_SOURCE="+BASE_IMAGE_SOURCE,text)
        self.assertIn('git -C "$ROOT" archive "$PINNED_EXISTING_IMAGE_SOURCE"',text)
        self.assertIn("FIRBO_BROWSER_INSTALLED_IMAGE_PROVENANCE_PASS",text)
        self.assertIn("FIRBO_BROWSER_EGRESS_NO_NEW_DEPENDENCIES_PASS",text)
        self.assertIn('docker build --pull=false --network none',text)
        self.assertIn("FROM firbo-browser-mcp:0.2.0",text)
        self.assertIn("COPY --chown=pwuser:pwuser server.mjs network-policy.mjs /app/",text)
        self.assertIn('for file in server.mjs create-session.mjs package.json; do',text)
        self.assertIn('for file in create-session.mjs package.json; do',text)
        self.assertNotIn('docker build --pull=false -t "$CANDIDATE" "$SRC"',text)
        # The reviewed PR42 Dockerfile STILL has npm install (historical
        # source), but this installer must NEVER execute it.
        self.assertNotIn(' -f "$SRC/Dockerfile"',text)
        self.assertNotIn('docker build --pull -',text)
        self.assertNotIn('npm ci',text)
        self.assertNotIn('npm install --omit=dev',text)
        # Final root-owned service and preserved backup remain mandatory.
        self.assertIn('docker tag "$IMAGE" "$BACKUP"',text)
        self.assertIn('docker tag "$BACKUP" "$IMAGE"',text)
        self.assertIn('python3 "$TMP/scripts/accept-browser-direct-read-no-model.py"',text)

    def test_no_reconfiguration_second_server_or_paid_provider(self):
        s=SCRIPT.read_text()
        for forbidden in ["Caddyfile","supabase/functions","ollama pull",
                          "npm install -g","OPENAI_API_KEY","OMNIROUTE_API_KEY",
                          "kubectl", "docker network create"]:
            self.assertNotIn(forbidden,s)

if __name__=="__main__":
    unittest.main()
