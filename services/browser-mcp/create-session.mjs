#!/usr/bin/env node

import { randomUUID } from "node:crypto";

// Session creation is intentionally provider-free. The persistent FIRBO browser
// MCP lazily creates an isolated Playwright/Chromium context on first use.
const sessionId = randomUUID();

process.stdout.write(JSON.stringify({
  contract: "firbo-browser-session/v1",
  provider: "selfhosted-playwright",
  session_id: sessionId,
  live_view_mode: "snapshot_stream",
}) + "\n");
