import {
  roomFocusStateLabel,
  type RoomFocusHandoff,
  type RoomFocusPacket,
  type RoomFocusPartner,
  type RoomFocusProjection,
  type RoomFocusState,
  type RoomFocusWorkItem,
} from './room-focus-projection';

/** Sol belongs to Room chrome, not to the partner relationship graph. */
export type RoomFocusMeshEdgeKind =
  | 'responsibility'
  | 'dependency'
  | 'dispatch'
  | 'handoff'
  | 'mention'
  | 'request'
  | 'question'
  | 'receipt'
  | 'answer'
  | 'result'
  | 'review';

export interface RoomFocusMeshNode {
  id: string;
  kind: 'partner';
  refId: string;
  x: number;
  y: number;
  state: RoomFocusState;
  label: string;
  sublabel: string;
  responsibility: string;
  tone: number;
}

export type RoomFocusMeshRelationState = RoomFocusState
  | RoomFocusHandoff['state']
  | 'sent'
  | 'delivered'
  | 'received'
  | 'replied'
  | 'accepted'
  | 'confirmed'
  | 'cancelled';

export interface RoomFocusMeshProvenance {
  eventIds: string[];
  workItemIds: string[];
  dispatchIds: string[];
  /** Public evidence refs carried by the event/packet that caused the edge. */
  refs: string[];
}

export interface RoomFocusMeshRelation {
  id: string;
  kind: RoomFocusMeshEdgeKind;
  sourceId: string;
  targetId: string;
  state: RoomFocusMeshRelationState;
  label: string;
  summary: string;
  createdAtMs: number;
  sequence?: number;
  /** The public facts that caused this relation. The graph must never become
   * a second collaboration log; callers can use these ids to return to the
   * authoritative Room flow/work projection. */
  provenance: RoomFocusMeshProvenance;
}

/** A single authoritative attempt behind a visual relation. Multiple
 * confirmed attempts may share one edge, but their state, ordering, summary,
 * timestamp and provenance remain independently inspectable. */
export interface RoomFocusMeshAttempt {
  id: string;
  state: RoomFocusMeshRelationState;
  summary: string;
  createdAtMs: number;
  sequence?: number;
  provenance: RoomFocusMeshProvenance;
}

export interface RoomFocusMeshEdge extends RoomFocusMeshRelation {
  path: string;
  labelX: number;
  labelY: number;
  tip: { x: number; y: number };
  attempts: RoomFocusMeshAttempt[];
}

/** A real relation that is deliberately kept out of the established success
 * DAG: failed/pending attempts and confirmed relations that would introduce a
 * cycle stay inspectable instead of being painted as successful workflow. */
export interface RoomFocusMeshNonDagRelation extends RoomFocusMeshRelation {
  reason: string;
  attempts: RoomFocusMeshAttempt[];
}

type RoomFocusMeshRelationRecord = RoomFocusMeshRelation & {
  order: number;
  attemptId: string;
  insertion: number;
};

type RoomFocusMeshRelationGroup = {
  relation: RoomFocusMeshRelationRecord;
  attempts: RoomFocusMeshRelationRecord[];
};

export interface RoomFocusMesh {
  nodes: RoomFocusMeshNode[];
  edges: RoomFocusMeshEdge[];
  nonDagRelations: RoomFocusMeshNonDagRelation[];
  edgeKinds: RoomFocusMeshEdgeKind[];
  height: number;
}

const X_MARGIN = 5;
const MAX_COLUMNS = 2;
/* ViewBox units scale with canvas width. At the narrow 300px Room panel these
 * values still leave roughly 126px between row centres and 66px below the
 * final centre — enough for the two-line responsibility card without clip. */
const ROW_HEIGHT = 70;
const ROW_TOP = 22;
const MIN_HEIGHT = 64;
const EDGE_KIND_ORDER: RoomFocusMeshEdgeKind[] = [
  'responsibility', 'dependency', 'dispatch', 'handoff', 'mention', 'request', 'question', 'receipt', 'answer', 'result', 'review',
];
/* UR-161's success DAG is the workflow backbone. Public conversational
 * receipts/answers may legitimately travel back to an earlier actor and are
 * retained as confirmed gravity relations without changing that backbone. */
