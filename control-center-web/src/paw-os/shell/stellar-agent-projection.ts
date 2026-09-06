/**
 * Pure data projection for the PAW stellar wallpaper.
 *
 * A planet is always keyed by a real Session id.  Geometry and palette
 * choices are deterministic functions of that id, so adding a Session does
 * not move every other body in the sky.  Runtime activity is taken from an
 * individual Session record and only a fresh `busy`/`running` value can make
 * a planet enter `runningPlanets`.  Room membership gives a label/group; it
 * does not imply execution and it never creates peer-to-peer edges.
 */

export type StellarAgentStatus = 'running' | 'idle' | 'attention' | 'terminal' | 'unknown';
export type StellarAgentKind = 'standalone' | 'room' | 'subagent';
export type StellarAgentRelationshipKind = 'parent-child';

/** The directory shape stays deliberately smaller than the full Runtime
 * contract so this projection can consume both SessionSummary and a future
 * directory projection.  Extra fields are ignored unless they are explicit
 * relationship/membership fields listed below. */
export type StellarAgentSessionSource = {
  id: string;
  title?: string;
  status?: string;
  updatedAtMs?: number;
  sessionKind?: string;
  roomParticipant?: {
    roomId?: string;
    participantId?: string;
    status?: string;
  } | null;
  /** Present when a directory includes the delegation/session tree. */
  parentSessionId?: string | null;
  /** Compatibility with Runtime projections that expose the parent as id. */
  parentId?: string | null;
};

export type StellarAgentRoomParticipantSource = {
  id?: string;
  participantId?: string;
  sessionId?: string;
  displayName?: string;
  status?: string;
  ordinal?: number;
};

export type StellarAgentRoomSource = {
  id: string;
  title?: string;
  status?: string;
  updatedAtMs?: number;
  participants?: readonly StellarAgentRoomParticipantSource[];
};

export type StellarAgentProjectionInput = {
  nowMs: number;
  sessions: readonly StellarAgentSessionSource[];
  rooms: readonly StellarAgentRoomSource[];
  /** These flags come from PawWorkDirectory, not from a model guess. */
  sessionStatusFresh?: boolean;
  roomStatusFresh?: boolean;
  /** Optional fetch timestamps let callers enforce a hard age bound. */
  sessionSnapshotAtMs?: number;
  roomSnapshotAtMs?: number;
  maxSnapshotAgeMs?: number;
};

export type StellarAgentPlanet = {
  /** Stable DOM/render key and canonical click identity. */
  key: string;
  sessionId: string;
  /** Display name comes from Session.title or RoomParticipant.displayName. */
  name: string;
  title: string;
  kind: StellarAgentKind;
  sourceStatus: string;
  status: StellarAgentStatus;
  statusLabel: string;
  running: boolean;
  updatedAtMs: number;
  roomId?: string;
  roomTitle?: string;
  participantId?: string;
  participantStatus?: string;
  parentSessionId?: string;
  position: {
    /** Normalized coordinates for the wallpaper renderer. */
    x: number;
    y: number;
    depth: number;
  };
  style: {
    /** Stable hash seed for texture, glow and any renderer-specific details. */
    seed: number;
    /** Small finite palette slot; the renderer owns the actual colors. */
    paletteIndex: number;
    size: number;
    glow: number;
  };
};

export type StellarAgentRelationship = {
  id: string;
  kind: StellarAgentRelationshipKind;
  fromSessionId: string;
  toSessionId: string;
  /** The exact source field that proved this edge. */
  evidence: 'session.parentSessionId' | 'session.parentId';
};

export type StellarAgentProjection = {
  nowMs: number;
  freshness: {
    sessions: boolean;
    rooms: boolean;
  };
  /** All real records that can be represented, including non-running state. */
  planets: StellarAgentPlanet[];
  /** Renderer-facing subset. Every item here has running === true. */
  runningPlanets: StellarAgentPlanet[];
  /** Explicit parent links only. Room co-membership is intentionally absent. */
  relationships: StellarAgentRelationship[];
  /** Machine-readable reasons for any missing/uncertain evidence. */
  limitations: string[];
};

const DEFAULT_MAX_SNAPSHOT_AGE_MS = 60_000;
const PALETTE_SIZE = 6;

const RUNNING_STATUSES = new Set([
  'busy',
  'running',
  'executing',
  'in_progress',
  'in-progress',
]);

