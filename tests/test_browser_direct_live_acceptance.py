"""Offline regression for exact local direct browser acceptance, no paid model/provider."""
import ast
import contextlib
import importlib.util
import io
import json
import re
import ipaddress
import uuid
from pathlib import Path
from urllib.parse import quote_plus, urlsplit

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"scripts/accept-browser-direct-no-model.py"
ROUTE=ROOT/"services/browser-mcp/firbo_browser_route.py"
spec=importlib.util.spec_from_file_location("firbo_direct_acceptance",SCRIPT)
accept=importlib.util.module_from_spec(spec)
spec.loader.exec_module(accept)
SESSION="11111111-1111-4111-8111-111111111111"


def sample_run(model=False, url="https://example.com", title="Example Domain", good=True):
    return {
        "contract":"firbo-browser-execution/v1",
        "provider":"selfhosted-playwright",
        "session_id":SESSION,
        "status":"COMPLETED",
        "execution_verified":good,
        "tool_count":1,
        "failed_count":0,
        "diagnostics":{"mode":"navigation", "model_attempted":model},
        "tools":[{"name":"browser_session_execute","success":True,
                  "output":json.dumps({"ok":True,"page":{"url":url,"title":title}})}]
    }


def test_goal_is_actual_zero_model_direct_path():
    tree=ast.parse(ROUTE.read_text())
    direct=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="_direct_browser_plan")
    scope={"re":re,"ipaddress":ipaddress,"urlsplit":urlsplit,"quote_plus":quote_plus,"Any":object}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[direct],type_ignores=[])),str(ROUTE),"exec"),scope)
    plan=scope["_direct_browser_plan"](accept.GOAL)
    assert plan is not None
    assert plan["complete_on_navigation"] is True
    assert plan["url"]=="https://example.com"
    assert plan["expected_title"]=="Example Domain"


def test_accept_only_verified_direct_tool_receipt():
    assert accept.run_ok(sample_run(),SESSION)
    for value in [
        sample_run(model=True),
        sample_run(url="https://private.example.com"),
        sample_run(title="Wrong"),
        sample_run(good=False),
        dict(sample_run(),tool_count=0),
        dict(sample_run(),diagnostics={"mode":"react","model_attempted":False}),
        dict(sample_run(),tools=[]),
        dict(sample_run(),provider="other"),
        dict(sample_run(),session_id=str(uuid.uuid4())),
    ]:
        assert not accept.run_ok(value,SESSION)


def test_start_frame_and_close_only_exact_contract():
    start={"contract":"firbo-browser-session/v1","provider":"selfhosted-playwright","status":"READY","session_id":SESSION}
    assert accept.start_ok(start)==SESSION
    assert accept.start_ok(dict(start,status="FAILED")) is None
    frame={"contract":"firbo-browser-frame/v1","provider":"selfhosted-playwright",
           "session_id":SESSION,"frame":{"image":{"media_type":"image/jpeg",
           "encoding":"base64","data":"A"*1500}}}
    assert accept.frame_ok(frame,SESSION)
    assert not accept.frame_ok(dict(frame,session_id=str(uuid.uuid4())),SESSION)
    close={"contract":"firbo-browser-close/v1","session_id":SESSION,"status":"CLOSED"}
    assert accept.close_ok(close,SESSION)
    assert not accept.close_ok(dict(close,status="READY"),SESSION)


def test_error_receipts_cannot_claim_unknown_url_or_model():
    out=sample_run()
    out["tools"][0]["output"]='{"ok":true,"page":{"url":"https://secret.example","title":"Example Domain"}}'
    assert not accept.run_ok(out,SESSION)
    assert not accept.run_ok({"diagnostics":{"model_attempted":False}},SESSION)


def test_on_failed_run_cleanup_closes_same_session(monkeypatch):
    called=[]
    monkeypatch.setattr(accept,"read_key",lambda:"fixture-key")
    def fake_post(key,ids,action,**kwargs):
        assert key=="fixture-key"
        called.append((action,dict(kwargs)))
        if action=="start":
            return {"contract":"firbo-browser-session/v1","provider":"selfhosted-playwright",
                    "status":"READY","session_id":SESSION}
        if action=="run":
            return sample_run(good=False)
        if action=="close":
            return {"contract":"firbo-browser-close/v1","session_id":SESSION,"status":"CLOSED"}
        assert False, action
    monkeypatch.setattr(accept,"post",fake_post)
    output=io.StringIO()
    with contextlib.redirect_stdout(output):
        assert accept.main()==1
    assert [name for name,args in called]==["start","run","close"]
    assert called[-1][1]["session_id"]==SESSION
    assert "browser_exact_session_closed=true" in output.getvalue()
    assert "FIRBO_BROWSER_DIRECT_NO_MODEL_E2E_FAIL" in output.getvalue()
    assert "fixture-key" not in output.getvalue()


def test_no_external_provider_url_or_printed_secrets():
    source=SCRIPT.read_text()
    assert 'HTTPConnection(API_HOST, API_PORT' in source
    assert 'API_HOST = "127.0.0.1"' in source
    assert "model_attempted" in source
    assert "http.client.HTTPSConnection" not in source
    assert "print(key)" not in source
    assert "print(data)" not in source
    assert "finally:" in source