const DAG_EDGE_KINDS = new Set<RoomFocusMeshEdgeKind>([
  'responsibility', 'dependency', 'dispatch', 'handoff', 'review',
]);
const EDGE_BOW: Record<RoomFocusMeshEdgeKind, number> = {
  responsibility: -4,
  dependency: 3,
  dispatch: -5,
  handoff: 7,
  mention: -8,
  request: -2,
  question: -8,
  receipt: 9,
  answer: 9,
  result: 5,
  review: -11,
};
const GENERIC_PARTNER_ACTIONS = new Set([
  '推进中', '进行中', '协作中', '待命', '等待新的工作项',
]);

export function roomFocusMeshEdgeKindLabel(kind: RoomFocusMeshEdgeKind): string {
  return ({
    responsibility: '职责',
    dependency: '任务依赖',
    dispatch: '分派',
    handoff: '交接',
    mention: '@ 提及',
    request: '请求',
    question: '询问',
    receipt: '回执',
    answer: '回复',
    result: '结果',
    review: '复核',
  } satisfies Record<RoomFocusMeshEdgeKind, string>)[kind];
}

export function buildRoomFocusMesh(focus: RoomFocusProjection): RoomFocusMesh {
  const columns = Math.max(1, Math.min(MAX_COLUMNS, focus.partners.length));
  const rows = Math.max(1, Math.ceil(focus.partners.length / columns));
  let height = Math.max(MIN_HEIGHT, ROW_TOP * 2 + (rows - 1) * ROW_HEIGHT);
  const nodes = focus.partners.map((partner, index): RoomFocusMeshNode => ({
    id: partnerId(partner.participantId),
    kind: 'partner',
    refId: partner.participantId,
    x: round(X_MARGIN + ((index % columns + 0.5) * (100 - X_MARGIN * 2)) / columns),
    y: round(ROW_TOP + Math.floor(index / columns) * ROW_HEIGHT),
    state: partner.state,
    label: partner.celestialName,
    sublabel: roomFocusStateLabel(partner.state),
    responsibility: partnerResponsibility(partner, focus.workItems),
    tone: index % 4,
  }));
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const partnerIds = new Set(focus.partners.map((partner) => partner.participantId));
  const relations = new Map<string, RoomFocusMeshRelationRecord[]>();
  let relationInsertion = 0;

  const connect = (
    kind: RoomFocusMeshEdgeKind,
    sourceParticipantId: string | undefined,
    targetParticipantId: string | undefined,
    state: RoomFocusMeshRelationState,
    details: {
      provenance?: Partial<RoomFocusMeshProvenance>;
      order?: number;
      summary?: string;
      createdAtMs?: number;
      sequence?: number;
    } = {},
  ) => {
    if (!sourceParticipantId || !targetParticipantId || sourceParticipantId === targetParticipantId) return;
    if (!partnerIds.has(sourceParticipantId) || !partnerIds.has(targetParticipantId)) return;
    const sourceId = partnerId(sourceParticipantId);
    const targetId = partnerId(targetParticipantId);
    const id = `${kind}:${sourceId}->${targetId}`;
    const eventIds = details.provenance?.eventIds ?? [];
    const workItemIds = details.provenance?.workItemIds ?? [];
    const dispatchIds = details.provenance?.dispatchIds ?? [];
    const refs = details.provenance?.refs ?? [];
    const order = details.order ?? details.createdAtMs ?? 0;
    const createdAtMs = details.createdAtMs ?? order;
    const provenanceId = eventIds[0] || workItemIds[0] || dispatchIds[0] || `${relationInsertion}`;
    const attempt: RoomFocusMeshRelationRecord = {
      id, kind, sourceId, targetId, state, label: roomFocusMeshEdgeKindLabel(kind),
      summary: details.summary?.trim() || roomFocusMeshEdgeKindLabel(kind),
      createdAtMs,
      ...(details.sequence === undefined ? {} : { sequence: details.sequence }),
      order,
      attemptId: `${id}:attempt:${provenanceId}:${relationInsertion}`,
      insertion: relationInsertion,
      provenance: {
        eventIds: unique(eventIds),
        workItemIds: unique(workItemIds),
        dispatchIds: unique(dispatchIds),
        refs: unique(refs),
      },
    };
    relationInsertion += 1;
    const attempts = relations.get(id) ?? [];
    attempts.push(attempt);
    relations.set(id, attempts);
  };

  /* WorkItems are structural task-sheet/detail records. Only the public
   * handoff and flow projections below carry event provenance, so a task row
   * cannot become a fabricated gravity edge, failed attempt, or DAG relation. */
  for (const handoff of focus.handoffs) {
    connect('handoff', handoff.sourceParticipantId, handoff.targetParticipantId, handoff.state, {
      provenance: {
        eventIds: [handoff.id],
        ...(handoff.workItemId ? { workItemIds: [handoff.workItemId] } : {}),
        ...(handoff.dispatchId ? { dispatchIds: [handoff.dispatchId] } : {}),
      },
      order: handoff.createdAtMs,
      summary: handoff.task || handoff.artifactOrContract || '交接',
      createdAtMs: handoff.createdAtMs,
    });
  }
  for (const packet of focus.flow) {
    const kind = packetEdgeKind(packet);
    if (!kind) continue;
    for (const targetId of packet.targetParticipantIds) {
      if (packet.sourceParticipantId === 'root' || targetId === 'root') continue;
      connect(kind, packet.sourceParticipantId, targetId, packetState(packet), {
        provenance: {
          eventIds: [packet.id],
          ...(packet.workItemId ? { workItemIds: [packet.workItemId] } : {}),
          ...(packet.dispatchId ? { dispatchIds: [packet.dispatchId] } : {}),
          refs: packet.refs,
        },
        order: packet.sequence ?? packet.createdAtMs,
        summary: packet.summary,
        createdAtMs: packet.createdAtMs,
        sequence: packet.sequence,
      });
    }
  }

  const nonDagRelations: RoomFocusMeshNonDagRelation[] = [];
  const candidateGroups = [...relations.values()].flatMap((attempts): RoomFocusMeshRelationGroup[] => {
    const confirmed = attempts.filter(isConfirmedRelation).sort(compareRelations);
    for (const attempt of attempts.filter((candidate) => !isConfirmedRelation(candidate))) {
      nonDagRelations.push(toNonDagRelation(attempt, nonDagReason(attempt.state)));
    }
    if (!confirmed.length) return [];
    return [{ relation: mergeConfirmedRelations(confirmed), attempts: confirmed }];
  }).sort((left, right) => compareRelations(left.relation, right.relation));
  const establishedGroups: RoomFocusMeshRelationGroup[] = [];
  for (const group of candidateGroups) {
    const relation = group.relation;
    if (
      DAG_EDGE_KINDS.has(relation.kind)
      && createsDagCycle(establishedGroups.map(({ relation: established }) => established), relation)
    ) {
      for (const attempt of group.attempts) {
        nonDagRelations.push(toNonDagRelation(
          attempt,
          '确认关系未纳入成功 DAG：加入后会形成循环',
        ));
      }
      continue;
    }
    establishedGroups.push(group);
  }

  /* Once the authoritative success DAG is known, place partners in readable
   * top-to-bottom layers. Disconnected partners retain the stable two-column
   * roster order; a confirmed handoff/dispatch/review moves its target below
   * the source so the graph reads like a workflow instead of a tangled web. */
  height = layoutMeshNodes(nodes, establishedGroups);

  const labelBuckets = new Map<string, number>();
  const edges = establishedGroups.map(({ relation, attempts }): RoomFocusMeshEdge => {
    const source = nodeById.get(relation.sourceId)!;
    const target = nodeById.get(relation.targetId)!;
    const control = curveControl(source, target, relation.kind);
    const arrowT = 0.78;
    const tip = quadraticPoint(source, control, target, arrowT);
    const midpoint = quadraticPoint(source, control, target, 0.5);
    const labelBucket = `${Math.round(midpoint.x / 8)}:${Math.round(midpoint.y / 8)}`;
    const bucketIndex = labelBuckets.get(labelBucket) ?? 0;
    labelBuckets.set(labelBucket, bucketIndex + 1);
    const labelY = clampNumber(
      midpoint.y + (bucketIndex % 2 === 0 ? 1 : -1) * Math.ceil((bucketIndex + 1) / 2) * 9,
      ROW_TOP - 8,
      height - ROW_TOP + 8,
    );
    return {
      id: relation.id,
      kind: relation.kind,
      sourceId: relation.sourceId,
      targetId: relation.targetId,
      state: relation.state,
      label: relation.label,
      summary: relation.summary,
      createdAtMs: relation.createdAtMs,
      ...(relation.sequence === undefined ? {} : { sequence: relation.sequence }),
      provenance: relation.provenance,
      attempts: attempts.map(toAttemptReceipt),
      /* Split the same quadratic curve at the arrow point. SVG marker-mid can
       * then show direction before the target planet instead of disappearing
       * under its card, while both curve segments remain tangent-continuous. */
      path: quadraticSplitPath(source, control, target, arrowT),
      labelX: midpoint.x,
      labelY,
      tip,
    };
  });
  const presentKinds = new Set(edges.map((edge) => edge.kind));
  return {
    nodes,
    edges,
    nonDagRelations: nonDagRelations.sort(compareNonDagRelations),
    edgeKinds: EDGE_KIND_ORDER.filter((kind) => presentKinds.has(kind)),
    height,
  };
}

