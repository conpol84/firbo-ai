"""FIRBO browser observed site-search/read route — offline, zero model, zero network.

AST-extract only real route functions. Fake MCP receipts are truthfully simulated
for positive and negative cases; no external task/session/provider is created.
"""
import ast
import ipaddress
import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import quote_plus, urlsplit

ROOT=Path(__file__).resolve().parents[1]
ROUTE=ROOT/"services/browser-mcp/firbo_browser_route.py"
tree=ast.parse(ROUTE.read_text(encoding="utf-8"))
names={
    "_tool_result","_direct_browser_plan","_site_search_read_plan",
    "_browser_step","_browser_first_paragraph","_site_browser_receipt",
    "_site_search_submit","_site_open_exact_result","_site_search_read_run",
}
functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
assert len(functions)==len(names)
scope={"Any":Any,"re":re,"json":json,"urlsplit":urlsplit,"quote_plus":quote_plus,
       "ipaddress":ipaddress}
exec(compile(ast.fix_missing_locations(ast.Module(body=functions,type_ignores=[])),
             str(ROUTE),"exec"),scope)
plan=scope["_site_search_read_plan"]
run=scope["_site_search_read_run"]
SESSION="11111111-1111-4111-8111-111111111111"
HOME="https://www.wikipedia.org/"
ARTICLE="https://en.wikipedia.org/wiki/Cyprus"
PARA=("Cyprus is an island country in the eastern Mediterranean Sea. "
      "The content was returned by a verified browser DOM observation.")

def receipt(url,title,value=None,success=True):
    out={"ok":True,"page":{"url":url,"title":title}}
    if value is not None:out["value"]=value
    return SimpleNamespace(tool_name="browser_session_execute",
        success=success,content=json.dumps(out))

class FakeBrowser:
    def __init__(self,mode="article"):
        self.mode=mode
        self.steps=[]
    def execute(self,*,session_id,code):
        assert session_id==SESSION
        self.steps.append(code)
        if "await page.goto" in code:
            return receipt(HOME,"Wikipedia")
        if "const box=page.locator" in code:
            if self.mode=="no_search":
                return receipt(HOME,"Wikipedia",{"submitted":False})
            url=("https://en.wikipedia.org/w/index.php?search=Cyprus"
                 if self.mode=="results" else ARTICLE)
            return receipt(url,"Search results" if self.mode=="results" else "Cyprus - Wikipedia",
                {"submitted":True,"term":"Cyprus","before":HOME,"after":url,
                 "title":"Search results" if self.mode=="results" else "Cyprus - Wikipedia"})
        if "const matches=page.getByRole" in code:
            return receipt(ARTICLE,"Cyprus - Wikipedia",
                {"clicked":self.mode=="results","term":"Cyprus",
                 "before":"https://en.wikipedia.org/w/index.php?search=Cyprus",
                 "after":ARTICLE,"title":"Cyprus - Wikipedia"})
        if "const p=page.locator" in code:
            if self.mode=="no_read":
                return receipt(ARTICLE,"Cyprus - Wikipedia",
                    {"url":ARTICLE,"title":"Cyprus - Wikipedia",
                     "selection":"first_visible_paragraph","text":"short"})
            return receipt(ARTICLE,"Cyprus - Wikipedia",
                {"url":ARTICLE,"title":"Cyprus - Wikipedia",
                 "selection":"first_visible_paragraph","text":PARA})
        raise AssertionError("unexpected browser code")

