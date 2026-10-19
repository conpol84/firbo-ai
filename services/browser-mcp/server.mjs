#!/usr/bin/env node

import { chromium } from "playwright";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod/v4";

const MAX_CODE_BYTES = 100_000;
const MAX_LOG_BYTES = 64 * 1024;
const MAX_RESULT_BYTES = 256 * 1024;
const MAX_SESSIONS = Math.max(1, Math.min(6, Number(process.env.FIRBO_BROWSER_MAX_SESSIONS || 3)));
const MAX_IDLE_MS = Math.max(60_000, Math.min(60 * 60_000, Number(process.env.FIRBO_BROWSER_IDLE_MS || 20 * 60_000)));
const UUID = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
const BLOCKED_SOURCE =
  /\b(?:process|require|import\s*\(|child_process|node:|globalThis|Function|eval|WebSocket|Bun|Deno)\b/;

const server = new McpServer({ name: "firbo-browser-session", version: "0.2.0" });
const resources = new Map();
let closing = false;

const executeSchema = z.strictObject({
  session_id: z.string().regex(UUID, "session_id must be a FIRBO browser UUID"),
  code: z
    .string()
    .min(1)
    .refine((v) => new TextEncoder().encode(v).byteLength <= MAX_CODE_BYTES, {
      message: `code must be at most ${MAX_CODE_BYTES} UTF-8 bytes`,
    }),
});

const sessionSchema = z.strictObject({
  session_id: z.string().regex(UUID, "session_id must be a FIRBO browser UUID"),
});

server.registerTool(
  "browser_session_execute",
  {
    title: "Execute code in one FIRBO self-hosted browser session",
    description:
      "Execute bounded async JavaScript against the exact self-hosted Playwright session supplied by FIRBO. " +
      "The host, not the model, creates the session. page and context are in scope. " +
      "Do not access credentials, environment variables, local files, MFA, payments, purchases, " +
      "or irreversible submissions without explicit approval.",
    inputSchema: executeSchema,
  },
  async (input, extra) => {
    try {
      const parsed = executeSchema.parse(input);
      if (extra.signal?.aborted) return toolError("aborted", "Browser execution was aborted.");
      if (BLOCKED_SOURCE.test(parsed.code)) {
        return toolError("policy", "Code contains a blocked host-runtime capability.");
      }
      const state = await sessionState(parsed.session_id);
      const result = await enqueue(state, async () => executeCode(state, parsed.code, extra.signal));
      return toolText(result, result.ok !== true);
    } catch (error) {
      return toolError("runtime", safeError(error));
    }
  },
);

server.registerTool(
  "browser_session_snapshot",
  {
    title: "Capture one FIRBO browser Live View frame",
    description:
      "Capture a bounded JPEG screenshot from the exact FIRBO browser session. " +
      "Used only by the authenticated FIRBO control plane for Live View.",
    inputSchema: sessionSchema,
  },
  async (input) => {
    try {
      const { session_id } = sessionSchema.parse(input);
      const state = await sessionState(session_id);
      const result = await enqueue(state, async () => snapshotSession(state));
      return toolText(result, result.ok !== true);
    } catch (error) {
      return toolError("runtime", safeError(error));
    }
  },
);

server.registerTool(
  "browser_session_close",
  {
    title: "Close one FIRBO self-hosted browser session",
    description:
      "Close Chromium and discard all temporary profile/context state for the exact FIRBO session.",
    inputSchema: sessionSchema,
  },
  async (input) => {
    try {
      const { session_id } = sessionSchema.parse(input);
      await closeSession(session_id);
      return toolText({ ok: true, session_id, provider: "selfhosted-playwright" });
    } catch (error) {
      return toolError("runtime", safeError(error));
    }
  },
);

async function pruneIdleSessions() {
  const now = Date.now();
  const stale = [...resources.entries()]
    .filter(([, state]) => now - Number(state.lastUsedAt || state.createdAt || now) > MAX_IDLE_MS)
    .map(([sessionId]) => sessionId);
  await Promise.all(stale.map((sessionId) => closeSession(sessionId).catch(() => undefined)));
}

async function sessionState(sessionId) {
  const existing = resources.get(sessionId);
  if (existing) {
    existing.lastUsedAt = Date.now();
    return existing;
  }

  await pruneIdleSessions();
  if (resources.size >= MAX_SESSIONS) throw new Error("browser_session_capacity_reached");

  const browser = await chromium.launch({
    headless: true,
    args: [
      "--disable-dev-shm-usage",
      "--disable-background-networking",
      "--disable-default-apps",
      "--disable-extensions",
      "--disable-sync",
      "--no-first-run",
      "--no-sandbox",
    ],
  });
  try {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      screen: { width: 1440, height: 900 },
      locale: "en-US",
      colorScheme: "dark",
      ignoreHTTPSErrors: false,
    });
    context.setDefaultTimeout(15_000);
    context.setDefaultNavigationTimeout(25_000);
    const page = await context.newPage();
    const state = {
      browser,
      context,
      page,
      queue: Promise.resolve(),
      createdAt: Date.now(),
      lastUsedAt: Date.now(),
    };
    resources.set(sessionId, state);
    process.stderr.write(
      `firbo_browser_session_ready ${JSON.stringify({ session_id: sessionId, provider: "selfhosted-playwright" })}\n`,
    );
    return state;
  } catch (error) {
    await browser.close().catch(() => undefined);
    throw error;
  }
}