function layoutMeshNodes(
  nodes: RoomFocusMeshNode[],
  establishedGroups: readonly RoomFocusMeshRelationGroup[],
): number {
  if (!nodes.length) return MIN_HEIGHT;
  const rank = new Map(nodes.map((node) => [node.id, 0]));
  const outgoing = new Map<string, string[]>();
  const indegree = new Map(nodes.map((node) => [node.id, 0]));
  for (const { relation } of establishedGroups) {
    if (!DAG_EDGE_KINDS.has(relation.kind)) continue;
    const targets = outgoing.get(relation.sourceId) ?? [];
    if (targets.includes(relation.targetId)) continue;
    targets.push(relation.targetId);
    outgoing.set(relation.sourceId, targets);
    indegree.set(relation.targetId, (indegree.get(relation.targetId) ?? 0) + 1);
  }

  const queue = nodes
    .filter((node) => (indegree.get(node.id) ?? 0) === 0)
    .sort((left, right) => left.id.localeCompare(right.id));
  let visited = 0;
  while (queue.length) {
    const source = queue.shift()!;
    visited += 1;
    const sourceRank = rank.get(source.id) ?? 0;
    for (const targetId of outgoing.get(source.id) ?? []) {
      rank.set(targetId, Math.max(rank.get(targetId) ?? 0, sourceRank + 1));
      const nextDegree = (indegree.get(targetId) ?? 1) - 1;
      indegree.set(targetId, nextDegree);
      if (nextDegree === 0) queue.push(nodes.find((node) => node.id === targetId)!);
    }
  }
  /* The success DAG cycle guard should make this unreachable. If a future
     relation kind bypasses that guard, keep the layout deterministic rather
     than leaving a node at an arbitrary position. */
  if (visited < nodes.length) {
    for (const node of nodes) if ((indegree.get(node.id) ?? 0) > 0) rank.set(node.id, 0);
  }

  const hasWorkflowLayers = [...rank.values()].some((value) => value > 0);
  const orderedRanks = hasWorkflowLayers
    ? [...new Set(nodes.map((node) => rank.get(node.id) ?? 0))].sort((left, right) => left - right)
    : [0];
  let row = 0;
  for (const rankValue of orderedRanks) {
    const layer = nodes.filter((node) => (hasWorkflowLayers ? rank.get(node.id) === rankValue : true));
    for (let offset = 0; offset < layer.length; offset += MAX_COLUMNS) {
      const chunk = layer.slice(offset, offset + MAX_COLUMNS);
      chunk.forEach((node, index) => {
        const columns = Math.max(2, chunk.length);
        node.x = round(X_MARGIN + ((index + 0.5) * (100 - X_MARGIN * 2)) / columns);
        node.y = round(ROW_TOP + row * ROW_HEIGHT);
      });
      row += 1;
    }
  }
  return Math.max(MIN_HEIGHT, ROW_TOP * 2 + Math.max(0, row - 1) * ROW_HEIGHT);
}

