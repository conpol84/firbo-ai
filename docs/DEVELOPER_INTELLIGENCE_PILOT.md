# FIRBO Developer Intelligence — JetBrains + Codebase Memory

**Scope:** one FIRBO CEO, existing task/approval/receipt DB, existing OpenJarvis execution and paired computers. No new server, subscription, model, agent state or Superbrain. **Status: source-only tool discovery; no live IDE/MCP connection yet.**

## Product roles

**FIRBO Superbrain:** Current Supabase tenant-authorized knowledge and local bge-m3 semantic ranking, previously owner-verified bge-m3_ok. Stores approved user/company information and authorized work. Do not silently ingest source code as private user memories.

**Codebase Memory MCP:** https://github.com/DeusData/codebase-memory-mcp is a separate derived local source-code index, pinned by repo and commit. It is an MIT-licensed code intelligence tool without built-in LLM inference. Its local index is disposable, NOT the authority for FIRBO company/user memories. Audit release binaries and side effects before installation.

**JetBrains IDE MCP:** JetBrains 2025.2+ has integrated IDE MCP Server for symbol search, call hierarchy, code inspections and project analysis. Must run on the expressly selected authorized worker where a supported IDE is installed and the project opened. MCP also supports shell/edit: no brave mode, no arbitrary execution or public local port.

**Junie agent/CLI:** Optional, separate from IDE MCP. Can use JetBrains subscription, BYOK or custom/local models, with potential costs. It is NOT a prerequisite for the IDE's bundled MCP Server.

## Implemented SOURCE-ONLY in firbo-ai (NOT deployed)

- services/developer/readonly_mcp_discovery.py processes a bounded existing MCP tools/list JSON response from STDIN locally, **without opening any network connection**.
- JetBrains analysis allowlist: analyze_calls, get_file_problems, get_project_dependencies, search_symbol.
- Codebase Memory structural read allowlist: search_graph, trace_path, list_projects, index_status, check_index_coverage.
- Unknown tools, execute_terminal_command, build_project, index_repository, delete_project, writes/edits and configuration changes are denied. Remote tool descriptions are NOT returned or trusted.
- Even approved tools have execution_enabled=false. The existing FIRBO server-side authenticated MCP + device worker and approval/receipts must authorize each actual call.
- tests/test_developer_mcp_discovery.py exercises malicious catalog descriptions, duplicates, large catalogs, shell/build/index mutation denial. No model calls, IDE installation, cloned repos or production writes.

## Required pilot acceptance — don't skip

1. Select one owner-approved repository, first candidate PUBLIC conpol84/firbo-ai pinned to an exact commit, checked out read-only on healthy explicitly selected Linux worker (Mac only after compatible IDE and fresh heartbeat).
2. Run a reviewed checksum-pinned Codebase Memory release in isolated local user staging with no global auto-install/configuration writes, auto-index watchers or public ports. Never index .env, secrets, private production data or user memory.
3. Open JetBrains IDE with that exact project on a connected device and enable MCP Server only by the owner; expose analysis tools only, "brave mode" OFF.
4. Discover actual MCP tools/list and pass names through strict local gate. Wrong user, repo, commit, path, unsupported name and any write/shell must be denied. Owner/device/job permissions and cost bounds must be checked on backend, not in React.
5. Demonstrate real results: find firbo_browser_route owner code, follow a function call, identify affected tests, cite exact project commit and verify source; benchmark against existing GitHub/file lookup on latency/quality.
6. Integrate selected safe read tools behind existing task/receipt infrastructure and only after Stop PR #157 / provenance RLS second-user tests. No duplicate CEO, memory database, task ledger or server.
7. Owner/Admin UI can later show live connected/readiness state; do not fake healthy if IDE is not connected.

## Cost and deployment policy

Existing JetBrains MCP interface may be bundled in modern IDEs. Junie premium model use and BYOK model inference can cost. Codebase Memory is free-source, but local hardware resources, indexing data access, download provenance and security are still real operational costs. No purchase or background daemon without explicit owner agreement.

**Do not mark complete on source tests.** This is a safe pilot foundation and policy; the actual JetBrains/Codebase Memory connection is PENDING.
