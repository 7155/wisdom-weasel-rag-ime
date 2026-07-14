import { GitBranch, MessageSquarePlus, Send, UsersRound } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Virtuoso } from 'react-virtuoso';
import { useControlTransport } from '@/app/control-transport';
import { IconButton } from '@/components/primitives';
import { createRoomDeltaBatcher } from '@/contracts/batching';
import {
  appendOptimisticRoomMessage,
  createRoomProjection,
  parseRoomEventSnapshot,
  reduceRoomEvent,
  replayRoomEventSnapshot,
  type RoomProjectionState,
} from '@/contracts/room-reducer';
import type { UiRoomEvent } from '@/contracts/ui-events';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import { previewPersonas } from '@/features/agent/preview-data';
import { AgentBlocks, MarkdownBody } from '@/features/agent/timeline/BlockRenderer';
import { PersonaAvatar } from '@/features/agent/timeline/PersonaAvatar';
import { roleItems } from '@/features/agent/types';
import './rooms.css';

interface RoomParticipant { id: string; sessionId: string; roleId: string; roleVersion: string; displayName: string; status: string; ordinal: number; }
export interface RoomSummary { id: string; title: string; status: string; routingPolicy: string; moderatorParticipantId: string; updatedAtMs: number; participants: RoomParticipant[]; }

export function RoomsFeature() {
  const transport = useControlTransport();
  const [rooms, setRooms] = useState<RoomSummary[]>([]);
  const [personas, setPersonas] = useState<AgentPersonaV1[]>(() => __CONTROL_PREVIEW__ && transport.kind === 'mock' ? previewPersonas : []);
  const [selectedId, setSelectedId] = useState('');
  const [projection, setProjection] = useState<RoomProjectionState>(() => createRoomProjection(''));
  const projectionRef = useRef(projection);
  const [draft, setDraft] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    void Promise.allSettled([
      transport.request({ pathId: 'agent.rooms.list', query: { limit: 100 } }),
      transport.request({ pathId: 'agent.roles.list' }),
    ]).then(([roomResult, roleResult]) => {
      if (!active) return;
      if (roomResult.status === 'rejected') throw roomResult.reason;
      const items = roomItems(roomResult.value);
      const roles = roleResult.status === 'fulfilled' ? roleItems(roleResult.value) : [];
      const next = __CONTROL_PREVIEW__ && transport.kind === 'mock' && items.length === 0 ? previewRooms : items;
      setPersonas(__CONTROL_PREVIEW__ && transport.kind === 'mock' && roles.length === 0 ? previewPersonas : roles);
      setRooms(next); setSelectedId((current) => current || next[0]?.id || '');
    }).catch((loadError) => active && setError(errorText(loadError)));
    return () => { active = false; };
  }, [transport]);

  useEffect(() => {
    if (!selectedId) return;
    let active = true;
    let generation = 0;
    let reloadQueued = false;
    let unsubscribe: (() => void) | undefined;
    let snapshotController: AbortController | undefined;
    const empty = createRoomProjection(selectedId);
    projectionRef.current = empty;
    setProjection(empty);

    const scheduleSnapshotReload = () => {
      if (!active || reloadQueued) return;
      reloadQueued = true;
      queueMicrotask(() => {
        reloadQueued = false;
        if (active) void loadSnapshotAndSubscribe();
      });
    };
    const batcher = createRoomDeltaBatcher((events) => {
      if (!active || projectionRef.current.roomId !== selectedId) return;
      let next = projectionRef.current;
      let snapshotRequired = false;
      for (const event of events) {
        const reduced = reduceRoomEvent(next, event);
        next = reduced.state;
        snapshotRequired ||= reduced.disposition === 'snapshot-required';
      }
      projectionRef.current = next;
      setProjection(next);
      if (snapshotRequired) scheduleSnapshotReload();
    });

    async function loadSnapshotAndSubscribe(): Promise<void> {
      const requestGeneration = ++generation;
      batcher.clear();
      unsubscribe?.();
      unsubscribe = undefined;
      snapshotController?.abort();
      snapshotController = new AbortController();
      try {
        const value = await transport.request({
          pathId: 'agent.room.snapshot',
          params: { roomId: selectedId },
          signal: snapshotController.signal,
        });
        if (!active || requestGeneration !== generation) return;
        const snapshot = parseRoomEventSnapshot(value);
        const base = projectionRef.current.roomId === selectedId
          ? projectionRef.current
          : createRoomProjection(selectedId);
        const next = replayRoomEventSnapshot(base, snapshot);
        projectionRef.current = next;
        setProjection(next);
        const snapshotRoom: RoomSummary = snapshot.room;
        setRooms((current) => current.map((item) => item.id === snapshotRoom.id ? snapshotRoom : item));
        setError('');
        const subscriptionGeneration = requestGeneration;
        unsubscribe = transport.subscribe<UiRoomEvent>(
          {
            pathId: 'agent.room.events',
            params: { roomId: selectedId },
            lastEventId: snapshot.resumeToken,
          },
          {
            next: (event) => {
              if (active && subscriptionGeneration === generation) batcher.push(event);
            },
            error: (streamError) => {
              if (active && subscriptionGeneration === generation) setError(streamError.message);
            },
            snapshotRequired: () => {
              if (active && subscriptionGeneration === generation) scheduleSnapshotReload();
            },
          },
        );
      } catch (loadError) {
        if (active && requestGeneration === generation && !isAbortError(loadError)) {
          setError(errorText(loadError));
        }
      }
    }

    void loadSnapshotAndSubscribe();
    return () => {
      active = false;
      generation += 1;
      snapshotController?.abort();
      batcher.clear();
      unsubscribe?.();
    };
  }, [selectedId, transport]);

  const room = rooms.find((item) => item.id === selectedId);
  async function send(): Promise<void> {
    const message = draft.trim();
    if (!room || !message) return;
    const clientMessageId = `room-web-${crypto.randomUUID()}`;
    setProjection((current) => {
      const next = appendOptimisticRoomMessage(current, { clientMessageId, text: message, nowMs: Date.now() });
      projectionRef.current = next;
      return next;
    });
    setDraft('');
    try { await transport.request({ pathId: 'agent.room.message', params: { roomId: room.id }, body: { message, clientMessageId } }); }
    catch (requestError) { setDraft(message); setError(errorText(requestError)); }
  }
  async function createRoom(): Promise<void> {
    const participants = personas.slice(0, 2).map((persona) => ({ roleId: persona.roleId, roleVersion: persona.version, displayName: persona.displayName }));
    if (participants.length < 2) {
      setError('真实角色目录至少需要两个角色才能创建 Room。');
      return;
    }
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
        <header><span><strong>{room?.title ?? 'Room'}</strong><small>{room?.routingPolicy === 'moderator' ? '主持人路由' : '手动 @ 路由'}</small></span><div className="room-participants">{room?.participants.map((participant) => <span key={participant.id}><PersonaAvatar persona={personas.find((item) => item.roleId === participant.roleId)} size="small" /><b>{participant.displayName}</b></span>)}</div></header>
        <div className="room-error-slot" aria-live="polite">
          {error ? <p className="room-error" role="alert">{error}</p> : null}
        </div>
        <div className="room-timeline">
          <Virtuoso data={projection.turnOrder} increaseViewportBy={300} itemContent={(_index, turnId) => <RoomTurn key={turnId} turnId={turnId} room={room} projection={projection} personas={personas} />} />
        </div>
        <div className="room-composer"><textarea rows={2} value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send(); } }} placeholder="向 Room 发消息，使用 @ 指定参与者…" aria-label="Room 消息" /><IconButton label="发送 Room 消息" icon={<Send size={17} />} disabled={!draft.trim()} onClick={() => void send()} tooltip /></div>
      </section>
    </main>
  );
}