function isConfirmedRelation(relation: RoomFocusMeshRelationRecord): boolean {
  return relation.state === 'completed' || relation.state === 'confirmed';
}

function mergeConfirmedRelations(
  relations: RoomFocusMeshRelationRecord[],
): RoomFocusMeshRelationRecord {
  const ordered = relations.slice().sort(compareRelations);
  const latest = ordered.at(-1)!;
  return {
    ...latest,
    provenance: {
      eventIds: unique(ordered.flatMap((relation) => relation.provenance.eventIds)),
      workItemIds: unique(ordered.flatMap((relation) => relation.provenance.workItemIds)),
      dispatchIds: unique(ordered.flatMap((relation) => relation.provenance.dispatchIds)),
      refs: unique(ordered.flatMap((relation) => relation.provenance.refs)),
    },
  };
}

function toNonDagRelation(
  relation: RoomFocusMeshRelationRecord,
  reason: string,
): RoomFocusMeshNonDagRelation {
  return {
    id: relation.attemptId,
    kind: relation.kind,
    sourceId: relation.sourceId,
    targetId: relation.targetId,
    state: relation.state,
    label: relation.label,
    summary: relation.summary,
    createdAtMs: relation.createdAtMs,
    ...(relation.sequence === undefined ? {} : { sequence: relation.sequence }),
    reason,
    provenance: relation.provenance,
    attempts: [toAttemptReceipt(relation)],
  };
}

