import { Archive, ArchiveRestore, AtSign, ExternalLink, GitBranch, MessageSquarePlus, PanelRightOpen, Send, ShieldCheck, UsersRound } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Virtuoso } from 'react-virtuoso';
import { useControlTransport } from '@/app/control-transport';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  IconButton,
  Select,
} from '@/components/primitives';
import { createRoomDeltaBatcher } from '@/contracts/batching';
import {
  appendOptimisticRoomMessage,
  createRoomProjection,
  parseRoomEventSnapshot,
  reduceRoomEvent,
  replayRoomEventSnapshot,
  type RoomActivityProjection,
  type RoomProjectionState,
} from '@/contracts/room-reducer';
import type { UiRoomEvent } from '@/contracts/ui-events';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import { AgentBlocks, MarkdownBody } from '@/features/agent/timeline/BlockRenderer';
import { PersonaAvatar } from '@/features/agent/timeline/PersonaAvatar';
import { roleItems } from '@/features/agent/types';
import { publicErrorText } from '@/features/overview/management-ui';
import { RoomStatusPanel } from './RoomStatusPanel';
import './rooms.css';

export interface RoomParticipant { id: string; sessionId: string; roleId: string; roleVersion: string; displayName: string; status: string; ordinal: number; }
export interface RoomSummary { id: string; title: string; status: string; routingPolicy: string; moderatorParticipantId: string; updatedAtMs: number; participants: RoomParticipant[]; }
interface AgentSessionPolicySummary { id: string; mode: 'assistant' | 'coordinator'; status: string; toolProfileVersion: string; toolAllowlistMode: 'profile' | 'explicit'; allowedTools: string[]; }
interface RoomToolPolicyItem { id: string; displayName: string; description: string; sessionModes: string[]; operations: string[]; profileOperations: Record<string, string[]>; enabled: boolean; }

