/**
 * Wayfinder work projection — the desktop's read-only view of recent Sessions
 * and Rooms at desktop density.
 *
 * The raw directory is a web-length list: every repeated goal prompt and every
 * A legacy Room partner clone with a numbered suffix arrives as its own record. A desktop
 * home must stay a short, grouped, bounded surface, so this module folds the
 * raw records before anything renders:
 *
 * 1. Room partner Sessions (`roomParticipant`) never appear as rows. They fold
 *    into their Room's row as side-by-side partner names; when the Room record
 *    itself is missing from the directory, one synthesized Room row carries
 *    the shared goal text and the partner labels.
 * 2. Records that repeat the same goal copy (same kind + title + project)
 *    collapse into the newest record; older runs stay reachable as `repeats`.
 * 3. Rows land in three recency buckets — 今天 / 本周 / 更早 — each with a
 *    small preview count so the first screen shows recent useful work, not an
 *    endless page. The stale bucket is meant to rest collapsed.
 *
 * Pure data → data. The owning component decides fetch, expansion and clicks.
 */

import { ROOM_PLANET_NAMES, roomPlanetName } from '@/features/rooms/room-copy';

export type WayfinderWorkKind = 'session' | 'room';
export type WayfinderWorkActivity = 'running' | 'attention' | 'idle';

export type WayfinderWorkSessionSource = {
  id: string;
  title: string;
  status: string;
  updatedAtMs: number;
  workspaceRoots?: string[];
  roomParticipant?: { roomId?: string } | null;
};

export type WayfinderWorkRoomSource = {
  id: string;
  title: string;
  status?: string;
  updatedAtMs: number;
  workspaceRoots?: string[];
  participants?: Array<{ displayName?: string; ordinal?: number; status?: string }>;
};

export type WayfinderWorkRepeat = {
  id: string;
  kind: WayfinderWorkKind;
  updatedAtMs: number;
};

export type WayfinderWorkItem = {
  key: string;
  kind: WayfinderWorkKind;
  id: string;
  title: string;
  project: string;
  updatedAtMs: number;
  activity: WayfinderWorkActivity;
  /** Room partner names in ordinal order — rendered side by side, never as rows. */
  agents: string[];
  /** Older records with the same goal copy, newest first. */
  repeats: WayfinderWorkRepeat[];
};

export type WayfinderWorkBucketId = 'today' | 'week' | 'earlier';

export type WayfinderWorkBucket = {
  id: WayfinderWorkBucketId;
  label: string;
  items: WayfinderWorkItem[];
  /** How many rows the first screen shows before the bucket asks to expand. */
  previewCount: number;
};

export type WayfinderWorkView = {
  buckets: WayfinderWorkBucket[];
  /** Rows after folding — what the desktop can actually show. */
  rowCount: number;
  /** Raw records absorbed by folding (partner clones + repeated goal copy). */
  foldedCount: number;
};

const BUCKET_LABELS: Record<WayfinderWorkBucketId, string> = {
  today: '今天',
  week: '本周',
  earlier: '更早',
};

const BUCKET_PREVIEW: Record<WayfinderWorkBucketId, number> = {
  today: 5,
  week: 3,
  earlier: 0,
};

const PARTNER_SUFFIX = /\s*[·•・\-–—]\s*(Agent\s*\d+|伙伴\s*\d+|Earth|Mars|Venus|Jupiter|Saturn|Mercury|Neptune|Uranus|Planet\s*\d+)\s*$/i;

export function projectWayfinderWork({
  nowMs,
  query = '',
  rooms,
  sessions,
}: {
  nowMs: number;
  query?: string;
  rooms: readonly WayfinderWorkRoomSource[];
  sessions: readonly WayfinderWorkSessionSource[];
}): WayfinderWorkView {
  const liveRooms = rooms.filter((room) => room.status !== 'archived');
  const liveSessions = sessions.filter((session) => session.status !== 'archived');
  const roomIds = new Set(liveRooms.map((room) => room.id));

  const partnerSessions = liveSessions.filter((session) => session.roomParticipant?.roomId);
  const plainSessions = liveSessions.filter((session) => !session.roomParticipant?.roomId);

  const orphanPartnerRows = orphanPartnerRooms(partnerSessions, roomIds);
  const roomRows = liveRooms.map(roomRow);
  const sessionRows = plainSessions.map(sessionRow);

  let foldedCount = partnerSessions.length;
  const deduped = new Map<string, WayfinderWorkItem>();
  for (const row of [...sessionRows, ...roomRows, ...orphanPartnerRows]
    .sort((left, right) => right.updatedAtMs - left.updatedAtMs)) {
    const foldKey = `${row.kind}\u0001${normalizedTitle(row.title)}\u0001${row.project}`;
    const leader = deduped.get(foldKey);
    if (!leader) {
      deduped.set(foldKey, row);
      continue;
    }
    leader.repeats.push({ id: row.id, kind: row.kind, updatedAtMs: row.updatedAtMs });
    if (leader.activity === 'idle' && row.activity !== 'idle') leader.activity = row.activity;
    foldedCount += 1;
  }

  const needle = query.trim().toLocaleLowerCase();
  const matched = [...deduped.values()].filter((item) => (
    !needle
    || `${item.title}\n${item.project}\n${item.agents.join('\n')}`.toLocaleLowerCase().includes(needle)
  ));

  const buckets: WayfinderWorkBucket[] = (['today', 'week', 'earlier'] as const)
    .map((id) => ({
      id,
      label: BUCKET_LABELS[id],
      items: matched.filter((item) => bucketFor(item.updatedAtMs, nowMs) === id),
      previewCount: BUCKET_PREVIEW[id],
    }))
    .filter((bucket) => bucket.items.length > 0);

  return { buckets, rowCount: matched.length, foldedCount };
}

