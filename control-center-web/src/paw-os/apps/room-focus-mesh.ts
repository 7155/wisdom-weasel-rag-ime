import type {
  RoomFocusHandoff,
  RoomFocusProjection,
  RoomFocusState,
  RoomFocusWorkItem,
} from './room-focus-projection';

/**
 * 协作网状图 — the Sol console mesh. Every node is a real Room actor or
 * WorkItem and every edge is one authoritative RoomFocusProjection field:
 * ownership, accountability, recorded review, parent/child lineage or a real
 * handoff. Layout is pure polar math over stable orderings, so the same
 * projection always yields the same picture (UR-023, no invented edges).
 */

export type RoomFocusMeshEdgeKind = 'ownership' | 'accountable' | 'review' | 'parent' | 'handoff';

export interface RoomFocusMeshNode {
  id: string;
  kind: 'root' | 'partner' | 'work';
  /** participantId for partners, WorkItem id for work, '' for root. */
  refId: string;
  /** 0..100 coordinates inside the mesh canvas. */
  x: number;
  y: number;
  state: RoomFocusState;
  label: string;
  sublabel?: string;
  orbit?: number;
}

export interface RoomFocusMeshEdge {
  id: string;
  kind: RoomFocusMeshEdgeKind;
  sourceId: string;
  targetId: string;
  /** RoomFocusState for work-derived edges, RoomFocusHandoff state for handoffs. */
  state: RoomFocusState | RoomFocusHandoff['state'];
  /** SVG path in the same 0..100 space as node coordinates. */
  path: string;
  /** Direction hint drawn near the target — only on directed handoff edges. */
  tip?: { x: number; y: number };
}

export interface RoomFocusMesh {
  nodes: RoomFocusMeshNode[];
  edges: RoomFocusMeshEdge[];
  /** Edge kinds actually present, in legend order. Never lists absent kinds. */
  edgeKinds: RoomFocusMeshEdgeKind[];
}

const CENTER = { x: 50, y: 46 };
const PARTNER_RING = { rx: 27, ry: 21 };
const WORK_RING = { rx: 40, ry: 35 };
const WORK_RING_INNER = { rx: 31, ry: 26 };
/** Above this many work nodes the outer ring alternates two radii. */
const WORK_RING_SPLIT = 8;

/** Ring geometry for decorative orbit guides — same space as node x/y. */
export const roomFocusMeshRings = {
  center: CENTER,
  partner: PARTNER_RING,
  work: WORK_RING,
} as const;

const EDGE_KIND_ORDER: RoomFocusMeshEdgeKind[] = ['ownership', 'accountable', 'review', 'parent', 'handoff'];

export function roomFocusMeshEdgeKindLabel(kind: RoomFocusMeshEdgeKind): string {
  return ({
    ownership: '负责',
    accountable: '问责',
    review: '复核',
    parent: '子任务',
    handoff: '交接',
  } satisfies Record<RoomFocusMeshEdgeKind, string>)[kind];
}

export function buildRoomFocusMesh(focus: RoomFocusProjection): RoomFocusMesh {
  const nodes: RoomFocusMeshNode[] = [{
    id: 'root',
    kind: 'root',
    refId: '',
    x: CENTER.x,
    y: CENTER.y,
    state: focus.goal.state,
    label: focus.goal.title,
  }];

  const partnerAngle = new Map<string, number>();
  focus.partners.forEach((partner, index) => {
    const angle = -90 + (index * 360) / Math.max(focus.partners.length, 1);
    partnerAngle.set(partner.participantId, angle);
    nodes.push({
      id: `partner:${partner.participantId}`,
      kind: 'partner',
      refId: partner.participantId,
      ...pointAt(angle, PARTNER_RING),
      state: partner.state,
      label: partner.celestialName,
      sublabel: partner.displayName,
      orbit: index % 4,
    });
  });

  for (const [index, placed] of workRingSlots(focus.workItems, partnerAngle).entries()) {
    const ring = focus.workItems.length > WORK_RING_SPLIT && index % 2 === 1 ? WORK_RING_INNER : WORK_RING;
    nodes.push({
      id: `work:${placed.item.id}`,
      kind: 'work',
      refId: placed.item.id,
      ...pointAt(placed.angle, ring),
      state: placed.item.state,
      label: placed.item.objective,
      ...(placed.item.wave
        ? { sublabel: `∥ 轨道 ${Math.max(placed.item.wave.parallelIndex, 0) + 1}/${Math.max(placed.item.wave.parallelSize, 1)}` }
        : {}),
    });
  }

  const byId = new Map(nodes.map((node) => [node.id, node]));
  const edges = new Map<string, RoomFocusMeshEdge>();
  const connect = (
    kind: RoomFocusMeshEdgeKind,
    sourceId: string,
    targetId: string,
    state: RoomFocusMeshEdge['state'],
    directed = false,
  ) => {
    const source = byId.get(sourceId);
    const target = byId.get(targetId);
    if (!source || !target || sourceId === targetId) return;
    const id = `${kind}:${sourceId}->${targetId}`;
    if (edges.has(id)) return;
    edges.set(id, {
      id,
      kind,
      sourceId,
      targetId,
      state,
      path: curvePath(source, target, kind),
      ...(directed ? { tip: curvePoint(source, target, kind, 0.78) } : {}),
    });
  };

  const workIds = new Set(focus.workItems.map((item) => item.id));
  for (const item of focus.workItems) {
    const workId = `work:${item.id}`;
    connect(
      'parent',
      item.parentId && workIds.has(item.parentId) ? `work:${item.parentId}` : 'root',
      workId,
      item.state,
    );
    if (item.ownerParticipantId) connect('ownership', `partner:${item.ownerParticipantId}`, workId, item.state);
    if (item.accountableParticipantId && item.accountableParticipantId !== item.ownerParticipantId) {
      connect('accountable', `partner:${item.accountableParticipantId}`, workId, item.state);
    }
    if (item.review?.reviewerParticipantId) {
      connect('review', `partner:${item.review.reviewerParticipantId}`, workId, item.state);
    }
  }
  for (const handoff of focus.handoffs) {
    connect(
      'handoff',
      `partner:${handoff.sourceParticipantId}`,
      `partner:${handoff.targetParticipantId}`,
      handoff.state,
      true,
    );
  }

  const present = new Set([...edges.values()].map((edge) => edge.kind));
  return {
    nodes,
    edges: [...edges.values()],
    edgeKinds: EDGE_KIND_ORDER.filter((kind) => present.has(kind)),
  };
}

