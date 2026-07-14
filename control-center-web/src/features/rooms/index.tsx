import { GitBranch, MessageSquarePlus, Send, UsersRound } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Virtuoso } from 'react-virtuoso';
import { useControlTransport } from '@/app/control-transport';
import { IconButton } from '@/components/primitives';
import { createRoomDeltaBatcher } from '@/contracts/batching';
import { appendOptimisticRoomMessage, createRoomProjection, reduceRoomEvent, type RoomProjectionState } from '@/contracts/room-reducer';
import type { UiRoomEvent } from '@/contracts/ui-events';
import { previewPersonas } from '@/features/agent/preview-data';
import { AgentBlocks, MarkdownBody } from '@/features/agent/timeline/BlockRenderer';
import { PersonaAvatar } from '@/features/agent/timeline/PersonaAvatar';
import './rooms.css';

interface RoomParticipant { id: string; sessionId: string; roleId: string; roleVersion: string; displayName: string; status: string; ordinal: number; }
export interface RoomSummary { id: string; title: string; status: string; routingPolicy: string; moderatorParticipantId: string; updatedAtMs: number; participants: RoomParticipant[]; }

export function RoomsFeature() {
  const transport = useControlTransport();
  const [rooms, setRooms] = useState<RoomSummary[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [projection, setProjection] = useState<RoomProjectionState>(() => createRoomProjection(''));
  const [draft, setDraft] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    void transport.request({ pathId: 'agent.rooms.list', query: { limit: 100 } }).then((value) => {
      if (!active) return;
      const items = roomItems(value);
      const next = transport.kind === 'mock' && items.length === 0 ? previewRooms : items;
      setRooms(next); setSelectedId((current) => current || next[0]?.id || '');
    }).catch((loadError) => active && setError(errorText(loadError)));
    return () => { active = false; };
  }, [transport]);

  useEffect(() => {
    if (!selectedId) return;
    let state = createRoomProjection(selectedId);
    if (transport.kind === 'mock') for (const event of previewRoomEvents(selectedId)) state = reduceRoomEvent(state, event).state;
    setProjection(state);
    const batcher = createRoomDeltaBatcher((events) => setProjection((current) => {
      let next = current;
      for (const event of events) next = reduceRoomEvent(next, event).state;
      return next;
    }));
    const unsubscribe = transport.subscribe<UiRoomEvent>(
      { pathId: 'agent.room.events', params: { roomId: selectedId }, lastEventId: state.resumeToken },
      { next: (event) => batcher.push(event), error: (streamError) => setError(streamError.message) },
    );
    return () => { batcher.clear(); unsubscribe(); };
  }, [selectedId, transport]);

  const room = rooms.find((item) => item.id === selectedId);
  async function send(): Promise<void> {
    const message = draft.trim();
    if (!room || !message) return;
    const clientMessageId = `room-web-${crypto.randomUUID()}`;
    setProjection((current) => appendOptimisticRoomMessage(current, { clientMessageId, text: message, nowMs: Date.now() }));
    setDraft('');
    try { await transport.request({ pathId: 'agent.room.message', params: { roomId: room.id }, body: { message, clientMessageId } }); }
    catch (requestError) { setDraft(message); setError(errorText(requestError)); }
  }
  async function createRoom(): Promise<void> {
    const participants = previewPersonas.slice(0, 2).map((persona) => ({ roleId: persona.roleId, roleVersion: persona.version, displayName: persona.displayName }));
    try {
      const response = await transport.request<Record<string, unknown>>({ pathId: 'agent.rooms.create', body: { title: '新协作 Room', participants, routingPolicy: 'moderator', moderatorRoleId: participants[0]?.roleId ?? 'zhiyou-v1' } });
      const created = isRoom(record(response).room) ? record(response).room as unknown as RoomSummary : undefined;
      if (created) { setRooms((current) => [created, ...current]); setSelectedId(created.id); }
    } catch (requestError) { setError(errorText(requestError)); }
  }
  return (
    <main className="rooms-feature" data-route-id="rooms">
      <aside className="rooms-rail">
        <header><span><strong>Rooms</strong><small>多 Agent 协作</small></span><IconButton label="新建 Room" icon={<MessageSquarePlus size={17} />} onClick={() => void createRoom()} tooltip /></header>
        <div>{rooms.map((item) => <button type="button" key={item.id} aria-label={`打开 Room：${item.title}`} aria-current={item.id === selectedId} onClick={() => setSelectedId(item.id)}><UsersRound size={16} /><span><strong>{item.title}</strong><small>{item.participants.map((participant) => participant.displayName).join(' · ')}</small></span></button>)}</div>
      </aside>
      <section className="room-workspace">
        <header><span><strong>{room?.title ?? 'Room'}</strong><small>{room?.routingPolicy === 'moderator' ? '主持人路由' : '手动 @ 路由'}</small></span><div className="room-participants">{room?.participants.map((participant) => <span key={participant.id}><PersonaAvatar persona={previewPersonas.find((item) => item.roleId === participant.roleId)} size="small" /><b>{participant.displayName}</b></span>)}</div></header>
        <div className="room-error-slot" aria-live="polite">
          {error ? <p className="room-error" role="alert">{error}</p> : null}
        </div>
        <div className="room-timeline">
          <Virtuoso data={projection.turnOrder} increaseViewportBy={300} itemContent={(_index, turnId) => <RoomTurn key={turnId} turnId={turnId} room={room} projection={projection} />} />
        </div>
        <div className="room-composer"><textarea rows={2} value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send(); } }} placeholder="向 Room 发消息，使用 @ 指定参与者…" aria-label="Room 消息" /><IconButton label="发送 Room 消息" icon={<Send size={17} />} disabled={!draft.trim()} onClick={() => void send()} tooltip /></div>
      </section>
    </main>
  );
}