export function RoomsFeature() {
  const transport = useControlTransport();
  const [rooms, setRooms] = useState<RoomSummary[]>([]);
  const [personas, setPersonas] = useState<AgentPersonaV1[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [projection, setProjection] = useState<RoomProjectionState>(() => createRoomProjection(''));
  const projectionRef = useRef(projection);
  const [statusOpen, setStatusOpen] = useState(() => isWideRoomStatusViewport());
  const [snapshotLoading, setSnapshotLoading] = useState(false);
  const [draft, setDraft] = useState('');
  const [error, setError] = useState('');
  const [roomCatalogError, setRoomCatalogError] = useState('');
  const [roleCatalogError, setRoleCatalogError] = useState('');
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [createError, setCreateError] = useState('');
  const [createTitle, setCreateTitle] = useState('');
  const [selectedRoleIds, setSelectedRoleIds] = useState<string[]>([]);
  const [routingPolicy, setRoutingPolicy] = useState<'moderator' | 'manual_mentions'>('moderator');
  const [moderatorRoleId, setModeratorRoleId] = useState('');
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const [policyParticipant, setPolicyParticipant] = useState<RoomParticipant>();
  const [policySession, setPolicySession] = useState<AgentSessionPolicySummary>();
  const [policyTools, setPolicyTools] = useState<RoomToolPolicyItem[]>([]);
  const [policyMode, setPolicyMode] = useState<'assistant' | 'coordinator'>('assistant');
  const [policyProfile, setPolicyProfile] = useState('control-center-v1');
  const [policyAllowedTools, setPolicyAllowedTools] = useState<string[]>([]);
  const [policyLoading, setPolicyLoading] = useState(false);
  const [policySaving, setPolicySaving] = useState(false);
  const [policyError, setPolicyError] = useState('');

  useEffect(() => {
    let active = true;
    setCatalogLoading(true);
    void Promise.allSettled([
      transport.request({ pathId: 'agent.rooms.list', query: { limit: 100, ...(includeArchived ? { includeArchived: true } : {}) } }),
      transport.request({ pathId: 'agent.roles.list' }),
    ]).then(([roomResult, roleResult]) => {
      if (!active) return;
      if (roomResult.status === 'fulfilled') {
        const items = roomItems(roomResult.value);
        setRooms(items);
        setSelectedId((current) => items.some((item) => item.id === current)
          ? current
          : items.find((item) => item.status === 'active')?.id ?? items[0]?.id ?? '');
        setRoomCatalogError('');
      } else {
        setRoomCatalogError(publicErrorText(roomResult.reason, 'Rooms 暂时无法读取，请稍后重试。'));
      }
      if (roleResult.status === 'fulfilled') {
        setPersonas(roleItems(roleResult.value));
        setRoleCatalogError('');
      } else {
        setRoleCatalogError(publicErrorText(roleResult.reason, '角色目录暂时无法读取，请稍后重试。'));
      }
    }).finally(() => { if (active) setCatalogLoading(false); });
    return () => { active = false; };
  }, [includeArchived, transport]);

  useEffect(() => {
    if (!selectedId) {
      setSnapshotLoading(false);
      return;
    }
    let active = true;
    let generation = 0;
    let reloadQueued = false;
    let unsubscribe: (() => void) | undefined;
    let snapshotController: AbortController | undefined;
    const empty = createRoomProjection(selectedId);
    projectionRef.current = empty;
    setProjection(empty);
    setSnapshotLoading(true);

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
        setSnapshotLoading(false);
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
              if (active && subscriptionGeneration === generation) {
                setError(publicErrorText(streamError, 'Room 实时连接暂时中断，请稍后重试。'));
              }
            },
            snapshotRequired: () => {
              if (active && subscriptionGeneration === generation) scheduleSnapshotReload();
            },
          },
        );
      } catch (loadError) {
        if (active && requestGeneration === generation && !isAbortError(loadError)) {
          setError(publicErrorText(loadError, '暂时无法读取 Room 对话，请稍后重试。'));
          setSnapshotLoading(false);
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
  const visibleTurnOrder = projection.roomId === selectedId ? projection.turnOrder : [];
  const roomCanSend = room?.status === 'active';
  const hasManualMention = Boolean(room && room.routingPolicy === 'manual_mentions' && room.participants.some((participant) => draft.includes(`@${participant.displayName}`)));
  const canSend = Boolean(roomCanSend && draft.trim() && (room?.routingPolicy !== 'manual_mentions' || hasManualMention));
  async function send(): Promise<void> {
    const message = draft.trim();
    if (!room || room.status !== 'active' || !message) return;
    if (room.routingPolicy === 'manual_mentions' && !hasManualMention) {
      setError('请先选择一位参与角色。');
      return;
    }
    const clientMessageId = `room-web-${crypto.randomUUID()}`;
    setProjection((current) => {
      const next = appendOptimisticRoomMessage(current, { clientMessageId, text: message, nowMs: Date.now() });
      projectionRef.current = next;
      return next;
    });
    setDraft('');
    setError('');
    try { await transport.request({ pathId: 'agent.room.message', params: { roomId: room.id }, body: { message, clientMessageId } }); }
    catch (requestError) {
      setProjection((current) => {
        const next = removeOptimisticRoomMessage(current, clientMessageId);
        projectionRef.current = next;
        return next;
      });
      setDraft(message);
      setError(publicErrorText(requestError, '消息暂时未发送，请稍后重试。'));
    }
  }
  function addressParticipant(displayName: string): void {
    setDraft((current) => {
      let message = current.trimStart();
      for (const participant of room?.participants ?? []) {
        const mention = `@${participant.displayName}`;
        if (message.startsWith(mention)) {
          message = message.slice(mention.length).trimStart();
          break;
        }
      }
      return `@${displayName}${message ? ` ${message}` : ' '}`;
    });
    setError('');
  }
  function beginCreateRoom(): void {
    if (personas.length < 2) {
      setError('真实角色目录至少需要两个角色才能创建 Room。');
      return;
    }
    const defaults = personas.slice(0, 2).map((persona) => persona.roleId);
    setError('');
    setCreateError('');
    setCreateTitle('');
    setSelectedRoleIds(defaults);
    setModeratorRoleId(defaults[0] ?? '');
    setRoutingPolicy('moderator');
    setCreateOpen(true);
  }
  function toggleParticipant(roleId: string): void {
    setCreateError('');
    setSelectedRoleIds((current) => {
      const next = current.includes(roleId)
        ? current.filter((item) => item !== roleId)
        : current.length < 4 ? [...current, roleId] : current;
      if (!next.includes(moderatorRoleId)) setModeratorRoleId(next[0] ?? '');
      return next;
    });
  }
  async function createRoom(): Promise<void> {
    if (creating) return;
    const participants = selectedRoleIds
      .map((roleId) => personas.find((persona) => persona.roleId === roleId))
      .filter((persona): persona is AgentPersonaV1 => Boolean(persona))
      .map((persona) => ({ roleId: persona.roleId, roleVersion: persona.version, displayName: persona.displayName }));
    if (participants.length < 2) {
      setCreateError('请选择 2 至 4 个角色。');
      return;
    }
    const title = createTitle.trim();
    if (!title) return;
    if (routingPolicy === 'moderator' && !selectedRoleIds.includes(moderatorRoleId)) {
      setCreateError('请选择一位已加入 Room 的主持人。');
      return;
    }
    setCreating(true);
    setCreateError('');
    try {
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.rooms.create',
        body: {
          title,
          participants,
          routingPolicy,
          ...(routingPolicy === 'moderator' ? { moderatorRoleId } : {}),
        },
      });
      const created = isRoom(record(response).room) ? record(response).room as unknown as RoomSummary : undefined;
      if (!created) throw new Error('服务端没有返回可验证的 Room。');
      setRooms((current) => [created, ...current]);
      setSelectedId(created.id);
      setCreateOpen(false);
    } catch (requestError) { setCreateError(publicErrorText(requestError, 'Room 暂时无法创建，请稍后重试。')); }
    finally { setCreating(false); }
  }
  async function updateRoomArchiveState(archived: boolean): Promise<void> {
    if (!room || archiving) return;
    setArchiving(true);
    setError('');
    try {
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.room.archive',
        params: { roomId: room.id },
        body: { archived },
      });
      const updated = isRoom(record(response).room) ? record(response).room as unknown as RoomSummary : undefined;
      const expectedStatus = archived ? 'archived' : 'active';
      if (!updated || updated.status !== expectedStatus) throw new Error(`服务端没有确认 Room 已${archived ? '归档' : '恢复'}。`);
      const nextRooms = archived && !includeArchived
        ? rooms.filter((item) => item.id !== room.id)
        : rooms.map((item) => item.id === room.id ? updated : item);
      setRooms(nextRooms);
      setSelectedId(nextRooms.some((item) => item.id === room.id) ? room.id : nextRooms[0]?.id ?? '');
      setArchiveOpen(false);
    } catch (requestError) { setError(publicErrorText(requestError, 'Room 状态暂时无法更新，请稍后重试。')); }
    finally { setArchiving(false); }
  }
  async function openParticipantPolicy(participant: RoomParticipant): Promise<void> {
    setPolicyParticipant(participant);
    setPolicySession(undefined);
    setPolicyTools([]);
    setPolicyError('');
    setPolicyLoading(true);
    try {
      const [sessionResponse, toolResponse] = await Promise.all([
        transport.request({ pathId: 'agent.sessions.list', query: { includeInternal: true, limit: 500 } }),
        transport.request({ pathId: 'agent.tools.list', query: { sessionId: participant.sessionId } }),
      ]);
      const session = agentSessionItems(sessionResponse).find((item) => item.id === participant.sessionId);
      if (!session) throw new Error('没有找到这个参与者的 Agent Session。');
      const tools = roomToolItems(toolResponse);
      setPolicySession(session);
      setPolicyTools(tools);
      setPolicyMode(session.mode);
      setPolicyProfile(session.toolProfileVersion);
      setPolicyAllowedTools(session.toolAllowlistMode === 'explicit'
        ? session.allowedTools
        : tools.filter((tool) => tool.enabled).map((tool) => tool.id));
    } catch (requestError) {
      setPolicyError(publicErrorText(requestError, '参与者权限暂时无法读取，请稍后重试。'));
    } finally {
      setPolicyLoading(false);
    }
  }
  function updatePolicyMode(mode: 'assistant' | 'coordinator'): void {
    setPolicyMode(mode);
    setPolicyAllowedTools((current) => current.filter((toolId) => {
      const tool = policyTools.find((item) => item.id === toolId);
      return Boolean(tool && toolAvailableForPolicy(tool, mode, policyProfile));
    }));
  }
  function updatePolicyProfile(profile: string): void {
    setPolicyProfile(profile);
    setPolicyAllowedTools((current) => current.filter((toolId) => {
      const tool = policyTools.find((item) => item.id === toolId);
      return Boolean(tool && toolAvailableForPolicy(tool, policyMode, profile));
    }));
  }
  function togglePolicyTool(toolId: string): void {
    setPolicyAllowedTools((current) => current.includes(toolId)
      ? current.filter((item) => item !== toolId)
      : [...current, toolId]);
  }
  async function saveParticipantPolicy(): Promise<void> {
    if (!policyParticipant || !policySession || policySaving) return;
    setPolicySaving(true);
    setPolicyError('');
    try {
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.session.mode.update',
        params: { sessionId: policyParticipant.sessionId },
        body: {
          mode: policyMode,
          toolProfileVersion: policyProfile,
          allowedTools: policyAllowedTools,
        },
      });
      const updated = agentSessionValue(record(response).session);
      if (!updated) throw new Error('服务端没有返回更新后的 Agent 权限。');
      setPolicySession(updated);
      setPolicyParticipant(undefined);
    } catch (requestError) {
      setPolicyError(publicErrorText(requestError, '参与者权限暂时无法保存，请稍后重试。'));
    } finally {
      setPolicySaving(false);
    }
  }
  return <>
    <main className="rooms-feature" data-route-id="rooms" data-status-open={statusOpen}>
      <aside className="rooms-rail">
        <header><span><strong>Rooms</strong><small>多 Agent 协作</small></span><div className="rooms-rail-actions"><IconButton label={includeArchived ? '隐藏已归档 Room' : '显示已归档 Room'} icon={includeArchived ? <ArchiveRestore size={16} /> : <Archive size={16} />} aria-pressed={includeArchived} onClick={() => setIncludeArchived((current) => !current)} tooltip /><IconButton disabled={catalogLoading || creating} label="新建 Room" icon={<MessageSquarePlus size={17} />} onClick={beginCreateRoom} tooltip /></div></header>
        <div>{rooms.length ? rooms.map((item) => <button type="button" key={item.id} aria-label={`打开 Room：${item.title}`} aria-current={item.id === selectedId} onClick={() => setSelectedId(item.id)}><UsersRound size={16} /><span><strong>{item.title}</strong><small>{item.status === 'archived' ? '已归档 · ' : ''}{item.participants.map((participant) => participant.displayName).join(' · ')}</small></span></button>) : !catalogLoading ? <p className="rooms-rail-empty">还没有 Room</p> : null}</div>
      </aside>
      <section className="room-workspace">
        <header><span><strong>{room?.title ?? 'Room'}</strong><small>{!room ? '选择或新建协作空间' : room.status === 'archived' ? '已归档' : room.routingPolicy === 'moderator' ? '由主持人协调' : '通过 @ 指派'}</small></span><div className="room-header-actions"><div className="room-participants">{room?.participants.map((participant) => <button type="button" key={participant.id} aria-label={`配置 ${participant.displayName} 的权限`} onClick={() => void openParticipantPolicy(participant)}><PersonaAvatar persona={personas.find((item) => item.roleId === participant.roleId)} size="small" /><b>{participant.displayName}</b><ShieldCheck size={13} /></button>)}</div>{room ? <IconButton label={room.status === 'archived' ? '恢复 Room' : '归档 Room'} icon={room.status === 'archived' ? <ArchiveRestore size={16} /> : <Archive size={16} />} onClick={() => { setError(''); setArchiveOpen(true); }} tooltip /> : null}<IconButton label={statusOpen ? '隐藏 Room 状态栏' : '展开 Room 状态'} icon={<PanelRightOpen size={17} />} onClick={() => setStatusOpen((current) => !current)} tooltip /></div></header>
        <div className="room-error-slot" aria-live="polite">
          {error ? <p className="room-error" role="alert">{error}</p> : null}
          {!error && roomCatalogError ? <p className="room-error" role="alert">{roomCatalogError}</p> : null}
          {!error && !roomCatalogError && roleCatalogError ? <p className="room-catalog-warning" role="status">{roleCatalogError}</p> : null}
        </div>
        <div className="room-timeline">
          {room ? visibleTurnOrder.length ? <Virtuoso data={visibleTurnOrder} increaseViewportBy={300} itemContent={(_index, turnId) => <RoomTurn key={turnId} turnId={turnId} room={room} projection={projection} personas={personas} />} /> : <p className="room-empty">{snapshotLoading ? '正在读取 Room 对话…' : '还没有对话，发一条消息开始协作。'}</p> : <p className="room-empty">{catalogLoading ? '正在读取 Rooms…' : '选择一个 Room，或新建协作 Room。'}</p>}
        </div>
        <div className="room-composer-shell">{roomCanSend && room?.routingPolicy === 'manual_mentions' ? <div className="room-mention-bar" aria-label="指派参与角色"><AtSign size={14} />{room.participants.map((participant) => <button type="button" key={participant.id} aria-pressed={draft.trimStart().startsWith(`@${participant.displayName}`)} onClick={() => addressParticipant(participant.displayName)}>{participant.displayName}</button>)}</div> : null}<div className="room-composer"><textarea rows={2} value={draft} disabled={!roomCanSend} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send(); } }} placeholder={!room ? '先选择或新建 Room' : room.status === 'archived' ? '恢复 Room 后继续协作' : room.routingPolicy === 'manual_mentions' ? '先选择一位角色，再输入消息…' : '向 Room 发消息…'} aria-label="Room 消息" /><IconButton label="发送 Room 消息" icon={<Send size={17} />} disabled={!canSend} onClick={() => void send()} tooltip /></div></div>
      </section>
      <button className="agent-status-backdrop room-status-backdrop" aria-label="关闭 Room 状态" onClick={() => setStatusOpen(false)} type="button" />
      <RoomStatusPanel room={room} projection={projection} open={statusOpen} onClose={() => setStatusOpen(false)} />
    </main>
    <Dialog open={createOpen} onOpenChange={(open) => { if (!creating) { setCreateOpen(open); if (!open) setCreateError(''); } }}>
      <DialogContent className="room-create-dialog">
        <DialogHeader><DialogTitle>新建协作 Room</DialogTitle><DialogDescription>选择 2 至 4 个真实角色，并决定这次协作由谁协调。</DialogDescription></DialogHeader>
        <form id="room-create-form" className="room-create-form" onSubmit={(event) => { event.preventDefault(); void createRoom(); }}>
          {createError ? <p className="room-dialog-error" role="alert">{createError}</p> : null}
          <label className="room-create-field"><span>名称</span><input autoFocus maxLength={120} value={createTitle} onChange={(event) => { setCreateTitle(event.target.value); setCreateError(''); }} placeholder="例如：发布前检查" aria-label="Room 名称" /></label>
          <fieldset><legend>参与角色 <small>{selectedRoleIds.length}/4</small></legend><div className="room-role-options">{personas.map((persona) => { const checked = selectedRoleIds.includes(persona.roleId); return <label key={`${persona.roleId}:${persona.version}`}><input type="checkbox" checked={checked} disabled={!checked && selectedRoleIds.length >= 4} onChange={() => toggleParticipant(persona.roleId)} /><PersonaAvatar persona={persona} size="small" /><span><strong>{persona.displayName}</strong><small>{persona.tagline}</small></span></label>; })}</div></fieldset>
          <fieldset><legend>协调方式</legend><div className="room-routing-options"><label><input type="radio" name="room-routing" checked={routingPolicy === 'moderator'} onChange={() => { setRoutingPolicy('moderator'); setCreateError(''); }} />由一位角色协调</label><label><input type="radio" name="room-routing" checked={routingPolicy === 'manual_mentions'} onChange={() => { setRoutingPolicy('manual_mentions'); setCreateError(''); }} />通过 @ 指派</label></div></fieldset>
          {routingPolicy === 'moderator' ? <label className="room-create-field"><span>主持人</span><Select aria-label="Room 主持人" onValueChange={(value) => { setModeratorRoleId(value); setCreateError(''); }} options={selectedRoleIds.flatMap((roleId) => { const persona = personas.find((item) => item.roleId === roleId); return persona ? [{ value: roleId, label: persona.displayName }] : []; })} value={moderatorRoleId} /></label> : null}
        </form>
        <DialogFooter><Button variant="quiet" disabled={creating} onClick={() => setCreateOpen(false)}>取消</Button><Button type="submit" form="room-create-form" variant="primary" loading={creating} disabled={!createTitle.trim() || selectedRoleIds.length < 2}>创建 Room</Button></DialogFooter>
      </DialogContent>
    </Dialog>
    <Dialog open={archiveOpen} onOpenChange={(open) => { if (!archiving) setArchiveOpen(open); }}>
      <DialogContent><DialogHeader><DialogTitle>{room?.status === 'archived' ? '恢复这个 Room？' : '归档这个 Room？'}</DialogTitle><DialogDescription>{room?.status === 'archived' ? `“${room.title}”会恢复协作与消息输入。` : `“${room?.title}”会从当前列表移除，已有对话仍保留在本机。`}</DialogDescription></DialogHeader>{error ? <p className="room-dialog-error" role="alert">{error}</p> : null}<DialogFooter><Button variant="quiet" disabled={archiving} onClick={() => setArchiveOpen(false)}>取消</Button><Button variant={room?.status === 'archived' ? 'primary' : 'danger'} loading={archiving} onClick={() => void updateRoomArchiveState(room?.status !== 'archived')}>{room?.status === 'archived' ? '恢复' : '归档'}</Button></DialogFooter></DialogContent>
    </Dialog>
    <Dialog open={Boolean(policyParticipant)} onOpenChange={(open) => { if (!open && !policySaving) { setPolicyParticipant(undefined); setPolicyError(''); } }}>
      <DialogContent className="room-policy-dialog">
        <DialogHeader><DialogTitle>{policyParticipant?.displayName ?? '参与者'}的运行权限</DialogTitle><DialogDescription>这些设置直接约束该参与者在 Room 中可使用的模式和工具。</DialogDescription></DialogHeader>
        {policyError ? <p className="room-dialog-error" role="alert">{policyError}</p> : null}
        {policyLoading ? <p className="room-policy-loading" role="status">正在读取 Agent 权限…</p> : policySession ? <div className="room-policy-form">
          <fieldset><legend>运行模式</legend><div className="room-policy-segments">{(['assistant', 'coordinator'] as const).map((mode) => { const persona = personas.find((item) => item.roleId === policyParticipant?.roleId); const available = persona?.selectableModes.includes(mode) ?? mode === policySession.mode; return <label key={mode}><input type="radio" name="room-participant-mode" value={mode} checked={policyMode === mode} disabled={!available} onChange={() => updatePolicyMode(mode)} /><span>{mode === 'assistant' ? '助手' : '协调者'}</span></label>; })}</div></fieldset>
          <fieldset><legend>工具策略</legend><div className="room-policy-segments"><label><input type="radio" name="room-tool-profile" checked={policyProfile === 'control-center-v1'} onChange={() => updatePolicyProfile('control-center-v1')} /><span>标准</span></label><label><input type="radio" name="room-tool-profile" checked={policyProfile === 'subagent-readonly-v1'} onChange={() => updatePolicyProfile('subagent-readonly-v1')} /><span>只读</span></label></div></fieldset>
          <fieldset><legend>允许工具 <small>{policyAllowedTools.length} 项</small></legend><div className="room-policy-tools">{policyTools.map((tool) => { const available = toolAvailableForPolicy(tool, policyMode, policyProfile); return <label key={tool.id} data-disabled={!available}><input type="checkbox" checked={available && policyAllowedTools.includes(tool.id)} disabled={!available} onChange={() => togglePolicyTool(tool.id)} /><span><strong>{tool.displayName}</strong><small>{available ? tool.description : '当前模式或策略不可用'}</small></span></label>; })}</div></fieldset>
        </div> : null}
        <DialogFooter><Button variant="quiet" disabled={policySaving} onClick={() => setPolicyParticipant(undefined)}>取消</Button><Button variant="primary" loading={policySaving} disabled={policyLoading || !policySession} onClick={() => void saveParticipantPolicy()}>保存权限</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </>;
}