const ATTENTION_STATUSES = new Set([
  'blocked',
  'faulted',
  'failed',
  'error',
  'needs_attention',
  'needs-attention',
]);

const TERMINAL_STATUSES = new Set([
  'archived',
  'aborted',
  'cancelled',
  'canceled',
  'completed',
  'complete',
  'done',
  'succeeded',
  'success',
  'timed_out',
  'timed-out',
]);

/**
 * Build the wallpaper's truthful scene model.  This function has no clock,
 * random, DOM, or Runtime side effects; `nowMs` only evaluates optional
 * directory snapshot ages and is copied to the returned model.
 */
export function projectStellarAgents({
  nowMs,
  sessions,
  rooms,
  sessionStatusFresh = true,
  roomStatusFresh = true,
  sessionSnapshotAtMs,
  roomSnapshotAtMs,
  maxSnapshotAgeMs = DEFAULT_MAX_SNAPSHOT_AGE_MS,
}: StellarAgentProjectionInput): StellarAgentProjection {
  const freshness = {
    sessions: isFresh(sessionStatusFresh, sessionSnapshotAtMs, nowMs, maxSnapshotAgeMs),
    rooms: isFresh(roomStatusFresh, roomSnapshotAtMs, nowMs, maxSnapshotAgeMs),
  };
  const limitations = new Set<string>();
  if (!freshness.sessions) limitations.add('session-status-stale');
  if (!freshness.rooms) limitations.add('room-status-stale');

  const roomById = new Map<string, StellarAgentRoomSource>();
  for (const room of rooms) {
    if (!room.id.trim()) continue;
    const current = roomById.get(room.id);
    if (!current || compareRoomSource(room, current) < 0) roomById.set(room.id, room);
  }

  const participantBySessionId = new Map<string, RoomMembership>();
  for (const room of roomById.values()) {
    if (room.status?.toLocaleLowerCase() === 'archived') continue;
    for (const participant of room.participants ?? []) {
      const sessionId = clean(participant.sessionId);
      if (!sessionId) {
        limitations.add('room-participant-session-id-missing');
        continue;
      }
      if (participant.status?.toLocaleLowerCase() === 'removed') continue;
      const membership: RoomMembership = {
        roomId: room.id,
        roomTitle: clean(room.title),
        participantId: clean(participant.participantId) || clean(participant.id),
        displayName: clean(participant.displayName),
        participantStatus: clean(participant.status),
        updatedAtMs: finiteMs(room.updatedAtMs),
      };
      const current = participantBySessionId.get(sessionId);
      if (current && current.roomId !== membership.roomId) {
        limitations.add('multiple-room-memberships');
      }
      if (!current || compareMembership(membership, current) < 0) {
        participantBySessionId.set(sessionId, membership);
      }
    }
  }

  const records = new Map<string, StellarAgentRecord>();
  for (const source of sessions) {
    const sessionId = clean(source.id);
    if (!sessionId) continue;
    const membership = sessionMembership(source, participantBySessionId, roomById, limitations);
    const candidate: StellarAgentRecord = {
      sessionId,
      title: clean(source.title),
      sourceStatus: clean(source.status),
      updatedAtMs: finiteMs(source.updatedAtMs),
      sessionKind: clean(source.sessionKind),
      parentSessionId: explicitParentSessionId(source),
      parentField: clean(source.parentSessionId)
        ? 'session.parentSessionId'
        : clean(source.parentId)
          ? 'session.parentId'
          : undefined,
      membership,
      direct: true,
    };
    const current = records.get(sessionId);
    if (!current || compareRecord(candidate, current) < 0) records.set(sessionId, candidate);
  }

  // A Room may expose a real Session id while its individual Session record
  // is outside the directory projection. It is representable as unknown, but
  // its membership status can never be promoted to running.
  for (const [sessionId, membership] of participantBySessionId) {
    if (records.has(sessionId)) continue;
    records.set(sessionId, {
      sessionId,
      title: membership.displayName ?? '',
      sourceStatus: '',
      updatedAtMs: membership.updatedAtMs,
      sessionKind: '',
      parentSessionId: undefined,
      membership,
      direct: false,
    });
    limitations.add('individual-session-state-missing');
  }

  const planets = [...records.values()]
    .map((record) => planetFromRecord(record, freshness.sessions, limitations))
    .sort(comparePlanets);
  const runningPlanets = planets.filter((planet) => planet.running);
  const relationships = [...records.values()]
    .flatMap((record) => relationshipFromRecord(record, records, limitations))
    .sort((left, right) => left.id.localeCompare(right.id));

  return {
    nowMs,
    freshness,
    planets,
    runningPlanets,
    relationships,
    limitations: [...limitations].sort(),
  };
}

