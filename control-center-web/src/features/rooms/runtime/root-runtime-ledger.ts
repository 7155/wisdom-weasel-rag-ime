export type RuntimeStopRequest = {
  generation: number;
  idempotencyKey: string;
  requestedAtMs: number;
  state: 'requested' | 'acknowledged';
};

export type RootRuntimeEntry = {
  roomId: string;
  rootId: string;
  generation: number;
  activeSessionIds: Set<string>;
  activeDispatchIds: Set<string>;
  stopRequest: RuntimeStopRequest | null;
  lastTouched: number;
};

export type RootRuntimeLedger = {
  get(roomId: string, rootId: string): RootRuntimeEntry | undefined;
  set(entry: RootRuntimeEntry): void;
  remove(roomId: string, rootId: string): void;
  removeRoom(roomId: string): void;
  entries(): IterableIterator<[string, RootRuntimeEntry]>;
};

export function createRootRuntimeLedger(): RootRuntimeLedger {
  const entries = new Map<string, RootRuntimeEntry>();
  return {
    get(roomId, rootId) { return entries.get(key(roomId, rootId)); },
    set(entry) { entries.set(key(entry.roomId, entry.rootId), entry); },
    remove(roomId, rootId) { entries.delete(key(roomId, rootId)); },
    removeRoom(roomId) {
      for (const [entryKey, entry] of entries) {
        if (entry.roomId === roomId) entries.delete(entryKey);
      }
    },
    entries() { return entries.entries(); },
  };
}

export function bindRootRuntime(
  ledger: RootRuntimeLedger,
  roomId: string,
  rootId: string,
  generation: number,
): RootRuntimeEntry {
  const current = ledger.get(roomId, rootId);
  if (current && generation < current.generation) throw new TypeError('Root generation is stale');
  if (current?.generation === generation) {
    current.lastTouched = Date.now();
    return current;
  }
  const next: RootRuntimeEntry = {
    roomId: required(roomId, 'roomId'),
    rootId: required(rootId, 'rootId'),
    generation: nonNegative(generation, 'generation'),
    activeSessionIds: new Set(),
    activeDispatchIds: new Set(),
    stopRequest: null,
    lastTouched: Date.now(),
  };
  ledger.set(next);
  return next;
}

export function trackRootSession(
  ledger: RootRuntimeLedger,
  roomId: string,
  rootId: string,
  generation: number,
  sessionId: string,
): void {
  exactEntry(ledger, roomId, rootId, generation).activeSessionIds.add(required(sessionId, 'sessionId'));
}

export function trackRootDispatch(
  ledger: RootRuntimeLedger,
  roomId: string,
  rootId: string,
  generation: number,
  dispatchId: string,
): void {
  exactEntry(ledger, roomId, rootId, generation).activeDispatchIds.add(required(dispatchId, 'dispatchId'));
}

export function requestRootRuntimeStop(
  ledger: RootRuntimeLedger,
  roomId: string,
  rootId: string,
  generation: number,
  idempotencyKey: string,
  requestedAtMs: number,
): RuntimeStopRequest {
  const entry = exactEntry(ledger, roomId, rootId, generation);
  if (entry.stopRequest?.idempotencyKey === idempotencyKey) return entry.stopRequest;
  if (entry.stopRequest?.state === 'requested') throw new TypeError('Root already has a pending Stop');
  const request: RuntimeStopRequest = {
    generation,
    idempotencyKey: required(idempotencyKey, 'idempotencyKey'),
    requestedAtMs: nonNegative(requestedAtMs, 'requestedAtMs'),
    state: 'requested',
  };
  entry.stopRequest = request;
  entry.lastTouched = Date.now();
  return request;
}

export function markRootStopAcknowledged(
  ledger: RootRuntimeLedger,
  roomId: string,
  rootId: string,
  generation: number,
  idempotencyKey: string,
): void {
  const entry = exactEntry(ledger, roomId, rootId, generation);
  if (!entry.stopRequest || entry.stopRequest.idempotencyKey !== idempotencyKey) {
    throw new TypeError('Stop acknowledgement has no matching request');
  }
  entry.stopRequest = { ...entry.stopRequest, state: 'acknowledged' };
  entry.lastTouched = Date.now();
}

function exactEntry(
  ledger: RootRuntimeLedger,
  roomId: string,
  rootId: string,
  generation: number,
): RootRuntimeEntry {
  const entry = ledger.get(roomId, rootId);
  if (!entry) throw new TypeError('Root runtime is not bound');
  if (entry.generation !== generation) throw new TypeError('Root generation does not match runtime');
  return entry;
}

function key(roomId: string, rootId: string): string {
  return `${roomId}\u0000${rootId}`;
}

function required(value: string, field: string): string {
  const normalized = value.trim();
  if (!normalized) throw new TypeError(`${field} is required`);
  return normalized;
}

function nonNegative(value: number, field: string): number {
  if (!Number.isInteger(value) || value < 0) throw new TypeError(`${field} must be nonnegative`);
  return value;
}
