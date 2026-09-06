import type { AgentRoomIntercomV1 } from '@/contracts/generated/agent-room-intercom.v1';
import type { AgentSubagentRunV1 } from '@/contracts/generated/agent-subagent-run.v1';
import { isSubagentBatch, subagentRuns, subagentTree } from '@/features/agent/status/subagent-data';
import { subagentPresentationState, subagentStateLabel, type SubagentPresentationState } from '@/features/agent/status/subagent-presentation';
import type { RoomFocusPacket } from './room-focus-projection';

export interface RoomSatellite {
  id: string;
  nodeId: string;
  sessionId: string;
  task: string;
  state: SubagentPresentationState;
  stateLabel: string;
  depth: number;
  result: string;
  error: string;
}

export interface RoomSatelliteSnapshot {
  status: 'loading' | 'ready' | 'error';
  satellites: RoomSatellite[];
  updatedAtMs?: number;
  error?: string;
}

export type RoomSatelliteSnapshots = Record<string, RoomSatelliteSnapshot | undefined>;

/** A retained Tool Agent node is one satellite; retries are attempts of it.
 * Room Partner Sessions are never satellites, even if a malformed run names one. */
export function roomSatellites(value: unknown, participantSessionIds: readonly string[]): RoomSatellite[] {
  const latest = new Map<string, AgentSubagentRunV1>();
  for (const run of subagentRuns(value)) {
    if (participantSessionIds.includes(run.childSessionId)) continue;
    const identity = run.nodeId || run.id;
    const previous = latest.get(identity);
    if (!previous || run.attemptNumber > previous.attemptNumber
      || (run.attemptNumber === previous.attemptNumber && run.updatedAtMs > previous.updatedAtMs)) latest.set(identity, run);
  }
  return [...latest.values()].map((run) => ({
    id: run.id,
    nodeId: run.nodeId,
    sessionId: run.childSessionId,
    task: run.todoTask || run.task,
    state: subagentPresentationState(run),
    stateLabel: subagentStateLabel(run),
    depth: run.depth,
    result: typeof run.result.summary === 'string' ? run.result.summary : '',
    error: run.error,
  }));
}

/** Keep absence/malformed responses separate from a successful empty tree. */
export function hasRoomSatelliteSnapshot(value: unknown, sessionId: string): boolean {
  const source = record(value);
  const tree = record(source.tree);
  if (source.ok !== true) return false;
  if (source.tree) {
    if (tree.rootSessionId !== sessionId || !Array.isArray(tree.roots)) return false;
    const parsed = subagentTree(value);
    return parsed.roots.length === tree.roots.length && parsed.nodeCount === tree.nodeCount;
  }
  return Array.isArray(source.items) && source.items.every(isSubagentBatch);
}

export function roomIntercomMessages(value: unknown, roomId: string): AgentRoomIntercomV1[] {
  const source = record(value);
  if (!Array.isArray(source.items)) return [];
  return source.items.filter((item): item is AgentRoomIntercomV1 => {
    const row = record(item);
    return row.schemaVersion === 'rag-ime.agent-room-intercom.v1'
      && row.roomId === roomId && typeof row.id === 'string'
      && typeof row.sourceParticipantId === 'string' && typeof row.targetParticipantId === 'string'
      && ['send', 'ask', 'reply'].includes(String(row.kind))
      && ['queued', 'delivering', 'delivered', 'replied', 'failed', 'stale', 'cancelled'].includes(String(row.status))
      && typeof row.content === 'string' && typeof row.createdAtMs === 'number';
  });
}

/** The durable queue supplies content, lifecycle and reply linkage. Room
 * activity receipts enrich that same identity instead of inflating traffic. */
export function mergeRoomMessageFlow(flow: RoomFocusPacket[], intercom: AgentRoomIntercomV1[]): RoomFocusPacket[] {
  const packets = new Map(flow.map((packet) => [packet.id, packet]));
  for (const message of intercom) {
    const id = `intercom:${message.id}`;
    const previous = packets.get(id);
    packets.set(id, {
      id,
      intercomId: message.id,
      sourceParticipantId: message.sourceParticipantId,
      targetParticipantIds: [message.targetParticipantId],
      kind: message.kind === 'ask' ? 'question' : message.kind === 'reply' ? 'answer' : 'intercom',
      summary: message.content,
      status: message.status,
      createdAtMs: message.createdAtMs,
      updatedAtMs: message.updatedAtMs,
      sequence: previous?.sequence ?? message.createdAtMs,
      ...(message.workItemId ? { workItemId: message.workItemId } : {}),
      ...(message.replyTo ? { replyToPacketId: `intercom:${message.replyTo}` } : {}),
      ...(message.deliveredAtMs ? { deliveredAtMs: message.deliveredAtMs } : {}),
      ...(message.repliedAtMs ? { repliedAtMs: message.repliedAtMs } : {}),
      ...(message.error ? { error: message.error } : {}),
      receiptIds: previous?.receiptIds ?? [],
      refs: previous?.refs ?? [],
      ...(!previous ? { scope: 'recent-room' as const } : {}),
    });
  }
  // Queue timestamps and Room event sequence numbers are different clocks.
  // Timestamp first; sequence is only a tie-breaker within this merged view.
  return [...packets.values()].sort((a, b) => a.createdAtMs - b.createdAtMs || a.sequence - b.sequence || a.id.localeCompare(b.id));
}

export function roomFlowStatusLabel(status: string, directMessage = false): string {
  if (status === 'failed') return directMessage ? '投递失败' : '失败';
  return ({
    queued: '等待送达', delivering: '投递中', delivered: '已送达', replied: '已回复',
    stale: '已失效', cancelled: '已取消', running: '传递中', waiting: '等待批准',
    active: '进行中', review: '待复核', completed: '已完成', done: '已完成',
    aborted: '已停止', blocked: '受阻',
  } as Record<string, string>)[status] ?? status;
}

export function roomFlowKindLabel(kind: RoomFocusPacket['kind']): string {
  return ({ request: '请求', intercom: '直接消息', question: '询问', answer: '回复', plan: '计划', document: '文档', context: '上下文', result: '公开结果', dispatch: '任务分派', approval: '审批', review: '复核' })[kind];
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
