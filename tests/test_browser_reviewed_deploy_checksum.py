"""Offline proof the scoped browser release won't overwrite unknown host files."""
from __future__ import annotations
import hashlib
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/deploy-browser-route-only.sh"
ROUTE = ROOT / "services/browser-mcp/firbo_browser_route.py"
PREVIOUS = "0a87e75af771551049b43ccf5db649560d6d3c828a01f32510f59eb270b24fc3"
REVIEWED_SHA = "e23b5aa1cd6bdaa223cd80283dc3fe6aaa471a666b03255d84d0c337b7e39bbf"
REVIEWED_COMMIT = "c1b006d2d0776598a63eb36c8e69a7ed16a3e5a4"


class ReviewedBrowserDeployTests(unittest.TestCase):
    def test_reviewed_predecessor_is_exactly_recognized(self):
        text = SCRIPT.read_text()
        self.assertIn("EXPECTED_PR36_SHA256=" + PREVIOUS, text)
        self.assertIn('"$CURRENT_SHA" == "$EXPECTED_PR36_SHA256"', text)
        self.assertIn('installed route differs from reviewed baselines', text)
        self.assertNotIn('SKIP_SHA', text)
        self.assertNotIn('ALLOW_UNKNOWN', text)

    def test_historical_pr37_release_is_pinned_and_new_route_not_implicitly_approved(self):
        text = SCRIPT.read_text()
        self.assertIn("REVIEWED_PR37_COMMIT=" + REVIEWED_COMMIT, text)
        self.assertIn("REVIEWED_PR37_ROUTE_SHA256=" + REVIEWED_SHA, text)
        # Preserve the old host release pin: a newer route is NOT automatically
        # eligible for the old script's --apply action.
        self.assertIn('"$PINNED_COMMIT" == "$REVIEWED_PR37_COMMIT"', text)
        self.assertIn('"$CANDIDATE_SHA" == "$REVIEWED_PR37_ROUTE_SHA256"', text)
        self.assertIn('[[ "$CURRENT_SHA" == "$EXPECTED_BASE_SHA256"', text)
        self.assertNotIn("EXPECTED_PR40_SHA256=", text)
        self.assertNotEqual(hashlib.sha256(ROUTE.read_bytes()).hexdigest(), REVIEWED_SHA)
        self.assertIn("def _browser_first_paragraph(", ROUTE.read_text())
        # A future PR40 install requires separately pinned source & host SHA,
        # backup, rollback, dry-run and explicit owner approval.

    def test_preflight_backup_rollback_and_shell_syntax_preserved(self):
        text = SCRIPT.read_text()
        self.assertIn('MODE=--check', text)
        self.assertIn('[[ "$MODE" == --check || "$MODE" == --apply ]]', text)
        self.assertIn('cp -p -- "$ROUTE" "$BACKUP"', text)
        self.assertIn('rollback_on_error', text)
        self.assertIn('FIRBO_BROWSER_PREVIOUS_MODULE_RESTORED', text)
        self.assertNotIn('rm -rf /home/jarvis', text)
        result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