export function RoomTurn({ turnId, room, projection, personas }: { turnId: string; room?: RoomSummary; projection: RoomProjectionState; personas: AgentPersonaV1[] }) {
  const turn = projection.turnsById[turnId];
  if (!turn) return null;
  const activities = turn.activityIds.map((id) => projection.activitiesById[id]).filter(Boolean);
  const seenActivityDescriptions = new Set<string>();
  const activityRows = activities.flatMap((activity) => {
    if (!isUsefulRoomActivity(activity)) return [];
    const participant = room?.participants.find((item) => item.id === activity.participantId);
    const description = describeRoomActivity(activity, participant?.displayName);
    const displayStatus = roomActivityDisplayStatus(activity);
    const duplicateKey = `${participant?.id ?? ''}\u0000${description.title}\u0000${description.detail}\u0000${displayStatus}`;
    if (seenActivityDescriptions.has(duplicateKey)) return [];
    seenActivityDescriptions.add(duplicateKey);
    return [{ activity, participant, description, displayStatus }];
  });
  const reviewActivity = [...activities].reverse().find((activity) => {
    const requestKind = textValue(activity.payload.requestKind);
    const approvalId = textValue(activity.payload.approvalId);
    const state = textValue(activity.payload.state);
    return requestKind === 'memory_review'
      || Boolean(approvalId && !['approved', 'rejected', 'applied'].includes(state));
  });
  const reviewSessionId = reviewActivity?.sourceSessionId
    || room?.participants.find((item) => item.id === reviewActivity?.participantId)?.sessionId
    || '';
  return <article className="room-turn">
    {turn.messageIds.map((id) => {
      const message = projection.messagesById[id];
      if (!message) return null;
      if (message.role === 'user') return <div key={id} className="room-user-message"><MarkdownBody text={message.text} /></div>;
      const participant = room?.participants.find((item) => item.id === message.participantId);
      const visibleBlocks = message.message?.blocks.filter((block) => block.type !== 'reasoning_summary' && block.type !== 'tool_call' && block.type !== 'tool_result');
      const needsReview = visibleBlocks?.some((block) => block.type === 'approval' && !['approved', 'rejected', 'applied'].includes(textValue(block.data.state)));
      return <div key={id} className="room-participant-message"><PersonaAvatar persona={personas.find((item) => item.roleId === participant?.roleId)} size="small" presence={message.status === 'streaming' ? 'thinking' : 'done'} /><div><header><strong>{participant?.displayName ?? 'Agent'}</strong><small>{message.status === 'streaming' ? '正在响应' : '已完成'}</small></header>{visibleBlocks?.length ? <AgentBlocks blocks={visibleBlocks} /> : message.text ? <MarkdownBody text={message.text} /> : null}{needsReview && participant?.sessionId ? <a className="room-review-link" href={agentSessionHref(participant.sessionId)}><span><strong>需要在 Agent 对话中审阅</strong><small>打开对应参与者，批准或拒绝这项操作。</small></span><span>前往审阅 <ExternalLink size={13} /></span></a> : null}</div></div>;
    })}
    {reviewSessionId ? <a className="room-review-link room-review-link--turn" href={agentSessionHref(reviewSessionId)}><span><strong>这轮协作正在等待审阅</strong><small>Agent 已暂停；打开对应会话处理后会自动继续。</small></span><span>立即审阅 <ExternalLink size={13} /></span></a> : null}
    {activityRows.length ? <details className="room-group-activity"><summary><GitBranch size={15} /><span><strong>协作进度</strong><small>{activityRows.length} 条实时进展</small></span></summary><div>{activityRows.map(({ activity, participant, description, displayStatus }) => <p key={activity.id}><PersonaAvatar persona={personas.find((item) => item.roleId === participant?.roleId)} size="small" /><span className="room-group-activity__copy"><strong>{description.title}</strong><small>{description.detail}</small></span><i data-status={displayStatus}>{displayStatus === 'running' ? '进行中' : displayStatus === 'failed' ? '未完成' : '完成'}</i></p>)}</div></details> : null}
  </article>;
}

