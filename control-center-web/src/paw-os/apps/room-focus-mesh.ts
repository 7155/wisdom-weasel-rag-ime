import type {
  RoomFocusHandoff,
  RoomFocusProjection,
  RoomFocusState,
  RoomFocusWorkItem,
} from './room-focus-projection';

/**
 * 协作时序网 — the Sol console mesh as a chronological flow graph, not an
 * orbit. Every node is a real Room actor or WorkItem and every edge one
 * authoritative RoomFocusProjection field: ownership, accountability,
 * recorded review, parent/child lineage or a real handoff.
 *
 * Columns are identity lanes: Sol (the origin) leftmost, then one stable lane
 * per partner; a WorkItem lives in its owner's lane. Rows are real event
 * order — a node's vertical position comes only from recorded times
 * (WorkItem updatedAtMs, handoff createdAtMs, flow packet createdAtMs), so
 * reading top→bottom is reading time. Nothing invents a timestamp: a partner
 * with no recorded involvement stays on the origin row. Layout is pure
 * deterministic math over stable orderings (UR-023).
 */

export type RoomFocusMeshEdgeKind = 'ownership' | 'accountable' | 'review' | 'parent' | 'handoff';

export interface RoomFocusMeshNode {
  id: string;
  kind: 'root' | 'partner' | 'work';
  /** participantId for partners, WorkItem id for work, '' for root. */
  refId: string;
  /** x in the fixed 0..100 lane axis; y in 0..mesh.height — time grows down. */
  x: number;
  y: number;
  state: RoomFocusState;
  label: string;
  sublabel?: string;
  /** Stable partner identity color index. */
  tone?: number;
}

export interface RoomFocusMeshEdge {
  id: string;
  kind: RoomFocusMeshEdgeKind;
  sourceId: string;
  targetId: string;
  /** RoomFocusState for work-derived edges, RoomFocusHandoff state for handoffs. */
  state: RoomFocusState | RoomFocusHandoff['state'];
  /** SVG path in the same 0..100 × 0..height space as node coordinates. */
  path: string;
  /** Direction hint drawn near the target — only on directed handoff edges. */
  tip?: { x: number; y: number };
}

/** One vertical lifeline guide: from the actor's entry row to the bottom. */
export interface RoomFocusMeshLane {
  /** 'root' for Sol, otherwise the participantId owning the lane. */
  id: string;
  x: number;
  y0: number;
  y1: number;
}

export interface RoomFocusMesh {
  nodes: RoomFocusMeshNode[];
  edges: RoomFocusMeshEdge[];
  /** Edge kinds actually present, in legend order. Never lists absent kinds. */
  edgeKinds: RoomFocusMeshEdgeKind[];
  lanes: RoomFocusMeshLane[];
  /** viewBox height in the same units as the fixed 0..100 width. */
  height: number;
}

