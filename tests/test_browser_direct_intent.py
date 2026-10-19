"""Regression tests for the existing OpenJarvis browser route's bounded fast path.

Extract only the stdlib planning function; importing the entire OpenJarvis
runtime is unnecessary for these parser/security tests.
"""
from __future__ import annotations

import ast
import ipaddress
import re
import unittest
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlsplit


ROUTE = Path(__file__).resolve().parents[1] / "services/browser-mcp/firbo_browser_route.py"
tree = ast.parse(ROUTE.read_text(encoding="utf-8"))
function = next(
    node for node in tree.body
    if isinstance(node, ast.FunctionDef) and node.name == "_direct_browser_plan"
)
namespace = {
    "Any": Any,
    "ipaddress": ipaddress,
    "re": re,
    "quote_plus": quote_plus,
    "urlsplit": urlsplit,
}
module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
exec(compile(module, str(ROUTE), "exec"), namespace)
plan = namespace["_direct_browser_plan"]


class BrowserIntentTests(unittest.TestCase):
    def test_exact_example_dot_com_acceptance(self):
        output = plan(
            "Navigate to https://example.com and verify the page title is Example Domain. "
            "Finish only after browser tool evidence confirms it."
        )
        self.assertIsNotNone(output)
        self.assertEqual(output["url"], "https://example.com")
        self.assertEqual(output["expected_title"], "Example Domain")
        self.assertTrue(output["complete_on_navigation"])

    def test_youtube_search_without_model_tool_planning(self):
        output = plan("Open YouTube in the cloud browser and search for NFL highlights")
        self.assertIsNotNone(output)
        self.assertEqual(
            output["url"],
            "https://www.youtube.com/results?search_query=NFL+highlights",
        )
        self.assertTrue(output["complete_on_navigation"])

    def test_youtube_more_steps_not_claimed_complete(self):
        output = plan(
            'Open YouTube in the cloud browser and search for NFL highlights and play the first video'
        )
        self.assertIsNotNone(output)
        self.assertFalse(output["complete_on_navigation"])

    def test_natural_search_starts_public_browser_without_a_url(self):
        for command in [
            "Search for Cyprus, open the Cyprus article, read its first paragraph and verify the URL",
            "earch for Cyprus, open the Cyprus article, read its first paragraph and verify the URL",
            "Find Cyprus and read the introduction",
            "Look up Cyprus and summarize the first paragraph",
        ]:
            with self.subTest(command=command):
                output = plan(command)
                self.assertIsNotNone(output)
                self.assertEqual(output["url"], "https://www.google.com/search?q=Cyprus")
                self.assertEqual(output["hostname"], "www.google.com")
                self.assertFalse(output["complete_on_navigation"])

    def test_public_search_is_not_auto_completed_on_navigation(self):
        output = plan("Search for Cyprus")
        self.assertEqual(output["url"], "https://www.google.com/search?q=Cyprus")
        self.assertFalse(output["complete_on_navigation"])

    def test_negative_and_credential_bearing_searches_not_bootstrapped(self):
        for command in [
            "Do not search for Cyprus",
            "Never search for Cyprus",
            "Search for https://169.254.169.254",
            "Search for https://user:password@example.com",
        ]:
            with self.subTest(command=command):
                self.assertIsNone(plan(command))

    def test_no_implicit_browse_from_plain_web_fact(self):
        self.assertIsNone(plan("Tell me today's NFL scores"))

    def test_refuses_private_and_local_endpoints(self):
        for goal in [
            "Navigate to http://example.com",
            "Navigate to https://localhost",
            "Navigate to https://127.0.0.1",
            "Navigate to https://10.2.3.4",
            "Navigate to https://169.254.169.254",
            "Navigate to https://internal.local",
            "Navigate to https://example.com:8443",
            "Do not open https://example.com",
        ]:
            with self.subTest(goal=goal):
                self.assertIsNone(plan(goal))

    def test_followup_click_does_not_count_as_navigation_only(self):
        output = plan("Open https://example.com and click the login button")
        self.assertIsNotNone(output)
        self.assertFalse(output["complete_on_navigation"])


if __name__ == "__main__":
    unittest.main()