type RoomMembership = {
  roomId: string;
  roomTitle?: string;
  participantId?: string;
  displayName?: string;
  participantStatus?: string;
  updatedAtMs: number;
};

type StellarAgentRecord = {
  sessionId: string;
  title: string;
  sourceStatus: string;
  updatedAtMs: number;
  sessionKind: string;
  parentSessionId?: string;
  parentField?: StellarAgentRelationship['evidence'];
  membership?: RoomMembership;
  direct: boolean;
};

function planetFromRecord(
  record: StellarAgentRecord,
  sessionsFresh: boolean,
  limitations: Set<string>,
): StellarAgentPlanet {
  const status = projectStatus(record.sourceStatus, sessionsFresh, record.direct);
  const running = status === 'running';
  const roomId = record.membership?.roomId;
  const title = record.title || record.membership?.displayName || '未命名 Agent';
  if (roomId && !record.membership?.roomTitle) limitations.add('room-title-missing');
  if (roomId && !record.direct) limitations.add('individual-session-state-missing');
  const seed = stellarHash(record.sessionId);
  const styleUnit = (suffix: string) => stellarUnit(`${record.sessionId}:${suffix}`);
  return {
    key: `session:${record.sessionId}`,
    sessionId: record.sessionId,
    name: title,
    title,
    kind: record.parentSessionId ? 'subagent' : roomId ? 'room' : 'standalone',
    sourceStatus: record.sourceStatus || 'unknown',
    status,
    statusLabel: statusLabel(status),
    running,
    updatedAtMs: record.updatedAtMs,
    ...(roomId ? { roomId } : {}),
    ...(record.membership?.roomTitle ? { roomTitle: record.membership.roomTitle } : {}),
    ...(record.membership?.participantId ? { participantId: record.membership.participantId } : {}),
    ...(record.membership?.participantStatus ? { participantStatus: record.membership.participantStatus } : {}),
    ...(record.parentSessionId ? { parentSessionId: record.parentSessionId } : {}),
    position: stablePosition(record.sessionId),
    style: {
      seed,
      paletteIndex: seed % PALETTE_SIZE,
      size: round(0.055 + styleUnit('size') * 0.035),
      glow: round(0.45 + styleUnit('glow') * 0.5),
    },
  };
}

function relationshipFromRecord(
  record: StellarAgentRecord,
  records: ReadonlyMap<string, StellarAgentRecord>,
  limitations: Set<string>,
): StellarAgentRelationship[] {
  const parentSessionId = record.parentSessionId;
  if (!parentSessionId || parentSessionId === record.sessionId) return [];
  if (!records.has(parentSessionId)) limitations.add('parent-session-missing');
  const source = record.parentField ?? 'session.parentSessionId';
  return [{
    id: `parent-child:${parentSessionId}->${record.sessionId}`,
    kind: 'parent-child',
    fromSessionId: parentSessionId,
    toSessionId: record.sessionId,
    evidence: source,
  }];
}

function sessionMembership(
  source: StellarAgentSessionSource,
  participantBySessionId: ReadonlyMap<string, RoomMembership>,
  roomById: ReadonlyMap<string, StellarAgentRoomSource>,
  limitations: Set<string>,
): RoomMembership | undefined {
  const explicit = source.roomParticipant;
  const explicitRoomId = clean(explicit?.roomId);
  const explicitParticipantId = clean(explicit?.participantId);
  const explicitParticipantStatus = clean(explicit?.status);
  if (explicitParticipantStatus?.toLocaleLowerCase() === 'removed') return undefined;
  if (explicitRoomId) {
    const room = roomById.get(explicitRoomId);
    if (!room) limitations.add('room-record-missing');
    // Explicit Session membership wins even if another Room has a newer
    // directory row for this Session. Never mix identities across Rooms.
    const fromRoom = room?.participants?.find((participant) => (
      clean(participant.sessionId) === clean(source.id)
      && clean(participant.status).toLocaleLowerCase() !== 'removed'
      && (!explicitParticipantId
        || (clean(participant.participantId) || clean(participant.id)) === explicitParticipantId)
    ));
    return {
      roomId: explicitRoomId,
      roomTitle: clean(room?.title),
      participantId: explicitParticipantId || clean(fromRoom?.participantId) || clean(fromRoom?.id),
      displayName: clean(fromRoom?.displayName),
      participantStatus: explicitParticipantStatus || clean(fromRoom?.status),
      updatedAtMs: finiteMs(source.updatedAtMs),
    };
  }
  return participantBySessionId.get(source.id);
}

