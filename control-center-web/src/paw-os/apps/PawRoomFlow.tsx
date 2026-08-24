import {
  CircleHelp,
  ChevronRight,
  FileText,
  GitBranch,
  MessageCircle,
  Route,
  Send,
  ShieldCheck,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import type {
  RoomActivityProjection,
  RoomMessageProjection,
  RoomProjectionState,
} from '@/contracts/room-reducer';
import type { RoomSummary, RoomWorkItem } from '@/features/rooms/room-types';
import { roomActivityFlowKind, roomFlowRefs, type RoomActivityFlowKind } from '@/features/rooms/room-flow-projection';
import { SmoothDisclosureReveal } from '@/features/agent/timeline/SmoothDisclosureReveal';
import { toggleDisclosurePreservingAnchor } from '@/features/agent/timeline/disclosure-anchor';

type FlowActorId = 'root' | string;
type FlowPacketKind = 'request' | 'question' | 'answer' | 'plan' | 'document' | 'context' | 'result' | 'dispatch' | 'approval';

type RoomFlowPacket = {
  id: string;
  sourceId: FlowActorId;
  targetIds: FlowActorId[];
  kind: FlowPacketKind;
  summary: string;
  status: string;
  createdAtMs: number;
  sequence: number;
  dispatchId?: string;
  workItemId?: string;
  refs: string[];
};

export function PawRoomFlow({
  projection,
  room,
}: {
  projection?: RoomProjectionState;
  room: RoomSummary;
}) {
  const packets = useMemo(() => roomFlowPackets(room, projection), [projection, room]);
  const [selectedPacketId, setSelectedPacketId] = useState('');
  const [showAllPackets, setShowAllPackets] = useState(false);
  useEffect(() => setShowAllPackets(false), [room.id]);
  const selectedPacket = packets.find((packet) => packet.id === selectedPacketId) ?? packets.at(-1);
  const visiblePackets = showAllPackets ? packets : packets.slice(-FLOW_PACKET_WINDOW);

  return (
    <section className="paw-room-flow paw-room-flow--migrated-v1" aria-label="Room 消息与上下文流" data-empty={!packets.length || undefined}>
      <section className="paw-room-flow__stage" aria-label="Room 工作树">
        <header>
          <div>
            <strong>协作路径</strong>
            <span>{room.workItems?.length ?? 0} 个 WorkItem · {room.participants.filter((participant) => participant.status === 'active').length} 位伙伴</span>
          </div>
          <small>来自当前 Room 的 WorkItem 与公开事件</small>
        </header>
        <RoomWorkTree room={room} />
      </section>
      <aside className="paw-room-flow__ledger">
        <header>
          <span><GitBranch size={15} /><strong>消息流</strong></span>
          <span className="paw-room-flow__window"><small>最近 {visiblePackets.length} / 共 {packets.length} 条</small>{packets.length > visiblePackets.length ? <button onClick={() => setShowAllPackets(true)} type="button">显示全部</button> : null}</span>
        </header>
        <div className="paw-room-flow__packets">
          {visiblePackets.map((packet) => (
            <button
              aria-current={packet.id === selectedPacket?.id || undefined}
              data-kind={packet.kind}
              data-status={packet.status}
              key={packet.id}
              onClick={() => setSelectedPacketId(packet.id)}
              type="button"
            >
              <span>{packetIcon(packet.kind)}</span>
              <div>
                <strong>{packetKindLabel(packet.kind)}</strong>
                <p>{packet.summary}</p>
                <small>#{packet.sequence} · {actorName(room, packet.sourceId)} → {packet.targetIds.map((id) => actorName(room, id)).join('、') || 'Room'} · {clock(packet.createdAtMs)}</small>
              </div>
            </button>
          ))}
          {!packets.length ? <p className="paw-room-flow__empty">还没有可投影的公开消息、分派或上下文流转。</p> : null}
        </div>
        {selectedPacket ? (
          <section className="paw-room-flow__detail">
            <header><strong>{packetKindLabel(selectedPacket.kind)}</strong><span data-status={selectedPacket.status}>{flowStatusLabel(selectedPacket.status)}</span></header>
            <p>{selectedPacket.summary}</p>
            <dl>
              {selectedPacket.dispatchId ? <><dt>Dispatch</dt><dd>{selectedPacket.dispatchId}</dd></> : null}
              {selectedPacket.workItemId ? <><dt>WorkItem</dt><dd>{selectedPacket.workItemId}</dd></> : null}
              {selectedPacket.refs.length ? <><dt>上下文 / 文档</dt><dd>{selectedPacket.refs.join('\n')}</dd></> : null}
            </dl>
          </section>
        ) : null}
      </aside>
    </section>
  );
}

function RoomWorkTree({ room }: { room: RoomSummary }) {
  const workItems = room.workItems ?? [];
  const ids = new Set(workItems.map((item) => item.id));
  const roots = workItems.filter((item) => !item.parentWorkId || !ids.has(item.parentWorkId));
  const completed = workItems.filter((item) => item.state === 'done').length;
  return (
    <div className="paw-room-work-tree" data-empty={!workItems.length || undefined}>
      <article className="paw-room-work-tree__root">
        <span><Route aria-hidden="true" size={15} /></span>
        <div>
          <strong>{room.description || room.title}</strong>
          <small>{workItems.length ? `${completed}/${workItems.length} 项完成` : '等待真实 WorkItem'}</small>
        </div>
      </article>
      {roots.length ? (
        <ol className="paw-room-work-tree__branches">
          {roots.map((item) => <RoomWorkBranch item={item} key={item.id} room={room} workItems={workItems} />)}
        </ol>
      ) : <p>当前 Room 还没有已接受的 WorkItem。消息流会保留，但不会用静态阶段冒充分工。</p>}
    </div>
  );
}

const FLOW_PACKET_WINDOW = 18;

function RoomWorkBranch({ item, room, workItems }: { item: RoomWorkItem; room: RoomSummary; workItems: RoomWorkItem[] }) {
  const children = workItems.filter((candidate) => candidate.parentWorkId === item.id);
  const ownerId = item.currentOwnerParticipantId || item.offeredToParticipantId || item.accountableParticipantId;
  const owner = room.participants.find((participant) => participant.id === ownerId)?.displayName || '待认领';
  const active = ['queued', 'active', 'review', 'blocked'].includes(item.state);
  const references = [...item.artifactRefs, ...item.evidenceRefs];
  return (
    <li data-state={item.state}>
      <RoomFlowDisclosure active={active} contentId={`room-work-${item.id}`} summary={(
        <>
          <ChevronRight aria-hidden="true" size={14} />
          <span className="paw-room-work-tree__state"><i />{flowStatusLabel(item.state)}</span>
          <strong>{item.objective}</strong>
          <small>{owner}</small>
        </>
      )}>
        <div className="paw-room-work-tree__detail">
          {item.expectedOutput ? <p>{item.expectedOutput}</p> : null}
          {item.acceptanceCriteria.length ? <ul>{item.acceptanceCriteria.map((criterion) => <li key={criterion}>{criterion}</li>)}</ul> : null}
          {references.length ? <small>{references.join(' · ')}</small> : null}
        </div>
        {children.length ? <ol className="paw-room-work-tree__children">{children.map((child) => <RoomWorkBranch item={child} key={child.id} room={room} workItems={workItems} />)}</ol> : null}
      </RoomFlowDisclosure>
    </li>
  );
}

function roomFlowPackets(room: RoomSummary, projection?: RoomProjectionState): RoomFlowPacket[] {
  const packets: RoomFlowPacket[] = [];
  if (projection) {
    for (const activityId of projection.activityOrder) {
      const activity = projection.activitiesById[activityId];
      if (!activity) continue;
      const kind = roomActivityFlowKind(activity);
      if (!kind) continue;
      const isApproval = kind === 'approval';
      const targetId = isApproval ? 'root' : text(activity.payload.targetParticipantId) || activity.participantId || '';
      if (!targetId) continue;
      packets.push(packetFromActivity(activity, targetId, kind));
    }
    for (const messageId of projection.messageOrder) {
      const message = projection.messagesById[messageId];
      if (!message || message.projectionKind === 'execution' || !message.text.trim()) continue;
      const packet = packetFromMessage(message, projection);
      if (packet) packets.push(packet);
    }
  }
  for (const workItem of room.workItems ?? []) packets.push(packetFromWorkItem(workItem));
  return packets
    .sort((left, right) => left.sequence - right.sequence || left.createdAtMs - right.createdAtMs)
    .filter((packet, index, all) => all.findIndex((candidate) => candidate.id === packet.id) === index);
}

function packetFromActivity(activity: RoomActivityProjection, targetId: string, kind: RoomActivityFlowKind): RoomFlowPacket {
  const refs = roomFlowRefs(activity.payload);
  return {
    id: `activity:${activity.id}`,
    sourceId: text(activity.payload.sourceParticipantId)
      || text(activity.payload.actorParticipantId)
      || text(activity.payload.parentParticipantId)
      || (kind === 'approval' ? activity.participantId : '')
      || 'root',
    targetIds: [targetId],
    kind,
    summary: activity.summary || text(activity.payload.reason) || '已确认本轮分工',
    status: activity.status,
    createdAtMs: activity.createdAtMs,
    sequence: activity.sequence ?? activity.createdAtMs,
    dispatchId: text(activity.payload.dispatchId) || undefined,
    workItemId: text(activity.payload.workItemId) || text(activity.payload.taskId) || undefined,
    refs,
  };
}

function packetFromMessage(message: RoomMessageProjection, projection: RoomProjectionState): RoomFlowPacket | undefined {
  const sourceId: FlowActorId = message.role === 'user' ? 'root' : message.participantId || 'root';
  let targetIds: FlowActorId[] = [...(message.mentionedParticipantIds ?? [])];
  let kind: FlowPacketKind = message.role === 'user' ? 'request' : 'result';
  if (message.answerToPostId) {
    const question = projection.messagesById[message.answerToPostId];
    targetIds = question?.participantId ? [question.participantId] : [];
    kind = 'answer';
  } else if (message.question) {
    targetIds = ['root'];
    kind = 'question';
  } else if (message.role === 'assistant' && targetIds.length === 0) {
    targetIds = ['root'];
  }
  const blockKinds = message.message?.blocks.map((block) => block.type) ?? [];
  if (blockKinds.includes('task_plan') || message.postKind === 'plan') kind = 'plan';
  else if (blockKinds.some((blockKind) => ['file', 'artifact', 'diff'].includes(blockKind))) kind = 'document';
  if (sourceId === 'root' && targetIds.length === 0) return undefined;
  return {
    id: `message:${message.id}`,
    sourceId,
    targetIds,
    kind,
    summary: message.text,
    status: message.status,
    createdAtMs: message.createdAtMs,
    sequence: message.sequence ?? message.createdAtMs,
    dispatchId: message.dispatchId,
    refs: messageRefs(message),
  };
}

function packetFromWorkItem(workItem: RoomWorkItem): RoomFlowPacket {
  const targetId = workItem.currentOwnerParticipantId || workItem.offeredToParticipantId || workItem.accountableParticipantId;
  return {
    id: `work:${workItem.id}:${workItem.revision}`,
    sourceId: workItem.createdByParticipantId || 'root',
    targetIds: targetId ? [targetId] : [],
    kind: workItem.artifactRefs.some((ref) => /(?:\.md|document|plan)/iu.test(ref)) ? 'document' : 'plan',
    summary: workItem.objective,
    status: workItem.state,
    createdAtMs: workItem.updatedAtMs || workItem.createdAtMs,
    sequence: (workItem.updatedAtMs || workItem.createdAtMs) + .5,
    workItemId: workItem.id,
    refs: [...workItem.artifactRefs, ...workItem.evidenceRefs],
  };
}

function messageRefs(message: RoomMessageProjection): string[] {
  const refs = message.message?.blocks.flatMap((block) => {
    const data = record(block.data);
    return [text(block.ref), text(data.ref), text(data.path), text(data.documentId), text(data.revision)].filter(Boolean);
  }) ?? [];
  return [...new Set(refs)];
}

function RoomFlowDisclosure({ active, children, contentId, summary }: { active: boolean; children: ReactNode; contentId: string; summary: ReactNode }) {
  const [open, setOpen] = useState(active);
  const manual = useRef(false);
  const wasActive = useRef(active);
  useEffect(() => {
    if (active && !wasActive.current && !manual.current) setOpen(true);
    wasActive.current = active;
  }, [active]);
  return <section className="paw-room-work-tree__disclosure" data-open={open || undefined}>
    <button
      aria-controls={contentId}
      aria-expanded={open}
      className="paw-room-work-tree__summary"
      onClick={(event) => {
        manual.current = true;
        toggleDisclosurePreservingAnchor(event, setOpen);
      }}
      type="button"
    >
      {summary}
    </button>
    <SmoothDisclosureReveal className="paw-room-work-tree__reveal" id={contentId} innerClassName="paw-room-work-tree__reveal-inner" open={open}>{children}</SmoothDisclosureReveal>
  </section>;
}

function packetIcon(kind: FlowPacketKind): ReactNode {
  if (kind === 'approval') return <ShieldCheck size={14} />;
  if (kind === 'question') return <CircleHelp size={14} />;
  if (kind === 'plan') return <GitBranch size={14} />;
  if (kind === 'document' || kind === 'context') return <FileText size={14} />;
  if (kind === 'result' || kind === 'answer') return <MessageCircle size={14} />;
  if (kind === 'dispatch') return <Route size={14} />;
  return <Send size={14} />;
}

function packetKindLabel(kind: FlowPacketKind): string {
  return ({ request: '需求', question: '问题', answer: '答复', plan: 'Plan / WorkItem', document: '文档', context: '上下文', result: '公开结果', dispatch: '任务分派', approval: '审批' } as const)[kind];
}

function actorName(room: RoomSummary, actorId: FlowActorId): string {
  if (actorId === 'root') return '主 Room';
  return room.participants.find((participant) => participant.id === actorId)?.displayName || actorId;
}

function flowStatusLabel(status: string): string {
  return ({ queued: '等待送达', running: '传递中', waiting: '等待批准', active: '进行中', review: '待复核', completed: '已送达', done: '已完成', failed: '失败', aborted: '已停止', blocked: '受阻' } as Record<string, string>)[status] ?? status;
}

function clock(timestamp: number): string {
  return timestamp ? new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(new Date(timestamp)) : '';
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