const X_MARGIN = 3;
const ROW_TOP = 7;
const ROW_STEP = 12;
const ROW_BOTTOM = 9;
/** A quiet room (partners but no timed events) still gets a readable band. */
const MIN_HEIGHT = 36;

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
  const partnerColumn = new Map(focus.partners.map((partner, index) => [partner.participantId, index + 1]));
  const columnCount = focus.partners.length + 1;
  const laneX = (column: number) => round(X_MARGIN + ((column + 0.5) * (100 - 2 * X_MARGIN)) / columnCount);

  /* Chronological rows: every timed node in real event order. Ties keep
   * actors ahead of their same-instant work, then projection order. */
  const anchors = partnerAnchors(focus, partnerColumn);
  const timed: { nodeId: string; at: number; phase: number; index: number }[] = [];
  const untimedWork: string[] = [];
  focus.partners.forEach((partner, index) => {
    const at = anchors.get(partner.participantId);
    if (at !== undefined) timed.push({ nodeId: `partner:${partner.participantId}`, at, phase: 0, index });
  });
  focus.workItems.forEach((item, index) => {
    const at = realTime(item.updatedAtMs);
    if (at !== undefined) timed.push({ nodeId: `work:${item.id}`, at, phase: 1, index });
    else untimedWork.push(`work:${item.id}`);
  });
  timed.sort((left, right) => left.at - right.at || left.phase - right.phase || left.index - right.index);
  const rowById = new Map<string, number>();
  timed.forEach((entry, order) => rowById.set(entry.nodeId, order + 1));
  untimedWork.forEach((nodeId, order) => rowById.set(nodeId, timed.length + 1 + order));
  const rowCount = 1 + timed.length + untimedWork.length;
  const height = Math.max(MIN_HEIGHT, ROW_TOP + (rowCount - 1) * ROW_STEP + ROW_BOTTOM);
  const rowY = (row: number) => round(ROW_TOP + row * ROW_STEP);

  const nodes: RoomFocusMeshNode[] = [{
    id: 'root',
    kind: 'root',
    refId: '',
    x: laneX(0),
    y: rowY(0),
    state: focus.goal.state,
    label: focus.goal.title,
  }];
  focus.partners.forEach((partner, index) => {
    nodes.push({
      id: `partner:${partner.participantId}`,
      kind: 'partner',
      refId: partner.participantId,
      x: laneX(index + 1),
      /* No recorded involvement → the partner waits on the origin row. */
      y: rowY(rowById.get(`partner:${partner.participantId}`) ?? 0),
      state: partner.state,
      label: partner.celestialName,
      sublabel: partner.displayName,
      tone: index % 4,
    });
  });
  const workById = new Map(focus.workItems.map((item) => [item.id, item]));
  for (const item of focus.workItems) {
    nodes.push({
      id: `work:${item.id}`,
      kind: 'work',
      refId: item.id,
      x: laneX(workColumn(item, workById, partnerColumn)),
      y: rowY(rowById.get(`work:${item.id}`)!),
      state: item.state,
      label: item.objective,
      ...(item.wave
        ? { sublabel: `∥ 轨道 ${Math.max(item.wave.parallelIndex, 0) + 1}/${Math.max(item.wave.parallelSize, 1)}` }
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

  const lanes: RoomFocusMeshLane[] = [{ id: 'root', x: laneX(0), y0: rowY(0), y1: height - 4 }];
  for (const partner of focus.partners) {
    const node = byId.get(`partner:${partner.participantId}`)!;
    lanes.push({ id: partner.participantId, x: node.x, y0: node.y, y1: height - 4 });
  }

  const present = new Set([...edges.values()].map((edge) => edge.kind));
  return {
    nodes,
    edges: [...edges.values()],
    edgeKinds: EDGE_KIND_ORDER.filter((kind) => present.has(kind)),
    lanes,
    height,
  };
}

/** Earliest recorded time a partner is named by an authoritative field:
 * WorkItem roles at updatedAtMs, handoffs at createdAtMs, flow packets at
 * createdAtMs. No record → no anchor; times are never invented. */
function partnerAnchors(
  focus: RoomFocusProjection,
  partnerColumn: Map<string, number>,
): Map<string, number> {
  const anchors = new Map<string, number>();
  const consider = (participantId: string | undefined, at: number) => {
    if (!participantId || !partnerColumn.has(participantId)) return;
    const time = realTime(at);
    if (time === undefined) return;
    const previous = anchors.get(participantId);
    if (previous === undefined || time < previous) anchors.set(participantId, time);
  };
  for (const item of focus.workItems) {
    for (const role of [
      item.ownerParticipantId,
      item.offeredToParticipantId,
      item.accountableParticipantId,
      item.verifierParticipantId,
      item.review?.reviewerParticipantId,
    ]) consider(role, item.updatedAtMs);
  }
  for (const handoff of focus.handoffs) {
    consider(handoff.sourceParticipantId, handoff.createdAtMs);
    consider(handoff.targetParticipantId, handoff.createdAtMs);
  }
  for (const packet of focus.flow) {
    consider(packet.sourceParticipantId, packet.createdAtMs);
    for (const target of packet.targetParticipantIds) consider(target, packet.createdAtMs);
  }
  return anchors;
}

/** A WorkItem lives in its owner's lane, inheriting up the parent chain when
 * unowned. Nothing resolvable keeps it in Sol's origin lane — the parent
 * edge, not a guessed lane, carries the relation. */
function workColumn(
  item: RoomFocusWorkItem,
  workById: Map<string, RoomFocusWorkItem>,
  partnerColumn: Map<string, number>,
): number {
  const seen = new Set<string>();
  let current: RoomFocusWorkItem | undefined = item;
  while (current && !seen.has(current.id)) {
    seen.add(current.id);
    const owner = current.ownerParticipantId
      || current.offeredToParticipantId
      || current.accountableParticipantId;
    const column = owner ? partnerColumn.get(owner) : undefined;
    if (column !== undefined) return column;
    current = current.parentId ? workById.get(current.parentId) : undefined;
  }
  return 0;
}

/** Signed perpendicular bow per kind: ownership stays a straight drop inside
 * the lane; review and accountability bow to opposite sides so both stay
 * legible on the same endpoints; handoffs bow widest with a direction tip. */
const EDGE_BOW: Record<RoomFocusMeshEdgeKind, number> = {
  ownership: 0,
  accountable: -5,
  review: 5,
  parent: 3,
  handoff: 7,
};

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
  const chord = { x: target.x - source.x, y: target.y - source.y };
  const length = Math.hypot(chord.x, chord.y) || 1;
  const bow = EDGE_BOW[kind];
  return {
    x: round(mid.x + (-chord.y / length) * bow),
    y: round(mid.y + (chord.x / length) * bow),
  };
}

function realTime(value: number): number | undefined {
  return Number.isFinite(value) && value > 0 ? value : undefined;
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}
