"""General interactive browser agent acceptance (not site- or video-specific).

The pure verifier is AST-extracted to avoid calling any paid model or VPS.
"""
import ast
import json
import re
import unittest
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
TREE=ast.parse((ROOT/"services/browser-mcp/firbo_browser_route.py").read_text())
names={"_browser_goal_requirements","_browser_goal_acceptance"}
selected=[node for node in TREE.body if isinstance(node,ast.FunctionDef) and node.name in names]
assert len(selected)==len(names)
scope={"re":re,"Any":Any,"json":json,"urlsplit":urlsplit,"EXECUTE_TOOL":"browser_session_execute"}
exec(compile(ast.fix_missing_locations(ast.Module(body=selected,type_ignores=[])),str(ROOT), "exec"),scope)
requirements=scope["_browser_goal_requirements"]
accept=scope["_browser_goal_acceptance"]

def observation(url,*,title="Example Page",value=None,success=True):
    output={"ok":True,"page":{"url":url,"title":title}}
    if value is not None: output["value"]=value
    return {"name":"browser_session_execute","success":success,"output":json.dumps(output)}

class GeneralBrowserContractTests(unittest.TestCase):
    def test_navigation_can_finish_a_navigation_only_goal(self):
        self.assertTrue(accept("Open https://example.com",[
            observation("https://example.com")])["execution_verified"])

    def test_search_query_must_be_observed_not_merely_intended(self):
        self.assertFalse(accept("Search on GitHub for FIRBO",[
            observation("https://github.com")])["execution_verified"])
        self.assertTrue(accept("Search on GitHub for FIRBO",[
            observation("https://github.com"),observation("https://github.com/search?q=FIRBO")])["execution_verified"])

    def test_search_and_read_requires_extracted_information(self):
        command="Search Google for weather and read the results"
        not_enough=accept(command,[observation("https://www.google.com/search?q=weather")])
        self.assertFalse(not_enough["execution_verified"])
        self.assertEqual(not_enough["missing_steps"],["read"])
        done=accept(command,[
            observation("https://www.google.com/search?q=weather",
                        value={"results":[{"title":"Result 1","url":"https://example.com"}]})
        ])
        self.assertTrue(done["execution_verified"])

    def test_click_must_observe_state_change(self):
        no_click=accept("Open https://example.com and click first link",[
            observation("https://example.com")])
        self.assertIn("interact",no_click["missing_steps"])
        clicked=accept("Open https://example.com and click first link",[
            observation("https://example.com"),observation("https://example.com/about")])
        self.assertTrue(clicked["execution_verified"])

    def test_video_play_requires_media_clock_not_results_url(self):
        command="Search YouTube for a song and play the video"
        page_only=[observation("https://www.youtube.com/results?search_query=song")]
        self.assertIn("play",accept(command,page_only)["missing_steps"])
        video_state={"before":{"paused":True,"time":4.0},"after":{"paused":False,"time":6.2}}
        done=accept(command,page_only+[
            observation("https://www.youtube.com/watch?v=dQw4w9WgXcQ",value=video_state)
        ])
        self.assertTrue(done["execution_verified"])

    def test_failed_tool_and_about_blank_are_never_evidence(self):
        self.assertFalse(accept("Open website",[
            observation("https://example.com",success=False)
        ])["execution_verified"])
        self.assertFalse(accept("Open website",[
            observation("about:blank")
        ])["execution_verified"])

    def test_generic_non_youtube_multistep(self):
        command="Open Wikipedia, search for Cyprus, click the result and summarize it"
        partial=[observation("https://en.wikipedia.org"),
                 observation("https://en.wikipedia.org/w/index.php?search=Cyprus"),
                 observation("https://en.wikipedia.org/wiki/Cyprus")]
        self.assertEqual(accept(command,partial)["missing_steps"],["read"])
        final=partial+[observation("https://en.wikipedia.org/wiki/Cyprus",
                                  value={"text":"Cyprus is an island country in the eastern Mediterranean Sea."})]
        self.assertTrue(accept(command,final)["execution_verified"])


if __name__=="__main__":
    unittest.main()