function sessionRow(session: WayfinderWorkSessionSource): WayfinderWorkItem {
  return {
    key: `session:${session.id}`,
    kind: 'session',
    id: session.id,
    title: session.title || '未命名工作',
    project: projectLeaf(session.workspaceRoots),
    updatedAtMs: session.updatedAtMs,
    activity: session.status === 'busy' ? 'running' : session.status === 'faulted' ? 'attention' : 'idle',
    agents: [],
    repeats: [],
  };
}

function roomRow(room: WayfinderWorkRoomSource): WayfinderWorkItem {
  return {
    key: `room:${room.id}`,
    kind: 'room',
    id: room.id,
    title: room.title || '未命名工作',
    project: projectLeaf(room.workspaceRoots),
    updatedAtMs: room.updatedAtMs,
    activity: room.status === 'active' ? 'running' : 'idle',
    agents: (room.participants ?? [])
      .filter((participant) => participant.status !== 'removed')
      .sort((left, right) => (left.ordinal ?? 0) - (right.ordinal ?? 0))
      .map((participant) => roomPlanetName(participant.ordinal ?? 0))
      .filter(Boolean),
    repeats: [],
  };
}

/** Partner Sessions whose Room record is absent still fold into one Room row. */
function orphanPartnerRooms(
  partnerSessions: readonly WayfinderWorkSessionSource[],
  knownRoomIds: ReadonlySet<string>,
): WayfinderWorkItem[] {
  const byRoom = new Map<string, WayfinderWorkSessionSource[]>();
  for (const session of partnerSessions) {
    const roomId = session.roomParticipant?.roomId ?? '';
    if (!roomId || knownRoomIds.has(roomId)) continue;
    byRoom.set(roomId, [...(byRoom.get(roomId) ?? []), session]);
  }
  return [...byRoom.entries()].map(([roomId, members]) => {
    const newest = members.reduce((left, right) => (right.updatedAtMs > left.updatedAtMs ? right : left));
    const agents = members
      .map((member, index) => roomPlanetName(legacyPartnerOrdinal(member.title) ?? index))
      .sort((left, right) => roomPlanetOrdinal(left) - roomPlanetOrdinal(right));
    return {
      key: `room:${roomId}`,
      kind: 'room' as const,
      id: roomId,
      title: newest.title.replace(PARTNER_SUFFIX, '').trim() || newest.title,
      project: projectLeaf(newest.workspaceRoots),
      updatedAtMs: newest.updatedAtMs,
      activity: members.some((member) => member.status === 'busy')
        ? 'running' as const
        : members.some((member) => member.status === 'faulted') ? 'attention' as const : 'idle' as const,
      agents,
      repeats: [],
    };
  });
}

function legacyPartnerOrdinal(title: string): number | undefined {
  const identity = title.match(PARTNER_SUFFIX)?.[1]?.trim();
  if (!identity) return undefined;
  const known = ROOM_PLANET_NAMES.findIndex((name) => name.toLowerCase() === identity.toLowerCase());
  if (known >= 0) return known;
  const matched = identity.match(/\d+/u)?.[0];
  if (!matched) return undefined;
  const ordinal = Number(matched) - 1;
  return Number.isInteger(ordinal) && ordinal >= 0 ? ordinal : undefined;
}

function roomPlanetOrdinal(name: string): number {
  const known = ROOM_PLANET_NAMES.indexOf(name as typeof ROOM_PLANET_NAMES[number]);
  if (known >= 0) return known;
  const fallback = Number(name.match(/\d+/u)?.[0]);
  return Number.isInteger(fallback) ? fallback - 1 : Number.MAX_SAFE_INTEGER;
}

function normalizedTitle(title: string): string {
  return title.replace(/\s+/g, ' ').replace(/[…]+$/, '').trim().toLocaleLowerCase();
}

function projectLeaf(roots: readonly string[] | undefined): string {
  const first = roots?.[0]?.trim() ?? '';
  if (!first) return '';
  return first.split('/').filter(Boolean).at(-1) ?? '';
}

function bucketFor(updatedAtMs: number, nowMs: number): WayfinderWorkBucketId {
  const updated = new Date(updatedAtMs);
  const now = new Date(nowMs);
  if (
    updated.getFullYear() === now.getFullYear()
    && updated.getMonth() === now.getMonth()
    && updated.getDate() === now.getDate()
  ) return 'today';
  return nowMs - updatedAtMs < 7 * 86_400_000 ? 'week' : 'earlier';
}

export function wayfinderWorkTime(updatedAtMs: number, nowMs: number): string {
  const delta = Math.max(0, nowMs - updatedAtMs);
  if (delta < 60_000) return '刚刚';
  if (delta < 3_600_000) return `${Math.floor(delta / 60_000)} 分钟前`;
  if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)} 小时前`;
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric' }).format(new Date(updatedAtMs));
}