interface WorkSlot {
  item: RoomFocusWorkItem;
  angle: number;
}

/** Work items take evenly spaced outer-ring slots, ordered so each owner's
 * items stay contiguous near that owner's angle. Even spacing keeps the ring
 * collision-free; the ownership edge — not proximity — carries the fact. */
function workRingSlots(
  items: RoomFocusWorkItem[],
  partnerAngle: Map<string, number>,
): WorkSlot[] {
  if (!items.length) return [];
  const anchorAngle = (item: RoomFocusWorkItem, index: number): number => {
    const owned = item.ownerParticipantId ? partnerAngle.get(item.ownerParticipantId) : undefined;
    if (owned !== undefined) return owned;
    const parent = items.find((candidate) => candidate.id === item.parentId);
    const inherited = parent?.ownerParticipantId ? partnerAngle.get(parent.ownerParticipantId) : undefined;
    /* Items with no resolvable owner keep insertion order after all owned
     * groups instead of guessing a partner. */
    return inherited ?? 400 + index;
  };
  const ordered = items
    .map((item, index) => ({ item, anchor: anchorAngle(item, index), index }))
    .sort((left, right) => left.anchor - right.anchor || left.index - right.index);
  const start = ordered[0]!.anchor >= 400 ? -90 : ordered[0]!.anchor;
  const step = 360 / items.length;
  return ordered.map((entry, slot) => ({ item: entry.item, angle: start + slot * step }));
}

function pointAt(angleDegrees: number, ring: { rx: number; ry: number }): { x: number; y: number } {
  const radians = (angleDegrees * Math.PI) / 180;
  return {
    x: round(CENTER.x + ring.rx * Math.cos(radians)),
    y: round(CENTER.y + ring.ry * Math.sin(radians)),
  };
}

const EDGE_BOW: Record<RoomFocusMeshEdgeKind, number> = {
  ownership: 3,
  accountable: 5,
  review: 5,
  parent: 4,
  handoff: 9,
};

/** Quadratic curve bowed away from the center so chords do not stack on Sol. */
function curvePath(source: { x: number; y: number }, target: { x: number; y: number }, kind: RoomFocusMeshEdgeKind): string {
  const control = curveControl(source, target, kind);
  return `M ${source.x} ${source.y} Q ${control.x} ${control.y} ${target.x} ${target.y}`;
}

function curvePoint(
  source: { x: number; y: number },
  target: { x: number; y: number },
  kind: RoomFocusMeshEdgeKind,
  t: number,
): { x: number; y: number } {
  const control = curveControl(source, target, kind);
  const inverse = 1 - t;
  return {
    x: round(inverse * inverse * source.x + 2 * inverse * t * control.x + t * t * target.x),
    y: round(inverse * inverse * source.y + 2 * inverse * t * control.y + t * t * target.y),
  };
}

function curveControl(
  source: { x: number; y: number },
  target: { x: number; y: number },
  kind: RoomFocusMeshEdgeKind,
): { x: number; y: number } {
  const mid = { x: (source.x + target.x) / 2, y: (source.y + target.y) / 2 };
  let away = { x: mid.x - CENTER.x, y: mid.y - CENTER.y };
  if (Math.hypot(away.x, away.y) < 0.001) {
    /* A perfect diameter: bow perpendicular to the chord instead. */
    away = { x: -(target.y - source.y), y: target.x - source.x };
  }
  const length = Math.hypot(away.x, away.y) || 1;
  const bow = EDGE_BOW[kind];
  return {
    x: round(mid.x + (away.x / length) * bow),
    y: round(mid.y + (away.y / length) * bow),
  };
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}