export function RoomTurn({ turnId, room, projection, personas }: { turnId: string; room?: RoomSummary; projection: RoomProjectionState; personas: AgentPersonaV1[] }) {
  const turn = projection.turnsById[turnId];
  if (!turn) return null;
  const activities = turn.activityIds.map((id) => projection.activitiesById[id]).filter(Boolean);
  return <article className="room-turn">
    {turn.messageIds.map((id) => {
      const message = projection.messagesById[id];
      if (!message) return null;
      if (message.role === 'user') return <div key={id} className="room-user-message"><MarkdownBody text={message.text} /></div>;
      const participant = room?.participants.find((item) => item.id === message.participantId);
      return <div key={id} className="room-participant-message"><PersonaAvatar persona={personas.find((item) => item.roleId === participant?.roleId)} size="small" presence={message.status === 'streaming' ? 'thinking' : 'done'} /><div><header><strong>{participant?.displayName ?? 'Agent'}</strong><small>{message.status === 'streaming' ? '正在响应' : '已完成'}</small></header>{message.message ? <AgentBlocks blocks={message.message.blocks} /> : <MarkdownBody text={message.text} />}</div></div>;
    })}
    {activities.length ? <details className="room-group-activity"><summary><GitBranch size={15} /><span><strong>{turn.participantIds.length || activities.length} 个 Agent 协同处理</strong><small>{activities.length} 条结构化活动，展开查看分支</small></span></summary><div>{activities.map((activity) => { const participant = room?.participants.find((item) => item.id === activity.participantId); return <p key={activity.id}><PersonaAvatar persona={personas.find((item) => item.roleId === participant?.roleId)} size="small" /><span className="room-group-activity__copy"><strong>{participant?.displayName ?? '路由器'}</strong><small>{activity.summary}</small></span><i>{activity.status === 'running' ? '进行中' : activity.status === 'failed' ? '失败' : '完成'}</i></p>; })}</div></details> : null}
  </article>;
}

const previewRooms: RoomSummary[] = [{ id: 'room-preview', title: '迁移作战室', status: 'active', routingPolicy: 'moderator', moderatorParticipantId: 'participant-zhiyou', updatedAtMs: Date.now(), participants: [
  { id: 'participant-zhiyou', sessionId: 'session-preview', roleId: 'zhiyou-v1', roleVersion: '1', displayName: '智鼬·此刻', status: 'active', ordinal: 0 },
  { id: 'participant-hermes', sessionId: 'session-runtime', roleId: 'hermes-v1', roleVersion: '1', displayName: '智鼬·初识', status: 'active', ordinal: 1 },
] }];

function roomItems(value: unknown): RoomSummary[] { const source = record(value); return (Array.isArray(source.items) ? source.items : Array.isArray(source.rooms) ? source.rooms : []).filter(isRoom); }
function isRoom(value: unknown): value is RoomSummary { const item = record(value); return typeof item.id === 'string' && typeof item.title === 'string' && Array.isArray(item.participants); }
function record(value: unknown): Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function errorText(value: unknown): string { return value instanceof Error ? value.message : String(value); }
function isAbortError(value: unknown): boolean { return value instanceof DOMException && value.name === 'AbortError'; }
