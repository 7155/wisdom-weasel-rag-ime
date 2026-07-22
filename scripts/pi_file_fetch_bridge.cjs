"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs/promises");
const path = require("node:path");

const BRIDGE_HOST = "rag-ime-file-bridge.invalid";
const bridgeRoot = process.env.RAG_IME_FILE_FETCH_BRIDGE_DIR || "";
const networkAuditPath = process.env.RAG_IME_EXTERNAL_NETWORK_AUDIT_PATH || "";
const timeoutMs = Math.max(1_000, Number(process.env.RAG_IME_FILE_FETCH_BRIDGE_TIMEOUT_MS || 130_000));
const originalFetch = globalThis.fetch.bind(globalThis);

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

globalThis.fetch = async function ragImeFileFetch(input, init = undefined) {
  const url = new URL(typeof input === "string" || input instanceof URL ? input.toString() : input.url);
  if (url.protocol !== "http:" || url.hostname !== BRIDGE_HOST) {
    const requestId = crypto.randomUUID();
    const startedAtMs = Date.now();
    const method = String(init?.method || (input instanceof Request ? input.method : "GET")).toUpperCase();
    try {
      const response = await originalFetch(input, init);
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
};
