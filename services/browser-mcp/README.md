# FIRBO exact-session browser MCP

Internal stdio MCP tool for the existing OpenJarvis process.

It **does not create Browserbase sessions**. FIRBO's `cloud-browser` control plane creates
the raw Browserbase session first, persists the exact `task_id -> session_id` binding and
exposes Live View. This MCP then attaches to that exact session and initializes Stagehand
once for the lifetime of the session.

Tools:

- `browser_session_execute(session_id, code)`
- `browser_session_close(session_id)`

Security boundary:

- Run this MCP in its Docker container with no host mounts.
- Pass only `BROWSERBASE_API_KEY` and `FIRBO_BROWSER_MAX_SESSIONS`.
- Do not expose the MCP directly to customers.
- User goals are interpreted by the existing OpenJarvis agent loop; code is bounded and
  common host-runtime capabilities are blocked/shadowed.
- Login credentials, MFA, payments, purchases and irreversible submissions remain approval
  boundaries enforced by the FIRBO browser-executor system prompt/control plane.