function enqueue(state, operation) {
  state.lastUsedAt = Date.now();
  const next = state.queue.then(operation, operation);
  state.queue = next.then(
    () => undefined,
    () => undefined,
  );
  return next;
}

async function activePage(state) {
  const pages = state.context.pages();
  return pages.find((p) => !p.isClosed()) || state.page || (await state.context.newPage());
}

async function executeCode(state, code, signal) {
  if (signal?.aborted) {
    return { ok: false, error: { kind: "aborted", message: "Browser execution was aborted." } };
  }
  const page = await activePage(state);
  state.page = page;

  const logs = [];
  let logBytes = 0;
  const localConsole = Object.freeze({
    log: (...values) => appendLog("log", values),
    warn: (...values) => appendLog("warn", values),
    error: (...values) => appendLog("error", values),
  });

  function appendLog(level, values) {
    if (logBytes >= MAX_LOG_BYTES) return;
    const raw = values.map(formatValue).join(" ");
    const text = truncateUtf8(raw, MAX_LOG_BYTES - logBytes);
    logBytes += Buffer.byteLength(text);
    if (text) logs.push({ level, text });
  }

  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  const fn = new AsyncFunction(
    "page",
    "context",
    "console",
    "process",
    "require",
    "fetch",
    "globalThis",
    "Function",
    "WebSocket",
    '"use strict";\n' + code,
  );

  try {
    const value = await fn(
      page,
      state.context,
      localConsole,
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
    );
    const current = await activePage(state);
    state.page = current;
    return {
      ok: true,
      provider: "selfhosted-playwright",
      session_id: null,
      page: { url: current.url(), title: await current.title() },
      ...(value === undefined ? {} : { value: jsonSafe(value) }),
      ...(logs.length ? { logs } : {}),
    };
  } catch (error) {
    const current = await activePage(state).catch(() => page);
    return {
      ok: false,
      provider: "selfhosted-playwright",
      page: current ? { url: current.url(), title: await current.title().catch(() => "") } : undefined,
      ...(logs.length ? { logs } : {}),
      error: { kind: "runtime", name: safeName(error), message: safeError(error) },
    };
  }
}

async function snapshotSession(state) {
  const page = await activePage(state);
  state.page = page;
  const jpeg = await page.screenshot({
    type: "jpeg",
    quality: 55,
    fullPage: false,
    animations: "disabled",
    caret: "hide",
    timeout: 10_000,
  });
  return {
    ok: true,
    provider: "selfhosted-playwright",
    captured_at: new Date().toISOString(),
    page: { url: page.url(), title: await page.title().catch(() => "") },
    image: {
      media_type: "image/jpeg",
      encoding: "base64",
      data: jpeg.toString("base64"),
    },
  };
}

async function closeSession(sessionId) {
  const state = resources.get(sessionId);
  if (!state) return;
  resources.delete(sessionId);
  await state.queue.catch(() => undefined);
  await state.context?.close().catch(() => undefined);
  await state.browser?.close().catch(() => undefined);
}

function safeName(error) {
  const name = error instanceof Error ? error.name : "Error";
  return /^[A-Za-z_$][A-Za-z0-9_$.-]{0,99}$/.test(name) ? name : "Error";
}

function safeError(error) {
  const message = error instanceof Error ? error.message : String(error);
  return message
    .replace(/\b(?:authorization|api[_-]?key|password|secret|token)\s*[:=]\s*[^\s,;]+/gi, "$1=[REDACTED]")
    .slice(0, 4000) || "Browser execution failed.";
}

function formatValue(value) {
  if (typeof value === "string") return value;
  try { return JSON.stringify(jsonSafe(value)); } catch { return "[Unserializable value]"; }
}

function jsonSafe(value) {
  if (value === undefined) return undefined;
  const serialized = JSON.stringify(value, (_key, nested) => {
    if (typeof nested === "bigint") return nested.toString();
    if (nested instanceof Uint8Array) {
      return { type: "bytes", encoding: "base64", data: Buffer.from(nested).toString("base64") };
    }
    return nested;
  });
  if (serialized === undefined) return undefined;
  const bytes = Buffer.byteLength(serialized);
  if (bytes <= MAX_RESULT_BYTES) return JSON.parse(serialized);
  return { truncated: true, original_bytes: bytes, preview: truncateUtf8(serialized, MAX_RESULT_BYTES) };
}

function truncateUtf8(value, maxBytes) {
  if (maxBytes <= 0) return "";
  if (Buffer.byteLength(value) <= maxBytes) return value;
  let out = "";
  let bytes = 0;
  for (const char of value) {
    const size = Buffer.byteLength(char);
    if (bytes + size > maxBytes) break;
    out += char;
    bytes += size;
  }
  return out;
}

function toolText(value, isError = false) {
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return { content: [{ type: "text", text }], ...(isError ? { isError: true } : {}) };
}

function toolError(kind, message) {
  return toolText({ ok: false, error: { kind, message } }, true);
}

async function shutdown(code) {
  if (closing) return;
  closing = true;
  const ids = [...resources.keys()];
  await Promise.all(ids.map((id) => closeSession(id).catch(() => undefined)));
  await server.close().catch(() => undefined);
  process.exit(code);
}

process.once("SIGINT", () => void shutdown(130));
process.once("SIGTERM", () => void shutdown(143));
process.stdin.once("end", () => void shutdown(0));
process.stdin.once("close", () => void shutdown(0));

await server.connect(new StdioServerTransport());
process.stderr.write("FIRBO self-hosted Playwright browser MCP listening on stdio\n");
