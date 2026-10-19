#!/usr/bin/env node

import { browserbase, Stagehand } from "@browserbasehq/stagehand";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod/v4";

const MAX_CODE_BYTES = 100_000;
const MAX_LOG_BYTES = 64 * 1024;
const MAX_RESULT_BYTES = 256 * 1024;
const MAX_SESSIONS = Math.max(1, Math.min(8, Number(process.env.FIRBO_BROWSER_MAX_SESSIONS || 3)));
const UUID = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
const BLOCKED_SOURCE =
  /\b(?:process|require|import\s*\(|child_process|node:|globalThis|Function|eval|WebSocket|Bun|Deno)\b/;

const apiKey = String(process.env.BROWSERBASE_API_KEY || "").trim();
delete process.env.BROWSERBASE_API_KEY;
if (!apiKey) {
  process.stderr.write("BROWSERBASE_API_KEY is required\n");
  process.exit(1);
}

const server = new McpServer({ name: "firbo-browser-session", version: "0.1.0" });
const resources = new Map();
let closing = false;

const executeSchema = z.strictObject({
  session_id: z.string().regex(UUID, "session_id must be a Browserbase UUID"),
  code: z
    .string()
    .min(1)
    .refine((v) => new TextEncoder().encode(v).byteLength <= MAX_CODE_BYTES, {
      message: `code must be at most ${MAX_CODE_BYTES} UTF-8 bytes`,
    }),
});

const closeSchema = z.strictObject({
  session_id: z.string().regex(UUID, "session_id must be a Browserbase UUID"),
});

server.registerTool(
  "browser_session_execute",
  {
    title: "Execute code in one FIRBO Browserbase session",
    description:
      "Execute bounded async JavaScript against the exact Browserbase session supplied by FIRBO. " +
      "The host, not the model, creates the session. Use only the provided session_id. " +
      "page and context are in scope. Do not access credentials, environment variables, local files, " +
      "MFA, payments, purchases, or irreversible submissions without explicit approval.",
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
  "browser_session_close",
  {
    title: "Disconnect one FIRBO browser session",
    description:
      "Disconnect the Stagehand handle for the exact FIRBO Browserbase session. " +
      "This does not release the remote Browserbase session; FIRBO cloud-browser owns release.",
    inputSchema: closeSchema,
  },
  async (input) => {
    try {
      const { session_id } = closeSchema.parse(input);
      await closeSession(session_id);
      return toolText({ ok: true, session_id });
    } catch (error) {
      return toolError("runtime", safeError(error));
    }
  },
);

async function sessionState(sessionId) {
  const existing = resources.get(sessionId);
  if (existing) return existing;
  if (resources.size >= MAX_SESSIONS) {
    throw new Error("browser_session_capacity_reached");
  }

  const pending = {
    browser: null,
    stagehand: null,
    queue: Promise.resolve(),
    init: null,
  };
  resources.set(sessionId, pending);
  pending.init = (async () => {
    const browser = await browserbase.connect({ apiKey, sessionId });
    try {
      const stagehand = await Stagehand.create({ browser, logging: { level: "off" } });
      pending.browser = browser;
      pending.stagehand = stagehand;
      process.stderr.write(
        `firbo_browser_session_ready ${JSON.stringify({ session_id: sessionId })}\n`,
      );
      return pending;
    } catch (error) {
      await browser.close().catch(() => undefined);
      resources.delete(sessionId);
      throw error;
    }
  })();
  return await pending.init;
}

function enqueue(state, operation) {
  const next = state.queue.then(operation, operation);
  state.queue = next.then(
    () => undefined,
    () => undefined,
  );
  return next;
}

async function executeCode(state, code, signal) {
  if (signal?.aborted) return { ok: false, error: { kind: "aborted", message: "Browser execution was aborted." } };
  const stagehand = state.stagehand;
  if (!stagehand) throw new Error("browser_session_not_initialized");
  const context = stagehand.browser.context;
  const page =
    (await context.activePage()) ??
    (await context.pages())[0] ??
    (await context.newPage());

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

  // Deliberately shadow common host-runtime capabilities. This MCP still runs
  // inside an isolated container; browser work is the only intended effect.
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
    "eval",
    "WebSocket",
    '"use strict";\n' + code,
  );

  try {
    const value = await fn(
      page,
      context,
      localConsole,
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
    );
    const active = (await context.activePage()) ?? page;
    return {
      ok: true,
      session_id: state.browser?.sessionId ?? null,
      page: { url: await active.url(), title: await active.title() },
      ...(value === undefined ? {} : { value: jsonSafe(value) }),
      ...(logs.length ? { logs } : {}),
    };
  } catch (error) {
    const active = (await context.activePage().catch(() => undefined)) ?? page;
    return {
      ok: false,
      session_id: state.browser?.sessionId ?? null,
      page: active ? { url: await active.url().catch(() => ""), title: await active.title().catch(() => "") } : undefined,
      ...(logs.length ? { logs } : {}),
      error: { kind: "runtime", name: safeName(error), message: safeError(error) },
    };
  }
}

async function closeSession(sessionId) {
  const state = resources.get(sessionId);
  if (!state) return;
  resources.delete(sessionId);
  await state.queue.catch(() => undefined);
  let failed = false;
  if (state.stagehand) await state.stagehand.close().catch(() => { failed = true; });
  if (state.browser) await state.browser.close().catch(() => { failed = true; });
  if (failed) throw new Error("browser_session_disconnect_failed");
}

function safeName(error) {
  const name = error instanceof Error ? error.name : "Error";
  return /^[A-Za-z_$][A-Za-z0-9_$.-]{0,99}$/.test(name) ? name : "Error";
}

function safeError(error) {
  const message = error instanceof Error ? error.message : String(error);
  return message
    .replaceAll(apiKey, "[REDACTED]")
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
process.stderr.write("FIRBO exact-session browser MCP listening on stdio\n");