function isUsefulRoomActivity(activity: RoomActivityProjection): boolean {
  if (activity.kind !== 'participant_activity') return true;
  if (activity.status !== 'completed') return true;
  if (textValue(activity.payload.activityKind) === 'intercom') return true;
  return Boolean(publicActivitySummary(activity.summary, activity.kind));
}

function roomActivityDisplayStatus(activity: RoomActivityProjection): RoomActivityProjection['status'] {
  const status = textValue(activity.payload.status);
  if (activity.kind === 'participant_status' && ['room_created', 'room_archived', 'room_restored'].includes(status)) return 'completed';
  if (textValue(activity.payload.activityKind) === 'intercom') {
    const phase = textValue(activity.payload.phase);
    if (phase === 'delivered') return 'completed';
    if (phase === 'failed' || phase === 'stale') return 'failed';
  }
  return activity.status;
}

function describeRoomActivity(activity: RoomActivityProjection, participantName = '协作成员'): { title: string; detail: string } {
  const payload = activity.payload;
  const status = textValue(payload.status);
  if (activity.kind === 'route_decision') {
    const target = textValue(payload.targetDisplayName) || participantName;
    return {
      title: `${target} 已接手`,
      detail: textValue(payload.routingPolicy) === 'manual_mentions' ? '根据 @ 指派开始处理' : '由主持人安排处理这轮任务',
    };
  }
  if (activity.kind === 'participant_status') {
    if (status === 'room_created') return { title: '协作空间已就绪', detail: '参与角色已经加入，可以开始对话' };
    if (status === 'room_archived') return { title: '协作空间已归档', detail: '历史对话已保留' };
    if (status === 'room_restored') return { title: '协作空间已恢复', detail: '参与角色可以继续协作' };
    return { title: `${participantName} 状态已更新`, detail: activity.status === 'running' ? '正在准备处理任务' : '当前步骤已经同步' };
  }
  if (activity.kind === 'turn_failed') {
    return { title: '这轮协作未完成', detail: '可以调整消息后重新发送' };
  }
  if (textValue(payload.activityKind) === 'intercom') {
    const phase = textValue(payload.phase);
    const phaseCopy: Record<string, string> = {
      queued: '协作消息正在等待接收',
      delivered: '协作消息已经送达',
      stale: '协作消息已过期',
      failed: '协作消息未能送达',
    };
    return { title: `${participantName} 正在与其他角色协作`, detail: phaseCopy[phase] ?? '协作消息状态已更新' };
  }
  const summary = publicActivitySummary(activity.summary, activity.kind);
  if (summary) return { title: `${participantName} 更新了进展`, detail: summary };
  if (activity.status === 'failed') return { title: `${participantName} 未完成这一步`, detail: '可以稍后重试' };
  if (activity.status === 'running') return { title: `${participantName} 正在处理`, detail: '有新进展时会在这里更新' };
  return { title: `${participantName} 完成了一步`, detail: '协作进度已经同步' };
}

