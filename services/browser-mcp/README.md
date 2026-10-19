# FIRBO self-hosted Playwright browser MCP

Internal stdio MCP tool for the existing OpenJarvis process.

Primary browser execution is provider-free and runs Chromium on the existing FIRBO VPS.
Browserbase is not required for normal subscriber browser work.

The control plane keeps the existing FIRBO contracts:

- `browser_session_execute(session_id, code)`
- `browser_session_snapshot(session_id)`
- `browser_session_close(session_id)`

Session lifecycle:

1. FIRBO creates a provider-free UUID via `create-session.mjs`.
2. The persistent OpenJarvis MCP lazily creates an isolated Playwright Chromium browser/context.
3. The restricted browser agent executes only through `browser_session_execute`.
4. FIRBO Live View reads bounded JPEG frames through `browser_session_snapshot`.
5. Stop/terminal completion calls `browser_session_close`, which destroys the temporary context/browser.

Security boundary:

- Run the MCP in its Docker container with no host mounts.
- The container receives no Browserbase/API provider secret.
- Customers never call the MCP directly; only the authenticated OpenJarvis browser route does.
- User goals are interpreted by the existing restricted browser-agent loop.
- Code is bounded and common host-runtime capabilities are blocked/shadowed.
- Browser contexts are temporary and not persisted after close.
- Login credentials, MFA, payments, purchases, publishing/submission and irreversible actions remain approval boundaries.
- Snapshot Live View avoids exposing VNC/RDP ports to the public internet.

This is still a staged security boundary: Chromium is container-isolated and runs without host mounts, but final production acceptance must include browser escape/network/tenant isolation checks.
