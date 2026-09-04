export const MAX_CONTROL_RETRY_AFTER_MS = 60_000;

const OWNER_RECOVERY_JITTER_WINDOW_MS = 250;

/** Parse the HTTP Retry-After delay-seconds or HTTP-date form into a bounded hint. */
export function parseRetryAfterMs(
  value: string | null,
  nowMs: number = Date.now(),
): number | undefined {
  const normalized = value?.trim();
  if (!normalized) return undefined;

  let delayMs: number;
  if (/^\d+$/.test(normalized)) {
    delayMs = Number(normalized) * 1_000;
  } else {
    const retryAtMs = Date.parse(normalized);
    if (!Number.isFinite(retryAtMs)) return undefined;
    delayMs = retryAtMs - nowMs;
  }
  if (!Number.isFinite(delayMs)) return MAX_CONTROL_RETRY_AFTER_MS;
  return Math.min(MAX_CONTROL_RETRY_AFTER_MS, Math.max(0, Math.ceil(delayMs)));
}

/** Read a transport-provided retry floor without coupling live hooks to HTTP. */
export function retryAfterMsFromError(error: unknown): number | undefined {
  if (typeof error !== 'object' || error === null) return undefined;
  const retryAfterMs = Reflect.get(error, 'retryAfterMs');
  if (typeof retryAfterMs !== 'number' || !Number.isFinite(retryAfterMs)) return undefined;
  return Math.min(MAX_CONTROL_RETRY_AFTER_MS, Math.max(0, Math.ceil(retryAfterMs)));
}

/**
 * Keep one timer per owner while spreading owners across a deterministic window.
 * A server retry hint is a floor; local exponential limits still bound ordinary failures.
 */
export function ownerRecoveryDelayMs({
  ownerId,
  attempt,
  baseDelayMs,
  maxDelayMs,
  retryAfterMs,
}: {
  ownerId: string;
  attempt: number;
  baseDelayMs: number;
  maxDelayMs: number;
  retryAfterMs?: number;
}): number {
  const boundedAttempt = Math.max(0, Math.min(30, Math.trunc(attempt)));
  const exponentialDelayMs = Math.min(
    maxDelayMs,
    baseDelayMs * (2 ** boundedAttempt),
  );
  const jitterMs = ownerJitterMs(ownerId, boundedAttempt);
  const localDelayMs = Math.min(maxDelayMs, exponentialDelayMs + jitterMs);
  if (retryAfterMs === undefined) return localDelayMs;
  const hintedDelayMs = Math.min(
    MAX_CONTROL_RETRY_AFTER_MS,
    retryAfterMs + jitterMs,
  );
  return Math.max(localDelayMs, hintedDelayMs);
}

function ownerJitterMs(ownerId: string, attempt: number): number {
  let hash = 0x811c9dc5;
  const value = `${ownerId}:${attempt}`;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return ((hash >>> 0) % OWNER_RECOVERY_JITTER_WINDOW_MS) + 1;
}