function publicActivitySummary(summary: string, kind: string): string {
  const value = summary.trim();
  if (!value || value === kind) return '';
  if (/\b(?:participant|route|tool|turn)_[a-z_]+\b/i.test(value)) return '';
  if (/control-center-(?:safe-)?v\d/i.test(value)) return '';
  if (value.includes('内部工具步骤')) return '准备工作已经完成';
  return value;
}

function textValue(value: unknown): string { return typeof value === 'string' ? value : ''; }
function agentSessionHref(sessionId: string): string { return `#/agent?${new URLSearchParams({ session: sessionId })}`; }

function roomItems(value: unknown): RoomSummary[] { const source = record(value); return (Array.isArray(source.items) ? source.items : Array.isArray(source.rooms) ? source.rooms : []).filter(isRoom); }
function isRoom(value: unknown): value is RoomSummary { const item = record(value); return typeof item.id === 'string' && typeof item.title === 'string' && Array.isArray(item.participants); }
function agentSessionItems(value: unknown): AgentSessionPolicySummary[] { const source = record(value); return (Array.isArray(source.items) ? source.items : []).map(agentSessionValue).filter((item): item is AgentSessionPolicySummary => Boolean(item)); }
function agentSessionValue(value: unknown): AgentSessionPolicySummary | undefined { const item = record(value); if (typeof item.id !== 'string' || !['assistant', 'coordinator'].includes(String(item.mode))) return undefined; return { id: item.id, mode: item.mode as AgentSessionPolicySummary['mode'], status: String(item.status ?? ''), toolProfileVersion: String(item.toolProfileVersion || 'control-center-v1'), toolAllowlistMode: item.toolAllowlistMode === 'explicit' ? 'explicit' : 'profile', allowedTools: Array.isArray(item.allowedTools) ? item.allowedTools.map(String) : [] }; }
function roomToolItems(value: unknown): RoomToolPolicyItem[] { const source = record(value); return (Array.isArray(source.items) ? source.items : []).flatMap((value) => { const item = record(value); if (typeof item.id !== 'string' || typeof item.displayName !== 'string') return []; const profileOperations = record(item.profileOperations); return [{ id: item.id, displayName: item.displayName, description: String(item.description ?? ''), sessionModes: Array.isArray(item.sessionModes) ? item.sessionModes.map(String) : [], operations: Array.isArray(item.operations) ? item.operations.map(String) : [], profileOperations: Object.fromEntries(Object.entries(profileOperations).map(([profile, operations]) => [profile, Array.isArray(operations) ? operations.map(String) : []])), enabled: item.enabled === true }]; }); }
function toolAvailableForPolicy(tool: RoomToolPolicyItem, mode: string, profile: string): boolean { return tool.sessionModes.includes(mode) && (tool.profileOperations[profile] ?? []).length > 0; }
function record(value: unknown): Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {}; }

