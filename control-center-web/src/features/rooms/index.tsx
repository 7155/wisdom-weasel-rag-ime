import { Archive, ArchiveRestore, AtSign, BriefcaseBusiness, ExternalLink, FilePlus2, FolderOpen, GitBranch, LoaderCircle, MessageSquarePlus, MessagesSquare, PanelRightOpen, Plus, Send, Settings2, ShieldCheck, Sparkles, UsersRound } from 'lucide-react';
import * as RadioGroup from '@radix-ui/react-radio-group';
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

export interface RoomParticipant { id: string; sessionId: string; roleId: string; roleVersion: string; displayName: string; collaborationRole?: 'coordinator' | 'executor' | 'researcher'; status: string; ordinal: number; }
export type RoomKind = 'collaboration' | 'roleplay';
export type RoomRoutingPolicy = 'moderator' | 'manual_mentions' | 'sequential' | 'natural' | 'invite_only';
export interface RoomTopic { id: string; roomId: string; title: string; summary: string; status: 'active' | 'archived'; ordinal: number; createdAtMs: number; updatedAtMs: number; }
export interface RoomArtifact { id: string; roomId: string; topicId: string; displayName: string; path: string; mediaType: string; status: 'active' | 'archived'; createdAtMs: number; updatedAtMs: number; }
export type RoomWorkState = 'queued' | 'active' | 'review' | 'blocked' | 'done' | 'failed' | 'cancelled';
export interface RoomWorkItem {
  id: string;
  roomId: string;
  topicId: string;
  rootTurnId: string;
  rootWorkId: string;
  parentWorkId: string;
  objective: string;
  expectedOutput: string;
  acceptanceCriteria: string[];
  accountableParticipantId: string;
  currentOwnerParticipantId: string;
  offeredToParticipantId: string;
  createdByParticipantId: string;
  clientMessageId: string;
  state: RoomWorkState;
  depth: number;
  revision: number;
  resultSummary: string;
  artifactRefs: string[];
  evidenceRefs: string[];
  blocker: Record<string, unknown>;
  acceptedTurnId: string;
  createdAtMs: number;
  updatedAtMs: number;
  completedAtMs: number | null;
}
export interface RoomSummary {
  id: string;
  title: string;
  status: string;
  roomKind?: RoomKind;
  avatar?: string;
  description?: string;
  scenarioPrompt?: string;
  routingPolicy: RoomRoutingPolicy;
  routingConfig?: { maxResponders?: number; naturalJitter?: number; fallbackParticipantId?: string };
  moderatorParticipantId: string;
  activeTopicId?: string;
  configRevision?: number;
  workspaceRoots?: string[];
  topics?: RoomTopic[];
  artifacts?: RoomArtifact[];
  workItems?: RoomWorkItem[];
  updatedAtMs: number;
  participants: RoomParticipant[];
}
interface AgentSessionPolicySummary { id: string; mode: 'assistant' | 'coordinator'; status: string; toolProfileVersion: string; toolAllowlistMode: 'profile' | 'explicit'; allowedTools: string[]; workspaceRoots: string[]; }
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
  const [createRoomKind, setCreateRoomKind] = useState<RoomKind>('collaboration');
  const [createAvatar, setCreateAvatar] = useState('briefcase');
  const [createDescription, setCreateDescription] = useState('');
  const [createScenarioPrompt, setCreateScenarioPrompt] = useState('');
  const [projectPaths, setProjectPaths] = useState<string[]>([]);
  const [workspaceRoots, setWorkspaceRoots] = useState<string[]>([]);
  const [workspacePicking, setWorkspacePicking] = useState(false);
  const [selectedRoleIds, setSelectedRoleIds] = useState<string[]>([]);
  const [routingPolicy, setRoutingPolicy] = useState<RoomRoutingPolicy>('moderator');
  const [moderatorRoleId, setModeratorRoleId] = useState('');
  const [invitedParticipantId, setInvitedParticipantId] = useState('');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsTitle, setSettingsTitle] = useState('');
  const [settingsAvatar, setSettingsAvatar] = useState('members');
  const [settingsDescription, setSettingsDescription] = useState('');
  const [settingsScenarioPrompt, setSettingsScenarioPrompt] = useState('');
  const [settingsRoutingPolicy, setSettingsRoutingPolicy] = useState<RoomRoutingPolicy>('moderator');
  const [settingsModeratorParticipantId, setSettingsModeratorParticipantId] = useState('');
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [settingsError, setSettingsError] = useState('');
  const [topicsOpen, setTopicsOpen] = useState(false);
  const [topicTitle, setTopicTitle] = useState('');
  const [topicSummary, setTopicSummary] = useState('');
  const [topicEditingId, setTopicEditingId] = useState('');
  const [topicSaving, setTopicSaving] = useState(false);
  const [topicError, setTopicError] = useState('');
  const [artifactPicking, setArtifactPicking] = useState(false);
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
      transport.request({ pathId: 'agent.sessions.list', query: { limit: 200 } }),
    ]).then(([roomResult, roleResult, sessionResult]) => {
      if (!active) return;
      const loadedRooms = roomResult.status === 'fulfilled' ? roomItems(roomResult.value) : [];
      if (roomResult.status === 'fulfilled') {
        const items = loadedRooms;
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
      const loadedSessions = sessionResult.status === 'fulfilled'
        ? agentSessionItems(sessionResult.value)
        : [];
      setProjectPaths(uniquePaths([
        ...loadedRooms.flatMap((item) => item.workspaceRoots ?? []),
        ...loadedSessions.flatMap((item) => item.workspaceRoots),
      ]));
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
        const snapshotRoom = snapshot.room as unknown as RoomSummary;
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
              if (!active || subscriptionGeneration !== generation) return;
              batcher.push(event);
              if (
                ['room_config_changed', 'topic_changed', 'artifact_changed'].includes(event.eventType)
                || (event.eventType === 'participant_activity' && event.payload.activityKind === 'work')
              ) {
                scheduleSnapshotReload();
              }
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
  const activeWork = room?.workItems?.find((work) => ['blocked', 'review', 'active', 'queued'].includes(work.state));
  const hasManualMention = Boolean(room && room.routingPolicy === 'manual_mentions' && room.participants.some((participant) => draft.includes(`@${participant.displayName}`)));
  const hasInvite = Boolean(room && room.routingPolicy === 'invite_only' && room.participants.some((participant) => participant.id === invitedParticipantId));
  const canSend = Boolean(
    roomCanSend
    && draft.trim()
    && (room?.routingPolicy !== 'manual_mentions' || hasManualMention)
    && (room?.routingPolicy !== 'invite_only' || hasInvite),
  );
  async function send(): Promise<void> {
    const message = draft.trim();
    if (!room || room.status !== 'active' || !message) return;
    if (room.routingPolicy === 'manual_mentions' && !hasManualMention) {
      setError('请先选择一位参与角色。');
      return;
    }
    if (room.routingPolicy === 'invite_only' && !hasInvite) {
      setError('请先邀请一位角色发言。');
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
    try {
      await transport.request({
        pathId: 'agent.room.message',
        params: { roomId: room.id },
        body: {
          message,
          clientMessageId,
          ...(room.routingPolicy === 'invite_only' ? { participantIds: [invitedParticipantId] } : {}),
        },
      });
      setInvitedParticipantId('');
    }
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
    const eligiblePersonas = personas.filter((persona) => persona.selectableModes.includes('coordinator'));
    if (
      eligiblePersonas.length < 2
      && personas.filter((persona) => persona.selectableModes.includes('assistant')).length < 2
    ) {
      setError('真实角色目录至少需要两个角色才能创建 Room。');
      return;
    }
    const timelineDefaults = ['vcp-v1', 'zhiyou-v1', 'hermes-v1']
      .map((roleId) => eligiblePersonas.find((persona) => persona.roleId === roleId)?.roleId)
      .filter((roleId): roleId is string => Boolean(roleId));
    const defaults = timelineDefaults.length >= 2
      ? timelineDefaults
      : eligiblePersonas.slice(0, Math.min(3, eligiblePersonas.length)).map((persona) => persona.roleId);
    setError('');
    setCreateError('');
    setCreateTitle('');
    setCreateRoomKind('collaboration');
    setCreateAvatar('briefcase');
    setCreateDescription('');
    setCreateScenarioPrompt('');
    setWorkspaceRoots(projectPaths.slice(0, 1));
    setSelectedRoleIds(defaults);
    setModeratorRoleId(defaults.includes('vcp-v1') ? 'vcp-v1' : defaults[0] ?? '');
    setRoutingPolicy('moderator');
    setCreateOpen(true);
  }
  function updateCreateRoomKind(kind: RoomKind): void {
    const requiredMode = kind === 'collaboration' ? 'coordinator' : 'assistant';
    const eligible = personas.filter((persona) => persona.selectableModes.includes(requiredMode));
    const timelineDefaults = ['vcp-v1', 'zhiyou-v1', 'hermes-v1']
      .map((roleId) => eligible.find((persona) => persona.roleId === roleId)?.roleId)
      .filter((roleId): roleId is string => Boolean(roleId));
    const defaults = timelineDefaults.length >= 2
      ? timelineDefaults
      : eligible.slice(0, Math.min(3, eligible.length)).map((persona) => persona.roleId);
    setCreateRoomKind(kind);
    setCreateAvatar(kind === 'roleplay' ? 'sparkles' : 'briefcase');
    setSelectedRoleIds(defaults);
    setModeratorRoleId(defaults.includes('vcp-v1') ? 'vcp-v1' : defaults[0] ?? '');
    setRoutingPolicy(kind === 'roleplay' ? 'natural' : 'moderator');
    setCreateError('');
  }
  async function pickWorkspaceRoot(): Promise<void> {
    if (workspacePicking || creating) return;
    if (!transport.pickFiles) {
      setCreateError('当前平台不能选择本地工作区，请在桌面控制中心中创建 Room。');
      return;
    }
    setWorkspacePicking(true);
    setCreateError('');
    try {
      const picked = await transport.pickFiles({
        purpose: 'workspace-root',
        selection: 'directory',
        multiple: false,
        maxFiles: 1,
      });
      const roots = uniquePaths(picked.map((item) => item.path ?? ''));
      if (roots.length) {
        setWorkspaceRoots(roots);
        setProjectPaths((current) => uniquePaths([...roots, ...current]));
      }
    } catch (pickError) {
      setCreateError(publicErrorText(pickError, '工作区选择失败，请稍后重试。'));
    } finally {
      setWorkspacePicking(false);
    }
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
    if (createRoomKind === 'collaboration' && !workspaceRoots.length) {
      setCreateError('请先选择这个 Room 使用的项目路径。');
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
          roomKind: createRoomKind,
          avatar: createAvatar,
          description: createDescription.trim(),
          scenarioPrompt: createScenarioPrompt.trim(),
          participants,
          routingPolicy,
          workspaceRoots: createRoomKind === 'collaboration' ? workspaceRoots : [],
          routingConfig: { maxResponders: 1, naturalJitter: createRoomKind === 'roleplay' ? 0.04 : 0, fallbackParticipantId: '' },
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
  function beginRoomSettings(): void {
    if (!room) return;
    setSettingsTitle(room.title);
    setSettingsAvatar(room.avatar ?? (room.roomKind === 'roleplay' ? 'sparkles' : 'briefcase'));
    setSettingsDescription(room.description ?? '');
    setSettingsScenarioPrompt(room.scenarioPrompt ?? '');
    setSettingsRoutingPolicy(room.routingPolicy);
    setSettingsModeratorParticipantId(room.moderatorParticipantId);
    setSettingsError('');
    setSettingsOpen(true);
  }
  async function saveRoomSettings(): Promise<void> {
    if (!room || settingsSaving || !settingsTitle.trim()) return;
    if (settingsRoutingPolicy === 'moderator' && !settingsModeratorParticipantId) {
      setSettingsError('请选择一位主持人。');
      return;
    }
    setSettingsSaving(true);
    setSettingsError('');
    try {
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.room.archive',
        params: { roomId: room.id },
        body: {
          title: settingsTitle.trim(),
          avatar: settingsAvatar,
          description: settingsDescription.trim(),
          scenarioPrompt: settingsScenarioPrompt.trim(),
          routingPolicy: settingsRoutingPolicy,
          routingConfig: room.routingConfig ?? { maxResponders: 1, naturalJitter: room.roomKind === 'roleplay' ? 0.04 : 0, fallbackParticipantId: '' },
          ...(settingsRoutingPolicy === 'moderator'
            ? { moderatorParticipantId: settingsModeratorParticipantId }
            : {}),
        },
      });
      const updated = isRoom(record(response).room) ? record(response).room as unknown as RoomSummary : undefined;
      if (!updated) throw new Error('服务端没有返回更新后的 Room。');
      setRooms((current) => current.map((item) => item.id === updated.id ? updated : item));
      setSettingsOpen(false);
      setInvitedParticipantId('');
    } catch (requestError) {
      setSettingsError(publicErrorText(requestError, 'Room 设置暂时无法保存，请稍后重试。'));
    } finally {
      setSettingsSaving(false);
    }
  }
  async function createTopic(): Promise<void> {
    if (!room || topicSaving || !topicTitle.trim()) return;
    setTopicSaving(true);
    setTopicError('');
    try {
      const response = await transport.request<Record<string, unknown>>({
        pathId: topicEditingId ? 'agent.room.topic.update' : 'agent.room.topic.create',
        params: { roomId: room.id },
        body: {
          ...(topicEditingId ? { topicId: topicEditingId } : {}),
          title: topicTitle.trim(),
          summary: topicSummary.trim(),
        },
      });
      const updated = isRoom(record(response).room) ? record(response).room as unknown as RoomSummary : undefined;
      if (!updated) throw new Error('服务端没有返回更新后的话题。');
      setRooms((current) => current.map((item) => item.id === updated.id ? updated : item));
      setTopicTitle('');
      setTopicSummary('');
      setTopicEditingId('');
    } catch (requestError) {
      setTopicError(publicErrorText(requestError, '话题暂时无法创建，请稍后重试。'));
    } finally {
      setTopicSaving(false);
    }
  }
  async function updateTopic(topicId: string, changes: Record<string, string | boolean>): Promise<void> {
    if (!room || topicSaving) return;
    setTopicSaving(true);
    setTopicError('');
    try {
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.room.topic.update',
        params: { roomId: room.id },
        body: { topicId, ...changes },
      });
      const updated = isRoom(record(response).room) ? record(response).room as unknown as RoomSummary : undefined;
      if (!updated) throw new Error('服务端没有返回更新后的话题。');
      setRooms((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (requestError) {
      setTopicError(publicErrorText(requestError, '话题状态暂时无法更新，请稍后重试。'));
    } finally {
      setTopicSaving(false);
    }
  }
  async function addRoomArtifact(): Promise<void> {
    if (!room || artifactPicking) return;
    if (!room.workspaceRoots?.length) {
      setError('角色扮演 Room 没有项目路径；先在协作 Room 中绑定工作区，才能共享文件。');
      return;
    }
    if (!transport.pickFiles) {
      setError('当前平台不能选择共享文件，请在桌面控制中心中操作。');
      return;
    }
    setArtifactPicking(true);
    setError('');
    try {
      const selected = await transport.pickFiles({
        purpose: 'room-artifact',
        selection: 'file',
        multiple: false,
        maxFiles: 1,
      });
      const file = selected[0];
      if (!file?.path) return;
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.room.artifact.add',
        params: { roomId: room.id },
        body: {
          path: file.path,
          displayName: file.name,
          mediaType: file.mimeType,
          topicId: room.activeTopicId ?? '',
        },
      });
      const updated = isRoom(record(response).room) ? record(response).room as unknown as RoomSummary : undefined;
      if (!updated) throw new Error('服务端没有返回新增的共享文件。');
      setRooms((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (requestError) {
      setError(publicErrorText(requestError, '共享文件暂时无法加入 Room，请确认文件位于授权项目路径内。'));
    } finally {
      setArtifactPicking(false);
    }
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
          workspaceRoots: policyMode === 'coordinator'
            ? room?.workspaceRoots ?? policySession.workspaceRoots
            : [],
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
        <div>{rooms.length ? rooms.map((item) => <button type="button" key={item.id} aria-label={`打开 Room：${item.title}`} aria-current={item.id === selectedId} onClick={() => { setSelectedId(item.id); setInvitedParticipantId(''); }}>{roomAvatarIcon(item)}<span><strong>{item.title}</strong><small>{item.status === 'archived' ? '已归档 · ' : ''}{item.participants.map((participant) => participant.displayName).join(' · ')}</small></span></button>) : !catalogLoading ? <p className="rooms-rail-empty">还没有 Room</p> : null}</div>
      </aside>
      <section className="room-workspace">
        <header><span><strong>{room?.title ?? 'Room'}</strong><small>{!room ? '选择或新建群聊' : room.status === 'archived' ? '已归档' : `${room.roomKind === 'roleplay' ? '角色群聊' : roomPathName(room)} · ${routingPolicyLabel(room.routingPolicy)}`}</small></span><div className="room-header-actions"><div className="room-participants">{room?.participants.map((participant) => <button type="button" key={participant.id} aria-label={`配置 ${participant.displayName} 的权限`} onClick={() => void openParticipantPolicy(participant)}><PersonaAvatar persona={personas.find((item) => item.roleId === participant.roleId)} size="small" /><b>{participant.displayName}</b><ShieldCheck size={13} /></button>)}</div>{room ? <IconButton label="Room 设置" icon={<Settings2 size={16} />} onClick={beginRoomSettings} tooltip /> : null}{room ? <IconButton label={room.status === 'archived' ? '恢复 Room' : '归档 Room'} icon={room.status === 'archived' ? <ArchiveRestore size={16} /> : <Archive size={16} />} onClick={() => { setError(''); setArchiveOpen(true); }} tooltip /> : null}<IconButton label={statusOpen ? '隐藏 Room 状态栏' : '展开 Room 状态'} icon={<PanelRightOpen size={17} />} onClick={() => setStatusOpen((current) => !current)} tooltip /></div></header>
        {room ? <div className="room-context-bar">
          <div className="room-topic-tabs" aria-label="Room 话题">
            <MessagesSquare size={14} />
            {(room.topics ?? []).filter((topic) => topic.status === 'active').map((topic) => <button type="button" key={topic.id} aria-current={topic.id === room.activeTopicId} onClick={() => { if (topic.id !== room.activeTopicId) void updateTopic(topic.id, { activate: true }); }}>{topic.title}</button>)}
            <IconButton label="管理 Room 话题" icon={<Plus size={14} />} disabled={topicSaving} onClick={() => { setTopicError(''); setTopicsOpen(true); }} tooltip />
          </div>
          <div className="room-context-actions">
            {activeWork ? <span className="room-work-summary" data-state={activeWork.state} title={activeWork.objective}><GitBranch size={13} />{roomWorkStateLabel(activeWork.state)} · {participantName(room, activeWork.currentOwnerParticipantId)} · {activeWork.objective}</span> : <span>{room.description || (room.roomKind === 'roleplay' ? '自然多角色交流' : '共享工作区协作')}</span>}
            {room.roomKind !== 'roleplay' ? <IconButton label="添加共享文件" icon={artifactPicking ? <LoaderCircle className="ui-spin" size={15} /> : <FilePlus2 size={15} />} disabled={artifactPicking || room.status !== 'active'} onClick={() => void addRoomArtifact()} tooltip /> : null}
          </div>
        </div> : <div aria-hidden="true" className="room-context-bar room-context-bar--empty" />}
        <div className="room-error-slot" aria-live="polite">
          {error ? <p className="room-error" role="alert">{error}</p> : null}
          {!error && roomCatalogError ? <p className="room-error" role="alert">{roomCatalogError}</p> : null}
          {!error && !roomCatalogError && roleCatalogError ? <p className="room-catalog-warning" role="status">{roleCatalogError}</p> : null}
        </div>
        <div className="room-timeline">
          {room ? visibleTurnOrder.length ? <Virtuoso data={visibleTurnOrder} increaseViewportBy={300} itemContent={(_index, turnId) => <RoomTurn key={turnId} turnId={turnId} room={room} projection={projection} personas={personas} />} /> : <p className="room-empty">{snapshotLoading ? '正在读取 Room 对话…' : '还没有对话，发一条消息开始协作。'}</p> : <p className="room-empty">{catalogLoading ? '正在读取 Rooms…' : '选择一个 Room，或新建协作 Room。'}</p>}
        </div>
        <div className="room-composer-shell">{roomCanSend && ['manual_mentions', 'invite_only'].includes(room?.routingPolicy ?? '') ? <div className="room-mention-bar" aria-label={room?.routingPolicy === 'invite_only' ? '邀请发言角色' : '指派参与角色'}>{room?.routingPolicy === 'invite_only' ? <MessageSquarePlus size={14} /> : <AtSign size={14} />}{room?.participants.map((participant) => <button type="button" key={participant.id} aria-pressed={room.routingPolicy === 'invite_only' ? invitedParticipantId === participant.id : draft.trimStart().startsWith(`@${participant.displayName}`)} onClick={() => { if (room.routingPolicy === 'invite_only') { setInvitedParticipantId(participant.id); setError(''); } else addressParticipant(participant.displayName); }}>{participant.displayName}</button>)}</div> : null}<div className="room-composer"><textarea rows={2} value={draft} disabled={!roomCanSend} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send(); } }} placeholder={!room ? '先选择或新建 Room' : room.status === 'archived' ? '恢复 Room 后继续交流' : room.routingPolicy === 'manual_mentions' ? '先选择一位角色，再输入消息…' : room.routingPolicy === 'invite_only' ? '先邀请一位角色发言…' : room.roomKind === 'roleplay' ? '向群聊发送消息…' : '向 Room 发消息…'} aria-label="Room 消息" /><IconButton label="发送 Room 消息" icon={<Send size={17} />} disabled={!canSend} onClick={() => void send()} tooltip /></div></div>
      </section>
      <button className="agent-status-backdrop room-status-backdrop" aria-label="关闭 Room 状态" disabled={!statusOpen} onClick={() => setStatusOpen(false)} type="button" />
      <RoomStatusPanel room={room} projection={projection} open={statusOpen} onClose={() => setStatusOpen(false)} />
    </main>
    <Dialog open={createOpen} onOpenChange={(open) => { if (!creating) { setCreateOpen(open); if (!open) setCreateError(''); } }}>
      <DialogContent className="room-create-dialog">
        <DialogHeader><DialogTitle>新建 Room</DialogTitle><DialogDescription>协作 Room 围绕项目执行；角色群聊围绕设定自然交流。两者使用同一条结构化事件链。</DialogDescription></DialogHeader>
        <form id="room-create-form" className="room-create-form" onSubmit={(event) => { event.preventDefault(); void createRoom(); }}>
          {createError ? <p className="room-dialog-error" role="alert">{createError}</p> : null}
          <fieldset><legend>用途</legend><div className="room-kind-options">
            <label><input type="radio" name="room-kind" checked={createRoomKind === 'collaboration'} onChange={() => updateCreateRoomKind('collaboration')} /><span><BriefcaseBusiness size={17} /><strong>任务协作</strong><small>共享工作区、工具和产物</small></span></label>
            <label><input type="radio" name="room-kind" checked={createRoomKind === 'roleplay'} onChange={() => updateCreateRoomKind('roleplay')} /><span><Sparkles size={17} /><strong>角色群聊</strong><small>自然发言与共同背景设定</small></span></label>
          </div></fieldset>
          {createRoomKind === 'collaboration' ? <section className="room-create-projects" aria-label="项目路径">
            <header><strong>项目路径</strong><small>必选</small></header>
            {projectPaths.length ? <RadioGroup.Root aria-label="最近项目" value={workspaceRoots[0] ?? ''} onValueChange={(value) => { setWorkspaceRoots([value]); setCreateError(''); }}>{projectPaths.map((path) => <RadioGroup.Item key={path} value={path} title={path}><FolderOpen size={16} /><span><strong>{pathName(path)}</strong><small>{path}</small></span></RadioGroup.Item>)}</RadioGroup.Root> : null}
            {workspaceRoots[0] && !projectPaths.includes(workspaceRoots[0]) ? <div className="room-create-project-picked" title={workspaceRoots.join('\n')}><FolderOpen size={16} /><span><strong>{pathName(workspaceRoots[0])}</strong><small>{workspaceRoots[0]}</small></span></div> : null}
            <Button type="button" variant="quiet" leadingIcon={workspacePicking ? <LoaderCircle className="ui-spin" size={15} /> : <FolderOpen size={15} />} disabled={workspacePicking || creating} onClick={() => void pickWorkspaceRoot()}>{workspaceRoots.length ? '选择其他目录' : '选择项目目录'}</Button>
          </section> : null}
          <div className="room-create-pair">
            <label className="room-create-field"><span>名称</span><input maxLength={120} value={createTitle} onChange={(event) => { setCreateTitle(event.target.value); setCreateError(''); }} placeholder={createRoomKind === 'roleplay' ? '例如：深夜茶话会' : '例如：发布前检查'} aria-label="Room 名称" /></label>
            <label className="room-create-field"><span>头像</span><Select aria-label="Room 头像" onValueChange={setCreateAvatar} options={roomAvatarOptions()} value={createAvatar} /></label>
          </div>
          <label className="room-create-field"><span>简介</span><input maxLength={500} value={createDescription} onChange={(event) => setCreateDescription(event.target.value)} placeholder="一句话说明这个 Room 的用途" aria-label="Room 简介" /></label>
          <fieldset><legend>参与角色 <small>{selectedRoleIds.length}/4</small></legend><div className="room-role-options">{personas.filter((persona) => persona.selectableModes.includes(createRoomKind === 'roleplay' ? 'assistant' : 'coordinator')).map((persona) => { const checked = selectedRoleIds.includes(persona.roleId); return <label key={`${persona.roleId}:${persona.version}`}><input type="checkbox" checked={checked} disabled={!checked && selectedRoleIds.length >= 4} onChange={() => toggleParticipant(persona.roleId)} /><PersonaAvatar persona={persona} size="small" /><span><strong>{persona.displayName}<em>{createRoomKind === 'roleplay' ? '群聊角色' : roomRoleLabel(persona.roleId, moderatorRoleId)}</em></strong><small>{persona.tagline}</small></span></label>; })}</div></fieldset>
          <fieldset><legend>发言方式</legend><div className="room-routing-options">{routingPolicyOptions(createRoomKind).map((option) => <label key={option.value}><input type="radio" name="room-routing" checked={routingPolicy === option.value} onChange={() => { setRoutingPolicy(option.value); setCreateError(''); }} /><span><strong>{option.label}</strong><small>{option.detail}</small></span></label>)}</div></fieldset>
          {routingPolicy === 'moderator' ? <label className="room-create-field"><span>主持人</span><Select aria-label="Room 主持人" onValueChange={(value) => { setModeratorRoleId(value); setCreateError(''); }} options={selectedRoleIds.flatMap((roleId) => { const persona = personas.find((item) => item.roleId === roleId); return persona ? [{ value: roleId, label: persona.displayName }] : []; })} value={moderatorRoleId} /></label> : null}
          <label className="room-create-field"><span>共同设定</span><textarea maxLength={8000} rows={3} value={createScenarioPrompt} onChange={(event) => setCreateScenarioPrompt(event.target.value)} placeholder={createRoomKind === 'roleplay' ? '共同背景、关系和交流边界。它不会覆盖安全策略。' : '团队共同遵守的项目背景与交付约束。'} aria-label="Room 共同设定" /></label>
        </form>
        <DialogFooter><Button variant="quiet" disabled={creating || workspacePicking} onClick={() => setCreateOpen(false)}>取消</Button><Button type="submit" form="room-create-form" variant="primary" loading={creating} disabled={(createRoomKind === 'collaboration' && !workspaceRoots.length) || !createTitle.trim() || selectedRoleIds.length < 2 || workspacePicking}>创建 Room</Button></DialogFooter>
      </DialogContent>
    </Dialog>
    <Dialog open={settingsOpen} onOpenChange={(open) => { if (!settingsSaving) { setSettingsOpen(open); if (!open) setSettingsError(''); } }}>
      <DialogContent className="room-settings-dialog">
        <DialogHeader><DialogTitle>Room 设置</DialogTitle><DialogDescription>共同设定、发言路由和角色权限彼此独立；修改后只影响后续回合。</DialogDescription></DialogHeader>
        <form id="room-settings-form" className="room-create-form" onSubmit={(event) => { event.preventDefault(); void saveRoomSettings(); }}>
          {settingsError ? <p className="room-dialog-error" role="alert">{settingsError}</p> : null}
          <div className="room-create-pair">
            <label className="room-create-field"><span>名称</span><input maxLength={120} value={settingsTitle} onChange={(event) => setSettingsTitle(event.target.value)} aria-label="Room 设置名称" /></label>
            <label className="room-create-field"><span>头像</span><Select aria-label="Room 设置头像" onValueChange={setSettingsAvatar} options={roomAvatarOptions()} value={settingsAvatar} /></label>
          </div>
          <label className="room-create-field"><span>简介</span><input maxLength={500} value={settingsDescription} onChange={(event) => setSettingsDescription(event.target.value)} aria-label="Room 设置简介" /></label>
          <fieldset><legend>发言方式</legend><div className="room-routing-options">{routingPolicyOptions(room?.roomKind ?? 'collaboration').map((option) => <label key={option.value}><input type="radio" name="room-settings-routing" checked={settingsRoutingPolicy === option.value} onChange={() => setSettingsRoutingPolicy(option.value)} /><span><strong>{option.label}</strong><small>{option.detail}</small></span></label>)}</div></fieldset>
          {settingsRoutingPolicy === 'moderator' ? <label className="room-create-field"><span>主持人</span><Select aria-label="Room 设置主持人" onValueChange={setSettingsModeratorParticipantId} options={(room?.participants ?? []).map((participant) => ({ value: participant.id, label: participant.displayName }))} value={settingsModeratorParticipantId} /></label> : null}
          <label className="room-create-field"><span>共同设定</span><textarea maxLength={8000} rows={5} value={settingsScenarioPrompt} onChange={(event) => setSettingsScenarioPrompt(event.target.value)} aria-label="Room 设置共同设定" /></label>
        </form>
        <DialogFooter><Button variant="quiet" disabled={settingsSaving} onClick={() => setSettingsOpen(false)}>取消</Button><Button type="submit" form="room-settings-form" variant="primary" loading={settingsSaving} disabled={!settingsTitle.trim()}>保存设置</Button></DialogFooter>
      </DialogContent>
    </Dialog>
    <Dialog open={topicsOpen} onOpenChange={(open) => { if (!topicSaving) { setTopicsOpen(open); if (!open) { setTopicError(''); setTopicEditingId(''); setTopicTitle(''); setTopicSummary(''); } } }}>
      <DialogContent className="room-topics-dialog">
        <DialogHeader><DialogTitle>话题管理</DialogTitle><DialogDescription>话题只限定工作上下文，不复制成员、长期记忆或历史文件。</DialogDescription></DialogHeader>
        {topicError ? <p className="room-dialog-error" role="alert">{topicError}</p> : null}
        <div className="room-topic-manager">
          {(room?.topics ?? []).map((topic) => <div key={topic.id} data-archived={topic.status === 'archived'} data-active={topic.id === room?.activeTopicId}><span><strong>{topic.title}</strong><small>{topic.summary || '暂无摘要'}</small></span><div><Button variant="quiet" disabled={topicSaving} onClick={() => { setTopicEditingId(topic.id); setTopicTitle(topic.title); setTopicSummary(topic.summary); }}>编辑</Button>{topic.status === 'active' && topic.id !== room?.activeTopicId ? <Button variant="quiet" disabled={topicSaving} onClick={() => void updateTopic(topic.id, { activate: true })}>切换</Button> : null}{topic.status === 'active' && topic.id !== room?.activeTopicId ? <IconButton label={`归档话题 ${topic.title}`} icon={<Archive size={15} />} disabled={topicSaving} onClick={() => void updateTopic(topic.id, { archived: true })} tooltip /> : null}</div></div>)}
        </div>
        <form id="room-topic-form" className="room-topic-form" onSubmit={(event) => { event.preventDefault(); void createTopic(); }}>
          <label className="room-create-field"><span>{topicEditingId ? '编辑名称' : '新话题'}</span><input maxLength={120} value={topicTitle} onChange={(event) => setTopicTitle(event.target.value)} placeholder="例如：发布风险" aria-label="话题名称" /></label>
          <label className="room-create-field"><span>摘要</span><textarea maxLength={2000} rows={2} value={topicSummary} onChange={(event) => setTopicSummary(event.target.value)} placeholder="记录这个话题正在解决什么" aria-label="话题摘要" /></label>
        </form>
        <DialogFooter>{topicEditingId ? <Button variant="quiet" disabled={topicSaving} onClick={() => { setTopicEditingId(''); setTopicTitle(''); setTopicSummary(''); }}>取消编辑</Button> : <Button variant="quiet" disabled={topicSaving} onClick={() => setTopicsOpen(false)}>关闭</Button>}<Button type="submit" form="room-topic-form" variant="primary" loading={topicSaving} disabled={!topicTitle.trim()}>{topicEditingId ? '保存话题' : '创建话题'}</Button></DialogFooter>
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
    const reason = textValue(payload.reason);
    const detailByReason: Record<string, string> = {
      explicit_invite: '由用户直接邀请发言',
      mention: '根据明确提及开始处理',
      moderator: '由主持人负责这一轮',
      sequential: '按成员顺序轮到该角色',
      descriptor_match: '根据角色标签与消息内容匹配',
      natural_fallback: '当前没有强匹配，由保底角色承接',
      configured_fallback: '由群组配置的保底角色承接',
    };
    const policy = textValue(payload.routingPolicy) as RoomRoutingPolicy;
    return {
      title: `${target} 已接手`,
      detail: detailByReason[reason] ?? (
        policy === 'moderator'
          ? '由主持人安排处理这轮任务'
          : `${routingPolicyLabel(policy)}已确定负责角色`
      ),
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
function agentSessionItems(value: unknown): AgentSessionPolicySummary[] { const source = record(value); const items = Array.isArray(source.items) ? source.items : Array.isArray(source.sessions) ? source.sessions : []; return items.map(agentSessionValue).filter((item): item is AgentSessionPolicySummary => Boolean(item)); }
function agentSessionValue(value: unknown): AgentSessionPolicySummary | undefined { const item = record(value); if (typeof item.id !== 'string' || !['assistant', 'coordinator'].includes(String(item.mode))) return undefined; return { id: item.id, mode: item.mode as AgentSessionPolicySummary['mode'], status: String(item.status ?? ''), toolProfileVersion: String(item.toolProfileVersion || 'control-center-v1'), toolAllowlistMode: item.toolAllowlistMode === 'explicit' ? 'explicit' : 'profile', allowedTools: Array.isArray(item.allowedTools) ? item.allowedTools.map(String) : [], workspaceRoots: Array.isArray(item.workspaceRoots) ? item.workspaceRoots.map(String) : [] }; }
function roomToolItems(value: unknown): RoomToolPolicyItem[] { const source = record(value); return (Array.isArray(source.items) ? source.items : []).flatMap((value) => { const item = record(value); if (typeof item.id !== 'string' || typeof item.displayName !== 'string') return []; const profileOperations = record(item.profileOperations); return [{ id: item.id, displayName: item.displayName, description: String(item.description ?? ''), sessionModes: Array.isArray(item.sessionModes) ? item.sessionModes.map(String) : [], operations: Array.isArray(item.operations) ? item.operations.map(String) : [], profileOperations: Object.fromEntries(Object.entries(profileOperations).map(([profile, operations]) => [profile, Array.isArray(operations) ? operations.map(String) : []])), enabled: item.enabled === true }]; }); }
function toolAvailableForPolicy(tool: RoomToolPolicyItem, mode: string, profile: string): boolean { return tool.sessionModes.includes(mode) && (tool.profileOperations[profile] ?? []).length > 0; }
function record(value: unknown): Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function uniquePaths(values: string[]): string[] { return values.map((value) => value.trim()).filter((value, index, all) => value.startsWith('/') && all.indexOf(value) === index).slice(0, 12); }
function pathName(path: string): string { return path.split('/').filter(Boolean).at(-1) ?? path; }
function roomPathName(room: RoomSummary): string { return room.workspaceRoots?.[0] ? pathName(room.workspaceRoots[0]) : '未绑定项目'; }
function roomRoleLabel(roleId: string, moderatorRoleId: string): string {
  if (roleId === moderatorRoleId) return '调控者';
  if (roleId === 'hermes-v1') return '调研者';
  if (roleId === 'zhiyou-v1') return '执行者';
  return '协作角色';
}

function participantName(room: RoomSummary, participantId: string): string {
  return room.participants.find((participant) => participant.id === participantId)?.displayName ?? '待接收';
}

function roomWorkStateLabel(state: RoomWorkState): string {
  return {
    queued: '待接收',
    active: '执行中',
    review: '待验收',
    blocked: '已阻塞',
    done: '已完成',
    failed: '未完成',
    cancelled: '已取消',
  }[state];
}

function roomAvatarOptions(): { value: string; label: string }[] {
  return [
    { value: 'briefcase', label: '任务协作' },
    { value: 'members', label: '成员群聊' },
    { value: 'sparkles', label: '角色互动' },
    { value: 'messages', label: '讨论空间' },
  ];
}

function roomAvatarIcon(room: RoomSummary) {
  if (room.avatar === 'sparkles' || room.roomKind === 'roleplay') return <Sparkles size={16} />;
  if (room.avatar === 'briefcase') return <BriefcaseBusiness size={16} />;
  if (room.avatar === 'messages') return <MessagesSquare size={16} />;
  return <UsersRound size={16} />;
}

function routingPolicyOptions(kind: RoomKind): { value: RoomRoutingPolicy; label: string; detail: string }[] {
  const shared: { value: RoomRoutingPolicy; label: string; detail: string }[] = [
    { value: 'sequential', label: '顺序轮流', detail: '每轮切换到下一位成员' },
    { value: 'invite_only', label: '点名邀请', detail: '由你点击决定谁发言' },
    { value: 'manual_mentions', label: '@ 指派', detail: '消息中明确提及一位成员' },
  ];
  return kind === 'roleplay'
    ? [
        { value: 'natural', label: '自然发言', detail: '依据角色标签与内容选择' },
        ...shared,
      ]
    : [
        { value: 'moderator', label: '主持协调', detail: '由主持人判断是否分工' },
        { value: 'natural', label: '语义分派', detail: '依据职责与消息内容选择' },
        ...shared,
      ];
}

function routingPolicyLabel(policy: RoomRoutingPolicy): string {
  return ({
    moderator: '主持协调',
    manual_mentions: '@ 指派',
    sequential: '顺序轮流',
    natural: '自然发言',
    invite_only: '点名邀请',
  } as const)[policy] ?? '结构化路由';
}

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