function toAttemptReceipt(relation: RoomFocusMeshRelationRecord): RoomFocusMeshAttempt {
  return {
    id: relation.attemptId,
    state: relation.state,
    summary: relation.summary,
    createdAtMs: relation.createdAtMs,
    ...(relation.sequence === undefined ? {} : { sequence: relation.sequence }),
    provenance: {
      eventIds: [...relation.provenance.eventIds],
      workItemIds: [...relation.provenance.workItemIds],
      dispatchIds: [...relation.provenance.dispatchIds],
      refs: [...relation.provenance.refs],
    },
  };
}

function compareRelations(
  left: RoomFocusMeshRelationRecord,
  right: RoomFocusMeshRelationRecord,
): number {
  return left.order - right.order
    || left.createdAtMs - right.createdAtMs
    || left.insertion - right.insertion
    || left.id.localeCompare(right.id);
}

function compareNonDagRelations(
  left: RoomFocusMeshNonDagRelation,
  right: RoomFocusMeshNonDagRelation,
): number {
  return left.createdAtMs - right.createdAtMs
    || (left.sequence ?? Number.MAX_SAFE_INTEGER) - (right.sequence ?? Number.MAX_SAFE_INTEGER)
    || left.id.localeCompare(right.id);
}

function nonDagReason(state: RoomFocusMeshRelationState): string {
  if (state === 'failed') return '失败尝试，未建立成功关系';
  if (state === 'blocked') return '已阻塞，未建立成功关系';
  if (state === 'stopped' || state === 'cancelled') return '已取消或停止，未建立成功关系';
  if (state === 'sent') return '已发送，尚未确认送达';
  if (state === 'delivered') return '已送达，尚未确认接收';
  if (state === 'received') return '已接收，尚未确认回复';
  if (state === 'replied') return '已回复，尚未确认完成';
  if (state === 'accepted') return '已接受，尚未确认完成';
  return '尚未确认，未建立成功关系';
}

function createsDagCycle(
  establishedRelations: readonly RoomFocusMeshRelationRecord[],
  candidate: RoomFocusMeshRelationRecord,
): boolean {
  const outgoing = new Map<string, string[]>();
  for (const relation of establishedRelations) {
    if (!DAG_EDGE_KINDS.has(relation.kind)) continue;
    const targets = outgoing.get(relation.sourceId) ?? [];
    targets.push(relation.targetId);
    outgoing.set(relation.sourceId, targets);
  }
  const pending = [candidate.targetId];
  const visited = new Set<string>();
  while (pending.length) {
    const current = pending.pop()!;
    if (current === candidate.sourceId) return true;
    if (visited.has(current)) continue;
    visited.add(current);
    pending.push(...(outgoing.get(current) ?? []));
  }
  return false;
}