class SiteSearchReadTests(unittest.TestCase):
    def goal(self):
        return ("Open Cloud Browser. Go to https://www.wikipedia.org, "
                "search for Cyprus, open the article, read the first paragraph "
                "and close the browser session.")
    def test_generic_parser_accepts_owner_instruction(self):
        found=plan(self.goal())
        self.assertEqual(found,{"url":"https://www.wikipedia.org",
                                "hostname":"www.wikipedia.org","query":"Cyprus"})
        self.assertIsNotNone(plan(
            "Visit https://www.example.org, search for release notes, "
            "open the first result, read the first paragraph"))
    def test_native_openjarvis_fixture_cannot_be_intercepted_by_fast_path(self):
        # Exercise actual separately installed OpenJarvis loop, not a direct
        # Search/Read request that correctly requires zero model calls.
        native=ast.parse((ROOT/"scripts/check-browser-native-contract.py").read_text())
        node=next(n.value for n in native.body
                  if isinstance(n,ast.Assign)
                  and any(isinstance(t,ast.Name) and t.id=="REACT_GOAL" for t in n.targets))
        native_goal=ast.literal_eval(node)
        self.assertIsNone(plan(native_goal))
        fallback=scope["_direct_browser_plan"](native_goal)
        self.assertIsNotNone(fallback)
        self.assertFalse(fallback["complete_on_navigation"])

    def test_real_vps_acceptance_goal_selects_no_model_path(self):
        # Use the ACTUAL operator acceptance script's literal goal. A parser
        # fixture with different wording must not green-light a broken release.
        acceptance=ast.parse((ROOT/"scripts/accept-browser-search-read.py").read_text())
        actual=next(n.value for n in acceptance.body if isinstance(n,ast.Assign)
                    and any(isinstance(t,ast.Name) and t.id=="GOAL" for t in n.targets))
        goal=ast.literal_eval(actual)
        selected=plan(goal)
        self.assertIsNotNone(selected,goal)
        self.assertEqual(selected["query"],"Cyprus")
        fake=FakeBrowser()
        result=run(fake,SESSION,selected)
        self.assertTrue(result["execution_verified"])
        self.assertEqual(result["tool_count"],3)

    def test_article_name_must_match_requested_term(self):
        bad="Open https://www.wikipedia.org and search for Cyprus, open the Greece article and read its first paragraph"
        self.assertIsNone(plan(bad))
        good="Open https://www.wikipedia.org and search for Cyprus, open the Cyprus article and read its first paragraph"
        self.assertEqual(plan(good)["query"],"Cyprus")

    def test_no_unsafe_navigation_or_hidden_writes(self):
        for goal in [
            "Open https://127.0.0.1, search for Cyprus, read the first paragraph",
            "Go to https://localhost, search for Cyprus, read the first paragraph",
            "Open https://example.com:8443, search for Cyprus, read the first paragraph",
            "Open https://example.com, search for Cyprus, read the first paragraph and delete a file",
            "Never open https://example.com, search for Cyprus, read the first paragraph",
        ]:
            with self.subTest(goal=goal):self.assertIsNone(plan(goal))
    def test_real_dom_url_transition_and_paragraph_without_any_model(self):
        fake=FakeBrowser()
        result=run(fake,SESSION,plan(self.goal()))
        self.assertEqual(result["status"],"COMPLETED")
        self.assertEqual(result["verified_steps"],["interact","navigate","read","search"])
        self.assertTrue(result["execution_verified"])
        self.assertEqual(result["tool_count"],3)
        self.assertEqual(result["failed_count"],0)
        self.assertIn(PARA,result["result"])
        self.assertTrue(all(session_id not in step for session_id in ["bad-session"] for step in fake.steps))
    def test_search_results_require_exact_observed_link_click(self):
        fake=FakeBrowser("results")
        result=run(fake,SESSION,plan(self.goal()))
        self.assertTrue(result["execution_verified"])
        self.assertEqual(result["tool_count"],4)
    def test_unverified_site_search_must_fail_closed(self):
        fake=FakeBrowser("no_search")
        result=run(fake,SESSION,plan(self.goal()))
        self.assertEqual(result["status"],"FAILED")
        self.assertEqual(result["verified_steps"],["navigate"])
        self.assertIn("search",result["missing_steps"])
        self.assertEqual(result["tool_count"],2)
    def test_unverified_paragraph_does_not_claim_read(self):
        fake=FakeBrowser("no_read")
        result=run(fake,SESSION,plan(self.goal()))
        self.assertFalse(result["execution_verified"])
        self.assertIn("read",result["missing_steps"])
        self.assertNotIn(PARA,result["result"])

if __name__=="__main__":
    unittest.main()
