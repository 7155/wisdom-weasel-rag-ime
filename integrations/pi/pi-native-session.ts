import { randomUUID } from "node:crypto";
import {
  chmodSync,
  lstatSync,
  readFileSync,
  realpathSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";

type NativeForkSession = {
  sessionId: string;
  sessionFile: string;
  parentSessionFile: string;
  parentLeafId: string;
  thinkingOverride?: "off";
};

export type TrustedRuntimeContext = {
  schemaVersion: "rag-ime.agent-runtime-context.v1";
  forkSessions: NativeForkSession[];
};

const MAX_SESSION_BYTES = 32 * 1024 * 1024;

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function managedRegularFile(candidate: string, root: string): string {
  const stat = lstatSync(candidate);
  if (stat.isSymbolicLink() || !stat.isFile() || stat.size <= 0 || stat.size > MAX_SESSION_BYTES) {
    throw new Error("Pi session file is not a bounded regular file");
  }
  const canonical = realpathSync(candidate);
  const boundary = relative(root, canonical);
  if (boundary === ".." || boundary.startsWith(`..${sep}`) || isAbsolute(boundary)) {
    throw new Error("Pi session file escaped the managed session directory");
  }
  return canonical;
}

function unsafeProviderThinking(message: Record<string, unknown>, block: unknown): boolean {
  if (!isRecord(block)) return false;
  if (block.type === "redacted_thinking") return true;
  if (block.type !== "thinking") return false;
  const provider = String(message.provider ?? "").toLowerCase();
  const api = String(message.api ?? "").toLowerCase();
  const model = String(message.model ?? "").toLowerCase();
  const anthropic = provider === "anthropic"
    || api === "anthropic-messages"
    || model.startsWith("anthropic/");
  if (!anthropic) return false;
  const signature = block.thinkingSignature ?? block.signature;
  return block.redacted === true || (typeof signature === "string" && signature.length > 0);
}

function rewriteForkSessionSafely(
  sessionFile: string,
  sessionRoot: string,
): { sessionId: string; sessionFile: string; thinkingOverride?: "off" } {
  const canonical = managedRegularFile(sessionFile, sessionRoot);
  const records = readFileSync(canonical, "utf8")
    .split("\n")
    .filter((line) => line.trim().length > 0)
    .map((line, index) => {
      try {
        const parsed = JSON.parse(line) as unknown;
        if (!isRecord(parsed)) throw new Error("record is not an object");
        return parsed;
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        throw new Error(`native Pi fork has invalid JSONL at line ${index + 1}: ${message}`);
      }
    });
  const header = records[0];
  if (!header || header.type !== "session" || typeof header.id !== "string" || !header.id) {
    throw new Error("native Pi fork is missing a valid session header");
  }

  let sanitized = false;
  for (const record of records) {
    if (record.type !== "message" || !isRecord(record.message) || record.message.role !== "assistant") {
      continue;
    }
    const message = record.message;
    const content = message.content;
    if (!Array.isArray(content)) continue;
    const filtered = content.filter((block) => !unsafeProviderThinking(message, block));
    if (filtered.length === content.length) continue;
    record.message = { ...message, content: filtered };
    sanitized = true;
  }

  if (sanitized) {
    const parent = [...records].reverse().find((record) => typeof record.id === "string");
    records.push({
      type: "thinking_level_change",
      id: randomUUID().slice(0, 8),
      parentId: typeof parent?.id === "string" ? parent.id : null,
      timestamp: new Date().toISOString(),
      thinkingLevel: "off",
    });
  }

  const temporary = `${canonical}.rag-ime-${process.pid}-${randomUUID()}.tmp`;
  try {
    writeFileSync(temporary, `${records.map((record) => JSON.stringify(record)).join("\n")}\n`, {
      encoding: "utf8",
      mode: 0o600,
      flag: "wx",
    });
    renameSync(temporary, canonical);
    chmodSync(canonical, 0o600);
  } finally {
    rmSync(temporary, { force: true });
  }
  return {
    sessionId: header.id,
    sessionFile: canonical,
    ...(sanitized ? { thinkingOverride: "off" as const } : {}),
  };
}

export function prepareNativeForkContext(ctx: any, count: number): TrustedRuntimeContext {
  if (!Number.isInteger(count) || count < 1 || count > 2) {
    throw new Error("native Pi fork count must be one or two");
  }
  const manager = ctx?.sessionManager;
  const parentCandidate = manager?.getSessionFile?.();
  const parentLeafId = manager?.getLeafId?.();
  if (typeof parentCandidate !== "string" || !parentCandidate) {
    throw new Error("fork context requires a persisted parent Pi session");
  }
  if (typeof parentLeafId !== "string" || !parentLeafId) {
    throw new Error("fork context requires the current Pi branch leaf");
  }
  if (typeof manager?.createBranchedSession !== "function") {
    throw new Error("managed Pi runtime does not expose native session branching");
  }

  const declaredRoot = manager?.getSessionDir?.();
  const rootCandidate = typeof declaredRoot === "string" && declaredRoot
    ? declaredRoot
    : dirname(resolve(parentCandidate));
  const sessionRoot = realpathSync(rootCandidate);
  const parentSessionFile = managedRegularFile(parentCandidate, sessionRoot);
  const forkSessions: NativeForkSession[] = [];
  for (let index = 0; index < count; index += 1) {
    const sessionFile = manager.createBranchedSession(parentLeafId);
    if (typeof sessionFile !== "string" || !sessionFile) {
      throw new Error("managed Pi runtime did not persist the native fork");
    }
    const sanitized = rewriteForkSessionSafely(sessionFile, sessionRoot);
    forkSessions.push({
      sessionId: sanitized.sessionId,
      sessionFile: sanitized.sessionFile,
      parentSessionFile,
      parentLeafId,
      ...(sanitized.thinkingOverride ? { thinkingOverride: sanitized.thinkingOverride } : {}),
    });
  }
  return {
    schemaVersion: "rag-ime.agent-runtime-context.v1",
    forkSessions,
  };
}
