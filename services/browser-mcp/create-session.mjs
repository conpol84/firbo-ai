#!/usr/bin/env node

import { browserbase } from "@browserbasehq/stagehand";

const apiKey = String(process.env.BROWSERBASE_API_KEY || "").trim();
delete process.env.BROWSERBASE_API_KEY;
if (!apiKey) {
  process.stderr.write("BROWSERBASE_API_KEY is required\n");
  process.exit(1);
}

let browser;
try {
  browser = await browserbase.launch({
    apiKey,
    keepAlive: true,
    region: "eu-central-1",
  });
  const sessionId = browser.sessionId;
  if (!sessionId) throw new Error("browserbase_session_id_missing");

  // Deliberately DO NOT call Stagehand.create(). The persistent OpenJarvis MCP
  // process owns the first and only Stagehand initialization for this session.
  await browser.close();
  browser = undefined;

  process.stdout.write(JSON.stringify({
    contract: "firbo-browser-session/v1",
    session_id: sessionId,
  }) + "\n");
} catch (error) {
  if (browser) await browser.close().catch(() => undefined);
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(message.slice(0, 1000) + "\n");
  process.exit(1);
}
