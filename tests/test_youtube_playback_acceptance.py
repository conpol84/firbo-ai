"""Exact-input and fail-closed YouTube video playback regression tests.

Pure route helpers are AST-extracted to avoid launching OpenJarvis or Chromium.
These are contract-level tests; VPS browser/audio still needs authenticated E2E.
"""
import ast
import ipaddress
import json
import re
import types
import unicodedata
import unittest
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlsplit

ROUTE = Path(__file__).resolve().parents[1] / "services/browser-mcp/firbo_browser_route.py"
tree = ast.parse(ROUTE.read_text(encoding="utf-8"))
names = {"_latin_title", "_youtube_play_goal", "_pick_youtube_video",
         "_tool_result", "_browser_step", "_youtube_verified_result"}
body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
assert len(body) == len(names)
scope = {"Any": Any, "ipaddress": ipaddress, "re": re, "unicodedata": unicodedata,
         "json": json, "parse_qs": parse_qs, "quote_plus": quote_plus, "urlsplit": urlsplit}
exec(compile(ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])),
             str(ROUTE), "exec"), scope)
plan = scope["_youtube_play_goal"]
pick = scope["_pick_youtube_video"]
run = scope["_youtube_verified_result"]
VIDEO_ID = "dQw4w9WgXcQ"  # Placeholder URL format in a mock; never a claimed recommendation.


class TestYoutubeGoal(unittest.TestCase):
    def test_explicit_user_commands(self):
        for text in [
            "OPEN YOUTUBE AND SEARCH MAZONAKIS ORES MIKRES. Open the video and tell me what you found.",
            "OPEN CLOUD BROWSER NOW. GO TO YOUTUBE AND SEARCH MAZONAKIS ORES MIKRES. Play the video.",
            "Open YouTube and search for Mazonakis Ores Mikres and play the first video",
        ]:
            with self.subTest(text=text):
                out = plan(text)
                self.assertIsNotNone(out)
                self.assertEqual(out["query"].casefold(), "mazonakis ores mikres")
                self.assertEqual(out["search_url"], "https://www.youtube.com/results?search_query=MAZONAKIS+ORES+MIKRES"
                                 if "MAZONAKIS" in text else
                                 "https://www.youtube.com/results?search_query=Mazonakis+Ores+Mikres")

    def test_no_play_request_no_playback(self):
        for text in [
            "OPEN CLOUD BROWSER NOW. GO TO YOUTUBE AND SEARCH MAZONAKIS ORES MIKRES.",
            "Open YouTube and search for NFL highlights",
            "Tell me about YouTube",
            "Go to https://127.0.0.1 and play video",
        ]:
            self.assertIsNone(plan(text), text)

    def test_greek_transliteration_and_exact_title(self):
        self.assertEqual(scope["_latin_title"]("Γιώργος Μαζωνάκης - Ώρες Μικρές"),
                         "giorgos mazonakis ores mikres")
        candidates = [
            {"title": "Unrelated song", "url": "https://www.youtube.com/watch?v="+VIDEO_ID},
            {"title": "Γιώργος Μαζωνάκης - Ώρες Μικρές (Official Video)",
             "url": "https://www.youtube.com/watch?v="+VIDEO_ID, "channel": "Artist"},
        ]
        selected=pick(candidates, "MAZONAKIS ORES MIKRES")
        self.assertIsNotNone(selected)
        self.assertEqual(selected["url"], "https://www.youtube.com/watch?v="+VIDEO_ID)
        self.assertIsNone(pick(candidates[:1], "MAZONAKIS ORES MIKRES"))
        self.assertIsNone(pick([{"title":"MAZONAKIS ORES MIKRES", "url":"https://evil.example/watch?v="+VIDEO_ID}],
                               "MAZONAKIS ORES MIKRES"))


class FakeTool:
    def __init__(self, playing:bool, wrong_page:bool=False):
        self.playing = playing
        self.wrong_page=wrong_page
        self.calls=[]
    def execute(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls)==1:
            payload={"ok": True, "page":{"url":"https://www.youtube.com/results?search_query=MAZONAKIS+ORES+MIKRES","title":"YouTube"}}
        elif len(self.calls)==2:
            payload={"ok":True, "value":[{
                "title":"Γιώργος Μαζωνάκης Ώρες Μικρές (Official Video)",
                "url":"https://www.youtube.com/watch?v="+VIDEO_ID,
                "channel":"Official"
            }]}
        else:
            payload={"ok":True,
                     "page":{"url":"https://www.youtube.com/watch?v="+("aaaaaaaaaaa" if self.wrong_page else VIDEO_ID)},
                     "value":{"before":{"paused":True,"time":3},
                              "after":{"paused":not self.playing,"time":5 if self.playing else 3}}}
        return types.SimpleNamespace(tool_name="browser_session_execute",
                                     success=True,content=json.dumps(payload))


class TestPlaybackReceipt(unittest.TestCase):
    def test_no_completed_receipt_without_real_video_progress(self):
        p=plan("Open YouTube and search for MAZONAKIS ORES MIKRES and play the first video")
        a=FakeTool(playing=True)
        good=run(a, "session",p)
        self.assertTrue(good["ok"])
        self.assertTrue(good["playback_verified"])
        self.assertEqual(good["video_url"], "https://www.youtube.com/watch?v="+VIDEO_ID)
        self.assertEqual(len(a.calls),3)
        b=FakeTool(playing=False)
        bad=run(b,"session",p)
        self.assertFalse(bad["ok"])
        self.assertTrue(bad["video_page_verified"])
        self.assertEqual(bad["error"], "youtube_playback_unverified")
        c=FakeTool(playing=True,wrong_page=True)
        bad_page=run(c,"session",p)
        self.assertFalse(bad_page["ok"])
        self.assertFalse(bad_page["video_page_verified"])
        self.assertIsNone(bad_page["video_url"])


if __name__ == "__main__":
    unittest.main()