function partnerResponsibility(partner: RoomFocusPartner, workItems: readonly RoomFocusWorkItem[]): string {
  const objective = workItems.find((item) => workOwner(item) === partner.participantId)?.objective.trim();
  if (objective) return objective;
  const currentAction = partner.currentAction.trim();
  if (currentAction && !GENERIC_PARTNER_ACTIONS.has(currentAction)) return currentAction;
  const role = ({
    coordinator: '协调与汇合',
    researcher: '研究与证据',
    implementer: '实现与交付',
    reviewer: '独立复核',
    specialist: '专项支持',
  } as Record<string, string>)[partner.collaborationRole ?? ''];
  return role || currentAction || '等待分工';
}

function workOwner(item: RoomFocusWorkItem | undefined): string | undefined {
  return item?.ownerParticipantId || item?.offeredToParticipantId;
}

/** Map only public packet facts to graph relations. A request addressed by one
 * Partner to another is the projected form of a direct @/ask; a result is a
 * delivered answer/result. Root-directed packets are filtered by connect(). */
function packetEdgeKind(packet: RoomFocusPacket): RoomFocusMeshEdgeKind | undefined {
  const edgeKinds: Partial<Record<RoomFocusPacket['kind'], RoomFocusMeshEdgeKind>> = {
    request: 'mention',
    intercom: 'request',
    dispatch: 'dispatch',
    question: 'question',
    answer: 'receipt',
    result: 'result',
    review: 'review',
  };
  return edgeKinds[packet.kind];
}

function packetState(packet: RoomFocusPacket): RoomFocusMeshRelationState {
  const status = packet.status.trim().toLowerCase();
  if (status === 'failed') return 'failed';
  if (['stopped', 'aborted'].includes(status)) return 'stopped';
  if (status === 'cancelled') return 'cancelled';
  if (status === 'completed' || status === 'done') return 'completed';
  if (status === 'confirmed' || status === 'success' || status === 'succeeded') return 'confirmed';
  if (status === 'accepted') return 'accepted';
  if (status === 'received') return 'received';
  if (status === 'replied') return 'replied';
  if (status === 'delivered') return 'delivered';
  if (status === 'sent') return 'sent';
  if (['waiting', 'queued', 'pending'].includes(status)) return 'waiting';
  return 'running';
}

function partnerId(participantId: string): string {
  return `partner:${participantId}`;
}

function curveControl(
  source: Pick<RoomFocusMeshNode, 'x' | 'y'>,
  target: Pick<RoomFocusMeshNode, 'x' | 'y'>,
  kind: RoomFocusMeshEdgeKind,
) {
  const chord = { x: target.x - source.x, y: target.y - source.y };
  const length = Math.hypot(chord.x, chord.y) || 1;
  const bow = EDGE_BOW[kind];
  return {
    x: round((source.x + target.x) / 2 + (-chord.y / length) * bow),
    y: round((source.y + target.y) / 2 + (chord.x / length) * bow),
  };
}

function quadraticPoint(
  source: Pick<RoomFocusMeshNode, 'x' | 'y'>,
  control: { x: number; y: number },
  target: Pick<RoomFocusMeshNode, 'x' | 'y'>,
  t: number,
) {
  const inverse = 1 - t;
  return {
    x: round(inverse * inverse * source.x + 2 * inverse * t * control.x + t * t * target.x),
    y: round(inverse * inverse * source.y + 2 * inverse * t * control.y + t * t * target.y),
  };
}

function quadraticSplitPath(
  source: Pick<RoomFocusMeshNode, 'x' | 'y'>,
  control: { x: number; y: number },
  target: Pick<RoomFocusMeshNode, 'x' | 'y'>,
  t: number,
): string {
  const firstControl = {
    x: round(source.x + (control.x - source.x) * t),
    y: round(source.y + (control.y - source.y) * t),
  };
  const secondControl = {
    x: round(control.x + (target.x - control.x) * t),
    y: round(control.y + (target.y - control.y) * t),
  };
  const split = {
    x: round(firstControl.x + (secondControl.x - firstControl.x) * t),
    y: round(firstControl.y + (secondControl.y - firstControl.y) * t),
  };
  return `M ${source.x} ${source.y} Q ${firstControl.x} ${firstControl.y} ${split.x} ${split.y} Q ${secondControl.x} ${secondControl.y} ${target.x} ${target.y}`;
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}

function clampNumber(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}
