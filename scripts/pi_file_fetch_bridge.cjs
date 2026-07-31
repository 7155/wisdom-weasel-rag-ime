"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const path = require("node:path");

const BRIDGE_HOST = "rag-ime-file-bridge.invalid";
const bridgeRoot = process.env.RAG_IME_FILE_FETCH_BRIDGE_DIR || "";
const networkAuditPath = process.env.RAG_IME_EXTERNAL_NETWORK_AUDIT_PATH || "";
const timeoutMs = Math.max(1_000, Number(process.env.RAG_IME_FILE_FETCH_BRIDGE_TIMEOUT_MS || 130_000));
let downstreamFetch = globalThis.fetch.bind(globalThis);
let downstreamWebSocket = typeof globalThis.WebSocket === "function" ? globalThis.WebSocket : undefined;

function abortError() {
  const error = new Error("The file fetch bridge request was aborted");
  error.name = "AbortError";
  return error;
}

async function delay(milliseconds, signal) {
  if (signal?.aborted) throw abortError();
  await new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, milliseconds);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(abortError());
      },
      { once: true },
    );
  });
}

async function atomicWrite(target, value) {
  const temporary = `${target}.tmp-${process.pid}-${crypto.randomUUID()}`;
  await fs.writeFile(temporary, `${JSON.stringify(value)}\n`, { encoding: "utf8", mode: 0o600, flag: "wx" });
  await fs.rename(temporary, target);
}

async function appendNetworkAudit(value) {
  if (!networkAuditPath) return;
  if (!path.isAbsolute(networkAuditPath)) {
    throw new Error("RAG_IME_EXTERNAL_NETWORK_AUDIT_PATH must be an absolute path");
  }
  await fs.appendFile(networkAuditPath, `${JSON.stringify(value)}\n`, { encoding: "utf8", mode: 0o600 });
}

function requestHeaders(input, init) {
  const headers = new Headers(input instanceof Request ? input.headers : undefined);
  new Headers(init?.headers).forEach((value, key) => headers.set(key, value));
  return Object.fromEntries(headers.entries());
}

async function ragImeFileFetch(input, init = undefined) {
  const url = new URL(typeof input === "string" || input instanceof URL ? input.toString() : input.url);
  if (url.protocol !== "http:" || url.hostname !== BRIDGE_HOST) {
    const requestId = crypto.randomUUID();
    const startedAtMs = Date.now();
    const method = String(init?.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
    try {
      const response = await downstreamFetch(input, init);
      await appendNetworkAudit({
        schemaVersion: "rag-ime.external-network-audit.v1",
        requestId,
        protocol: url.protocol,
        host: url.host,
        pathname: url.pathname,
        method,
        status: response.status,
        startedAtMs,
        completedAtMs: Date.now(),
      });
      return response;
    } catch (error) {
      await appendNetworkAudit({
        schemaVersion: "rag-ime.external-network-audit.v1",
        requestId,
        protocol: url.protocol,
        host: url.host,
        pathname: url.pathname,
        method,
        status: 0,
        errorName: error instanceof Error ? error.name : "Error",
        startedAtMs,
        completedAtMs: Date.now(),
      });
      throw error;
    }
  }
  if (!bridgeRoot || !path.isAbsolute(bridgeRoot)) {
    throw new Error("RAG_IME_FILE_FETCH_BRIDGE_DIR must be an absolute path");
  }
  const signal = init?.signal || (input instanceof Request ? input.signal : undefined);
  if (signal?.aborted) throw abortError();
  const bridgeId = crypto.randomUUID();
  const requestPath = path.join(bridgeRoot, "requests", `${bridgeId}.json`);
  const responsePath = path.join(bridgeRoot, "responses", `${bridgeId}.json`);
  const body = init?.body;
  if (body !== undefined && typeof body !== "string") {
    throw new TypeError("The file fetch bridge accepts string request bodies only");
  }
  await atomicWrite(requestPath, {
    bridgeId,
    url: url.toString(),
    method: String(init?.method || (input instanceof Request ? input.method : "GET")).toUpperCase(),
    headers: requestHeaders(input, init),
    body: body || "",
  });
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (signal?.aborted) {
      await fs.rm(requestPath, { force: true });
      throw abortError();
    }
    try {
      const response = JSON.parse(await fs.readFile(responsePath, "utf8"));
      await fs.rm(responsePath, { force: true });
      const status = Number(response.status || 599);
      const payload = response.payload || { ok: false, error: "empty bridge response" };
      return {
        ok: status >= 200 && status < 300,
        status,
        headers: new Headers(response.headers || {}),
        json: async () => structuredClone(payload),
        text: async () => JSON.stringify(payload),
      };
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
    await delay(10, signal);
  }
  await fs.rm(requestPath, { force: true });
  throw new Error(`File fetch bridge timed out after ${timeoutMs}ms`);
}

// Pi installs its bundled undici dispatcher after Node preloads this bridge.
// Keep the bridge as the public fetch while accepting that late implementation
// as the downstream transport, so Provider calls remain observable.
Object.defineProperty(globalThis, "fetch", {
  configurable: true,
  enumerable: true,
  get() {
    return ragImeFileFetch;
  },
  set(value) {
    if (value === ragImeFileFetch) return;
    if (typeof value !== "function") {
      throw new TypeError("global fetch replacement must be a function");
    }
    downstreamFetch = value.bind(globalThis);
  },
});

function ragImeAuditedWebSocket(input, protocols = undefined) {
  if (!new.target) throw new TypeError("WebSocket constructor must be called with new");
  if (typeof downstreamWebSocket !== "function") {
    throw new TypeError("WebSocket transport is not available");
  }
  const url = new URL(input instanceof URL ? input.toString() : String(input));
  const args = protocols === undefined ? [input] : [input, protocols];
  const socket = Reflect.construct(downstreamWebSocket, args);
  if (!["ws:", "wss:"].includes(url.protocol) || url.hostname === BRIDGE_HOST) return socket;

  const requestId = crypto.randomUUID();
  const startedAtMs = Date.now();
  let recorded = false;
  const record = (status, errorName = undefined) => {
    if (recorded) return;
    recorded = true;
    void appendNetworkAudit({
      schemaVersion: "rag-ime.external-network-audit.v1",
      requestId,
      transport: "websocket",
      protocol: url.protocol,
      host: url.host,
      pathname: url.pathname,
      method: "WEBSOCKET",
      status,
      ...(errorName ? { errorName } : {}),
      startedAtMs,
      completedAtMs: Date.now(),
    });
  };
  socket.addEventListener("open", () => record(101), { once: true });
  socket.addEventListener("error", (event) => record(0, event?.error?.name || "WebSocketError"), { once: true });
  socket.addEventListener("close", () => record(0, "WebSocketClosedBeforeOpen"), { once: true });
  return socket;
}

// OpenAI Codex prefers a persistent WebSocket over SSE. Keep that request in
// the same content-free network audit as fetch; otherwise a successful real
// Provider run is indistinguishable from the deterministic adapter.
Object.defineProperty(globalThis, "WebSocket", {
  configurable: true,
  enumerable: true,
  get() {
    return typeof downstreamWebSocket === "function" ? ragImeAuditedWebSocket : undefined;
  },
  set(value) {
    if (value === ragImeAuditedWebSocket) return;
    if (value !== undefined && typeof value !== "function") {
      throw new TypeError("global WebSocket replacement must be a constructor");
    }
    downstreamWebSocket = value;
  },
});
