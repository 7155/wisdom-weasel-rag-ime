import type {
  RoomFocusHandoff,
  RoomFocusPacket,
  RoomFocusPartner,
  RoomFocusProjection,
  RoomFocusState,
  RoomFocusWorkItem,
} from './room-focus-projection';

/** Sol belongs to Room chrome, not to the partner relationship graph. */
export type RoomFocusMeshEdgeKind =
  | 'responsibility'
  | 'dependency'
  | 'handoff'
  | 'question'
  | 'answer'
  | 'review';

export interface RoomFocusMeshNode {
  id: string;
  kind: 'partner';
  refId: string;
  x: number;
  y: number;
  state: RoomFocusState;
  label: string;
  responsibility: string;
  tone: number;
}

export interface RoomFocusMeshEdge {
  id: string;
  kind: RoomFocusMeshEdgeKind;
  sourceId: string;
  targetId: string;
  state: RoomFocusState | RoomFocusHandoff['state'];
  path: string;
  label: string;
  labelX: number;
  labelY: number;
  tip: { x: number; y: number };
}

export interface RoomFocusMesh {
  nodes: RoomFocusMeshNode[];
  edges: RoomFocusMeshEdge[];
  edgeKinds: RoomFocusMeshEdgeKind[];
  height: number;
}

const X_MARGIN = 5;
const MAX_COLUMNS = 4;
const ROW_HEIGHT = 36;
const ROW_TOP = 20;
const MIN_HEIGHT = 58;
const EDGE_KIND_ORDER: RoomFocusMeshEdgeKind[] = [
  'responsibility', 'dependency', 'handoff', 'question', 'answer', 'review',
];
const EDGE_BOW: Record<RoomFocusMeshEdgeKind, number> = {
  responsibility: -4,
  dependency: 3,
  handoff: 7,
  question: -8,
  answer: 9,
  review: -11,
};

export function roomFocusMeshEdgeKindLabel(kind: RoomFocusMeshEdgeKind): string {
  return ({
    responsibility: '职责',
    dependency: '任务依赖',
    handoff: '交接',
    question: '询问',
    answer: '回复',
    review: '复核',
  } satisfies Record<RoomFocusMeshEdgeKind, string>)[kind];
}

export function buildRoomFocusMesh(focus: RoomFocusProjection): RoomFocusMesh {
  const columns = Math.max(1, Math.min(MAX_COLUMNS, focus.partners.length));
  const rows = Math.max(1, Math.ceil(focus.partners.length / columns));
  const height = Math.max(MIN_HEIGHT, ROW_TOP * 2 + (rows - 1) * ROW_HEIGHT);
  const nodes = focus.partners.map((partner, index): RoomFocusMeshNode => ({
    id: partnerId(partner.participantId),
    kind: 'partner',
    refId: partner.participantId,
    x: round(X_MARGIN + ((index % columns + 0.5) * (100 - X_MARGIN * 2)) / columns),
    y: round(ROW_TOP + Math.floor(index / columns) * ROW_HEIGHT),
    state: partner.state,
    label: partner.celestialName,
    responsibility: partnerResponsibility(partner, focus.workItems),
    tone: index % 4,
  }));
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const partnerIds = new Set(focus.partners.map((partner) => partner.participantId));
  const workById = new Map(focus.workItems.map((item) => [item.id, item]));
  const relations = new Map<string, Omit<RoomFocusMeshEdge, 'path' | 'labelX' | 'labelY' | 'tip'>>();

  const connect = (
    kind: RoomFocusMeshEdgeKind,
    sourceParticipantId: string | undefined,
    targetParticipantId: string | undefined,
    state: RoomFocusMeshEdge['state'],
  ) => {
    if (!sourceParticipantId || !targetParticipantId || sourceParticipantId === targetParticipantId) return;
    if (!partnerIds.has(sourceParticipantId) || !partnerIds.has(targetParticipantId)) return;
    const sourceId = partnerId(sourceParticipantId);
    const targetId = partnerId(targetParticipantId);
    const id = `${kind}:${sourceId}->${targetId}`;
    if (relations.has(id)) return;
    relations.set(id, {
      id, kind, sourceId, targetId, state, label: roomFocusMeshEdgeKindLabel(kind),
    });
  };

  for (const item of focus.workItems) {
    const ownerId = workOwner(item);
    connect('responsibility', item.accountableParticipantId, ownerId, item.state);
    const parent = item.parentId ? workById.get(item.parentId) : undefined;
    connect('dependency', workOwner(parent), ownerId, item.state);
    connect('review', item.review?.reviewerParticipantId || item.verifierParticipantId, ownerId, item.state);
  }
  for (const handoff of focus.handoffs) {
    connect('handoff', handoff.sourceParticipantId, handoff.targetParticipantId, handoff.state);
  }
  for (const packet of focus.flow) {
    if (packet.kind !== 'question' && packet.kind !== 'answer') continue;
    for (const targetId of packet.targetParticipantIds) {
      if (packet.sourceParticipantId === 'root' || targetId === 'root') continue;
      connect(packet.kind, packet.sourceParticipantId, targetId, packetState(packet));
    }
  }

  const edges = [...relations.values()].map((relation): RoomFocusMeshEdge => {
    const source = nodeById.get(relation.sourceId)!;
    const target = nodeById.get(relation.targetId)!;
    const control = curveControl(source, target, relation.kind);
    return {
      ...relation,
      path: `M ${source.x} ${source.y} Q ${control.x} ${control.y} ${target.x} ${target.y}`,
      labelX: quadraticPoint(source, control, target, 0.5).x,
      labelY: quadraticPoint(source, control, target, 0.5).y,
      tip: quadraticPoint(source, control, target, 0.78),
    };
  });
  const presentKinds = new Set(edges.map((edge) => edge.kind));
  return {
    nodes,
    edges,
    edgeKinds: EDGE_KIND_ORDER.filter((kind) => presentKinds.has(kind)),
    height,
  };
}

function partnerResponsibility(partner: RoomFocusPartner, workItems: readonly RoomFocusWorkItem[]): string {
  const objective = workItems.find((item) => workOwner(item) === partner.participantId)?.objective.trim();
  if (objective) return objective;
  const role = ({
    coordinator: '协调与汇合',
    researcher: '研究与证据',
    implementer: '实现与交付',
    reviewer: '独立复核',
    specialist: '专项支持',
  } as Record<string, string>)[partner.collaborationRole ?? ''];
  return role || partner.currentAction.trim() || '等待分工';
}

function workOwner(item: RoomFocusWorkItem | undefined): string | undefined {
  return item?.ownerParticipantId || item?.offeredToParticipantId;
}

function packetState(packet: RoomFocusPacket): RoomFocusState {
  if (packet.status === 'failed') return 'failed';
  if (packet.status === 'stopped' || packet.status === 'cancelled') return 'stopped';
  if (['completed', 'delivered', 'replied'].includes(packet.status)) return 'completed';
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

function round(value: number): number {
  return Math.round(value * 100) / 100;
}