function explicitParentSessionId(source: StellarAgentSessionSource): string | undefined {
  const parentSessionId = clean(source.parentSessionId);
  if (parentSessionId) return parentSessionId;
  return clean(source.parentId);
}

function projectStatus(sourceStatus: string, sessionsFresh: boolean, direct: boolean): StellarAgentStatus {
  const normalized = sourceStatus.toLocaleLowerCase();
  if (TERMINAL_STATUSES.has(normalized)) return 'terminal';
  if (ATTENTION_STATUSES.has(normalized)) return 'attention';
  if (!sessionsFresh || !direct) return 'unknown';
  if (RUNNING_STATUSES.has(normalized)) return 'running';
  return 'idle';
}

function statusLabel(status: StellarAgentStatus): string {
  return {
    running: '运行中',
    idle: '就绪',
    attention: '需要处理',
    terminal: '已结束',
    unknown: '状态未知',
  }[status];
}

function comparePlanets(left: StellarAgentPlanet, right: StellarAgentPlanet): number {
  const statusOrder: Record<StellarAgentStatus, number> = {
    running: 0,
    attention: 1,
    idle: 2,
    unknown: 3,
    terminal: 4,
  };
  return statusOrder[left.status] - statusOrder[right.status]
    || right.updatedAtMs - left.updatedAtMs
    || left.sessionId.localeCompare(right.sessionId);
}

function compareRecord(left: StellarAgentRecord, right: StellarAgentRecord): number {
  return Number(right.direct) - Number(left.direct)
    || right.updatedAtMs - left.updatedAtMs
    || left.sourceStatus.localeCompare(right.sourceStatus)
    || left.sessionId.localeCompare(right.sessionId);
}

function compareRoomSource(left: StellarAgentRoomSource, right: StellarAgentRoomSource): number {
  return finiteMs(right.updatedAtMs) - finiteMs(left.updatedAtMs) || left.id.localeCompare(right.id);
}

function compareMembership(left: RoomMembership, right: RoomMembership): number {
  return right.updatedAtMs - left.updatedAtMs
    || left.roomId.localeCompare(right.roomId)
    || (left.participantId ?? '').localeCompare(right.participantId ?? '');
}

function isFresh(
  flag: boolean,
  snapshotAtMs: number | undefined,
  nowMs: number,
  maxSnapshotAgeMs: number,
): boolean {
  if (!flag) return false;
  if (snapshotAtMs === undefined) return true;
  if (!Number.isFinite(snapshotAtMs) || !Number.isFinite(nowMs)) return false;
  if (snapshotAtMs > nowMs) return true;
  return nowMs - snapshotAtMs <= Math.max(0, maxSnapshotAgeMs);
}

function stablePosition(sessionId: string): StellarAgentPlanet['position'] {
  const angle = stellarUnit(`${sessionId}:angle`) * Math.PI * 2;
  const radius = 0.19 + stellarUnit(`${sessionId}:radius`) * 0.25;
  const x = clamp(0.5 + Math.cos(angle) * radius, 0.04, 0.96);
  const y = clamp(0.5 + Math.sin(angle) * radius * 0.68, 0.06, 0.94);
  return {
    x: round(x),
    y: round(y),
    depth: round(0.2 + stellarUnit(`${sessionId}:depth`) * 0.8),
  };
}

/** FNV-1a keeps this module dependency-free and stable across JS runtimes. */
export function stellarHash(seed: string): number {
  let hash = 0x811c9dc5;
  for (let index = 0; index < seed.length; index += 1) {
    hash ^= seed.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

export function stellarUnit(seed: string): number {
  return stellarHash(seed) / 0x100000000;
}

function clean(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function finiteMs(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function round(value: number): number {
  return Math.round(value * 10_000) / 10_000;
}