function isWideRoomStatusViewport(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia('(min-width: 1280px)').matches
    : false;
}
function isAbortError(value: unknown): boolean { return value instanceof DOMException && value.name === 'AbortError'; }

export function removeOptimisticRoomMessage(
  state: RoomProjectionState,
  clientMessageId: string,
): RoomProjectionState {
  const messageId = state.optimisticByClientMessageId[clientMessageId];
  if (!messageId) return state;
  const message = state.messagesById[messageId];
  const next: RoomProjectionState = {
    ...state,
    messagesById: { ...state.messagesById },
    messageOrder: state.messageOrder.filter((id) => id !== messageId),
    turnsById: { ...state.turnsById },
    turnOrder: [...state.turnOrder],
    optimisticByClientMessageId: { ...state.optimisticByClientMessageId },
  };
  delete next.messagesById[messageId];
  delete next.optimisticByClientMessageId[clientMessageId];
  if (!message) return next;
  const turn = next.turnsById[message.turnId];
  if (!turn) return next;
  const messageIds = turn.messageIds.filter((id) => id !== messageId);
  if (messageIds.length || turn.activityIds.length) {
    next.turnsById[turn.id] = { ...turn, messageIds };
  } else {
    delete next.turnsById[turn.id];
    next.turnOrder = next.turnOrder.filter((id) => id !== turn.id);
  }
  return next;
}
