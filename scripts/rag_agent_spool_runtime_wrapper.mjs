import { randomUUID } from "node:crypto";
import { lstat, readFile, rename, unlink, writeFile } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const REQUEST_SCHEMA = "rag-ime.rag-benchmark-spool-request.v1";
const RESPONSE_SCHEMA = "rag-ime.rag-benchmark-spool-response.v1";
const spoolDir = process.env.RAG_IME_BENCHMARK_GATEWAY_SPOOL ?? "";
const runtimeEntrypoint = process.env.RAG_IME_BENCHMARK_RUNTIME_ENTRYPOINT ?? "";
const timeoutMs = Number.parseInt(
  process.env.RAG_IME_BENCHMARK_GATEWAY_TIMEOUT_MS ?? "120000",
  10,
);
const nativeFetch = globalThis.fetch.bind(globalThis);

if (!spoolDir || !runtimeEntrypoint) {
  throw new Error("benchmark spool runtime wrapper is not configured");
}
const spoolStat = await lstat(spoolDir);
if (!spoolStat.isDirectory() || spoolStat.isSymbolicLink()) {
  throw new Error("benchmark spool root must be a real directory");
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function requestUrl(input) {
  if (typeof input === "string" || input instanceof URL) return String(input);
  if (input instanceof Request) return input.url;
  throw new TypeError("unsupported fetch input for benchmark spool transport");
}

async function requestBody(input, init) {
  if (init?.body !== undefined && init.body !== null) {
    if (typeof init.body === "string") return init.body;
    if (init.body instanceof Uint8Array) {
      return Buffer.from(init.body).toString("utf8");
    }
    throw new TypeError("benchmark spool transport requires a text request body");
  }
  if (input instanceof Request) return await input.clone().text();
  return "";
}

function requestHeaders(input, init) {
  const headers = new Headers(input instanceof Request ? input.headers : undefined);
  const overrides = new Headers(init?.headers);
  for (const [name, value] of overrides.entries()) headers.set(name, value);
  return Object.fromEntries([...headers.entries()].map(([name, value]) => [name.toLowerCase(), value]));
}

async function spoolFetch(input, init = undefined) {
  const url = requestUrl(input);
  if (new URL(url).protocol !== "rag-ime-spool:") {
    return await nativeFetch(input, init);
  }
  const requestId = randomUUID();
  const requestPath = path.join(spoolDir, `${requestId}.request.json`);
  const responsePath = path.join(spoolDir, `${requestId}.response.json`);
  const temporaryPath = path.join(spoolDir, `.${requestId}.${randomUUID()}.request.tmp`);
  const signal = init?.signal ?? (input instanceof Request ? input.signal : undefined);
  const envelope = {
    schemaVersion: REQUEST_SCHEMA,
    requestId,
    url,
    method: String(init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase(),
    headers: requestHeaders(input, init),
    body: await requestBody(input, init),
  };
  await writeFile(temporaryPath, `${JSON.stringify(envelope)}\n`, {
    encoding: "utf8",
    flag: "wx",
    mode: 0o600,
  });
  await rename(temporaryPath, requestPath);
  const startedAt = Date.now();
  try {
    while (true) {
      if (signal?.aborted) {
        throw signal.reason instanceof Error
          ? signal.reason
          : new DOMException("The operation was aborted", "AbortError");
      }
      try {
        const response = JSON.parse(await readFile(responsePath, "utf8"));
        if (response.schemaVersion !== RESPONSE_SCHEMA || response.requestId !== requestId) {
          throw new Error("benchmark spool response identity is invalid");
        }
        await unlink(responsePath);
        return new Response(String(response.body ?? ""), {
          status: Number(response.status),
          headers: response.headers,
        });
      } catch (error) {
        if (error?.code !== "ENOENT") throw error;
      }
      if (!Number.isFinite(timeoutMs) || timeoutMs < 1 || Date.now() - startedAt > timeoutMs) {
        throw new Error("benchmark spool Tool request timed out");
      }
      await sleep(10);
    }
  } finally {
    await unlink(requestPath).catch((error) => {
      if (error?.code !== "ENOENT") throw error;
    });
    await unlink(temporaryPath).catch((error) => {
      if (error?.code !== "ENOENT") throw error;
    });
  }
}

globalThis.fetch = spoolFetch;
await import(pathToFileURL(runtimeEntrypoint).href);
