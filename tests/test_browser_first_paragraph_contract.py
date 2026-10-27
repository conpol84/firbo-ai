"""Regression contract: a verified firstParagraph may satisfy read, never search."""
from pathlib import Path
import unittest

SOURCE = (Path(__file__).resolve().parents[1] / "services/browser-mcp/firbo_browser_route.py").read_text()

class BrowserParagraphEvidenceContract(unittest.TestCase):
    def test_observed_paragraph_supported(self):
        self.assertIn('value.get("firstParagraph")', SOURCE)
        self.assertIn('value.get("first_paragraph")', SOURCE)
    def test_only_successful_public_page_observation_counts(self):
        self.assertIn('value.get("ok") is not True', SOURCE)
        self.assertIn('parsed.scheme != "https"', SOURCE)
        self.assertIn('len(extracted.strip())>=30', SOURCE)
    def test_search_requires_independent_evidence(self):
        self.assertIn('len(ob["value"]["results"])>0', SOURCE)
        self.assertIn('completed.add("search")', SOURCE)

if __name__ == "__main__":
    unittest.main()
