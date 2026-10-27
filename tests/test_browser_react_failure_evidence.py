"""Check safe error classifications without importing paid providers or user sessions."""
from __future__ import annotations
import ast
from pathlib import Path

ROUTE=Path(__file__).parents[1]/"services/browser-mcp/firbo_browser_route.py"
tree=ast.parse(ROUTE.read_text())


def test_no_raw_error_text_in_react_handler():
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="install_firbo_browser_route")
    handler=next(n for n in ast.walk(node) if isinstance(n,ast.ExceptHandler) and n.name=="exc"
                 and any(isinstance(t,ast.Constant) and t.value=="browser_execution_failed" for t in ast.walk(n)))
    source=ast.unparse(handler)
    assert "_safe_browser_failure_class(exc)" in source
    assert "failure_class" in source and "failure_stage" in source
    assert "str(exc)" not in source and "repr(exc)" not in source
    assert "finally" not in source