export function RoomTurn({ turnId, room, projection }: { turnId: string; room?: RoomSummary; projection: RoomProjectionState }) {
  const turn = projection.turnsById[turnId];
  if (!turn) return null;
  const activities = turn.activityIds.map((id) => projection.activitiesById[id]).filter(Boolean);
  return <article className="room-turn">
    {turn.messageIds.map((id) => {
      const message = projection.messagesById[id];
      if (!message) return null;
      if (message.role === 'user') return <div key={id} className="room-user-message"><MarkdownBody text={message.text} /></div>;
      const participant = room?.participants.find((item) => item.id === message.participantId);
      return <div key={id} className="room-participant-message"><PersonaAvatar persona={previewPersonas.find((item) => item.roleId === participant?.roleId)} size="small" presence={message.status === 'streaming' ? 'thinking' : 'done'} /><div><header><strong>{participant?.displayName ?? 'Agent'}</strong><small>{message.status === 'streaming' ? '正在响应' : '已完成'}</small></header>{message.message ? <AgentBlocks blocks={message.message.blocks} /> : <MarkdownBody text={message.text} />}</div></div>;
    })}
    {activities.length ? <details className="room-group-activity"><summary><GitBranch size={15} /><span><strong>{turn.participantIds.length || activities.length} 个 Agent 协同处理</strong><small>{activities.length} 条结构化活动，展开查看分支</small></span></summary><div>{activities.map((activity) => { const participant = room?.participants.find((item) => item.id === activity.participantId); return <p key={activity.id}><PersonaAvatar persona={previewPersonas.find((item) => item.roleId === participant?.roleId)} size="small" /><span className="room-group-activity__copy"><strong>{participant?.displayName ?? '路由器'}</strong><small>{activity.summary}</small></span><i>{activity.status === 'running' ? '进行中' : activity.status === 'failed' ? '失败' : '完成'}</i></p>; })}</div></details> : null}
  </article>;
}

const previewRooms: RoomSummary[] = [{ id: 'room-preview', title: '迁移作战室', status: 'active', routingPolicy: 'moderator', moderatorParticipantId: 'participant-zhiyou', updatedAtMs: Date.now(), participants: [
  { id: 'participant-zhiyou', sessionId: 'session-preview', roleId: 'zhiyou-v1', roleVersion: '1', displayName: '智鼬', status: 'active', ordinal: 0 },
  { id: 'participant-hermes', sessionId: 'session-runtime', roleId: 'hermes-v1', roleVersion: '1', displayName: 'Hermes', status: 'active', ordinal: 1 },
] }];

function previewRoomEvents(roomId: string): UiRoomEvent[] {
  const turnId = `${roomId}:turn-1`;
  const base = { schemaVersion: 'rag-ime.agent-room-event.v1' as const, roomId, turnId, createdAtMs: Date.now() - 60_000, sourceSessionId: '' };
  const make = (sequence: number, eventType: UiRoomEvent['eventType'], participantId: string | null, payload: Record<string, unknown>): UiRoomEvent => ({ ...base, eventId: `${roomId}:${sequence}`, sequence, eventType, participantId, payload, resumeToken: `${roomId}:${sequence}`, streamKind: 'room' });
  return [
    make(1, 'user_message', null, { messageId: 'room-user-1', text: '并行检查 Agent UI 与 Control API 的集成边界。' }),
    make(2, 'route_decision', null, { summary: '主持人将任务分给 2 个 Agent' }),
    make(3, 'participant_activity', 'participant-zhiyou', { requestId: 'activity-a', summary: '核对 Turn 聚合与流式投影', status: 'completed' }),
    make(4, 'participant_activity', 'participant-hermes', { requestId: 'activity-b', summary: '核对 route policy 与权限回执', status: 'completed' }),
    make(5, 'participant_delta', 'participant-zhiyou', { messageId: 'room-assistant-1', delta: 'Agent 时间线已经复用统一 reducer 与 batcher，' }),
    make(6, 'participant_delta', 'participant-zhiyou', { messageId: 'room-assistant-1', delta: '主时间线不会平铺每个工具结果。' }),
    make(7, 'participant_delta', 'participant-hermes', { messageId: 'room-assistant-2', delta: '权限切换只在服务端回执后更新。' }),
    make(8, 'turn_completed', null, { summary: '协作检查完成' }),
  ];
}

function roomItems(value: unknown): RoomSummary[] { const source = record(value); return (Array.isArray(source.items) ? source.items : Array.isArray(source.rooms) ? source.rooms : []).filter(isRoom); }
function isRoom(value: unknown): value is RoomSummary { const item = record(value); return typeof item.id === 'string' && typeof item.title === 'string' && Array.isArray(item.participants); }
function record(value: unknown): Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function errorText(value: unknown): string { return value instanceof Error ? value.message : String(value); }
