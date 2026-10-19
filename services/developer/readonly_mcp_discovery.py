"""Safe read-only discovery gate for FIRBO Developer/QA MCP pilots.

No MCP call is executed. This module classifies advertised capabilities from a
locally configured JetBrains IDE or codebase-memory-mcp server. Actual execution
must still use the existing authenticated FIRBO task, approval and receipt plane.

Unknown tools, writes, shells, run configurations, and index mutations are OFF.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

SAFE_NAMES: dict[str, frozenset[str]] = {
    "jetbrains": frozenset({
        "analyze_calls",
        "get_file_problems",
        "get_project_dependencies",
        "search_symbol",
    }),
    "codebase-memory": frozenset({
        "search_graph",
        "trace_path",
        "list_projects",
        "index_status",
        "check_index_coverage",
    }),
}
# Explicit deny markers protect against future upstream variations. The
# positive allowlist above is decisive even if names do not match markers.
DANGEROUS = re.compile(
    r"(?:run|execute|terminal|shell|build|rebuild|modify|edit|write|"
    r"delete|remove|replace|create|install|update|index_repository|"
    r"apply|refactor|rename|commit|push|deploy|debug|open_url|browser)",
    re.I,
)
TOOL_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,79}$")
MAX_TOOLS = 250


class InvalidToolList(ValueError):
    pass


def classify_advertised_tools(server: str, response: Any) -> dict[str, Any]:
    """Produce a compact tool-name-only allowlist; never trust remote prose."""
    if server not in SAFE_NAMES:
        raise InvalidToolList("unsupported_server")
    tools = response.get("tools") if isinstance(response, dict) else None
    if not isinstance(tools, list) or len(tools) > MAX_TOOLS:
        raise InvalidToolList("invalid_tool_catalog")
    allowed: list[str] = []
    denied: list[str] = []
    seen: set[str] = set()
    for item in tools:
        if not isinstance(item, dict):
            raise InvalidToolList("invalid_tool_shape")
        name = item.get("name")
        if not isinstance(name, str) or not TOOL_NAME.fullmatch(name):
            raise InvalidToolList("invalid_tool_name")
        if name in seen:
            raise InvalidToolList("duplicate_tool_name")
        seen.add(name)
        if name in SAFE_NAMES[server] and not DANGEROUS.search(name):
            allowed.append(name)
        else:
            denied.append(name)
    return {
        "contract": "firbo-developer-readonly-discovery/v1",
        "server": server,
        "policy": "read_only_pilot",
        "approved_tools": sorted(allowed),
        "denied_tool_count": len(denied),
        # No network URL, prompts, descriptions, paths or secrets returned.
        "execution_enabled": False,
        "requires_owner_approved_repo": True,
        "requires_task_bound_auth_and_receipt": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="FIRBO Developer read-only MCP pilot gate")
    parser.add_argument("--server", choices=sorted(SAFE_NAMES), required=True)
    args = parser.parse_args()
    if sys.stdin.isatty():
        parser.error("pipe a tools/list JSON response on stdin")
    text = sys.stdin.read(256_001)
    if len(text) > 256_000:
        raise InvalidToolList("tool_catalog_too_large")
    payload = json.loads(text)
    result = classify_advertised_tools(args.server, payload)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, json.JSONDecodeError) as exc:
        raise SystemExit("FIRBO_DEVELOPER_PILOT_BLOCKED: " + str(exc)) from None
