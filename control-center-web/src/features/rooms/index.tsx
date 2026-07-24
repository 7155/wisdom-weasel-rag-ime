import { Archive, ArchiveRestore, BriefcaseBusiness, FilePlus2, FolderOpen, GitBranch, LoaderCircle, MessageSquarePlus, MessagesSquare, PanelLeftClose, PanelLeftOpen, PanelRightOpen, Plus, Settings2, ShieldCheck, Sparkles, Trash2, UserMinus, UserPlus, UsersRound, X } from 'lucide-react';
import * as RadioGroup from '@radix-ui/react-radio-group';
import { useEffect, useRef, useState } from 'react';
import { Virtuoso } from 'react-virtuoso';
import { useShallow } from 'zustand/react/shallow';
import { useControlTransport } from '@/app/control-transport';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  EmptyState,
  IconButton,
  SegmentedControl,
  Select,
} from '@/components/primitives';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import { PersonaAvatar } from '@/features/agent/timeline/PersonaAvatar';
import { roleItems } from '@/features/agent/types';
import { useMediaQuery } from '@/features/agent/overlay-dialog';
import { publicErrorText } from '@/features/overview/management-ui';
import { RoomStatusPanel } from './RoomStatusPanel';
import { RoomMemberBoundaryDialog } from './RoomMemberBoundaryDialog';
import { RoomComposer, roomMentionedParticipants } from './composer/RoomComposer';
import { RoomKernelLivePanel } from './kernel/RoomKernelLivePanel';
import { RoomExecutionPhase } from './managed/RoomExecutionPhase';
import {
  type ManagedWorkDraft,
  RoomStartWorkDialog,
} from './managed/RoomStartWorkDialog';
import { RoomTurn } from './timeline/RoomTurn';
import { selectPublicRoomTurnOrder } from './runtime/room-execution-lanes';
import { useRoomLiveSession } from './runtime/use-room-live-session';
import { useRoomLiveStore } from './state/live-store';
import './rooms.css';

export { RoomTurn } from './timeline/RoomTurn';

const emptyRoomTurnIds: string[] = [];

export type RoomCollaborationRole = 'coordinator' | 'researcher' | 'implementer' | 'reviewer' | 'specialist';
export interface RoomParticipant { id: string; sessionId: string; roleId: string; roleVersion: string; displayName: string; collaborationRole?: RoomCollaborationRole; status: string; ordinal: number; }
export type RoomKind = 'collaboration' | 'roleplay';
export type RoomExecutionMode = 'read_only' | 'per_action' | 'workspace_managed' | 'full_trust';
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
  executionMode?: RoomExecutionMode;
  topics?: RoomTopic[];
  artifacts?: RoomArtifact[];
  workItems?: RoomWorkItem[];
  updatedAtMs: number;
  participants: RoomParticipant[];
}
export function RoomsFeature() {
  const transport = useControlTransport();
  const [rooms, setRooms] = useState<RoomSummary[]>([]);
  const [personas, setPersonas] = useState<AgentPersonaV1[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const roomDraftsRef = useRef(new Map<string, string>());
  const roomErrorsRef = useRef(new Map<string, {
    message: string;
    source: 'connection' | 'operation';
  }>());
  const roomSendLocksRef = useRef(new Set<string>());
  const managedWorkReceiptsRef = useRef(new Map<string, string>());
  const selectedRoomIdRef = useRef('');
  const roomRailTriggerRef = useRef<HTMLButtonElement>(null);
  const roomRailCloseRef = useRef<HTMLButtonElement>(null);
  const roomRailRef = useRef<HTMLElement>(null);
  const [roomRailOpen, setRoomRailOpen] = useState(roomRailInitiallyOpen);
  const roomRailOverlay = useMediaQuery('(max-width: 760px)');
  const [statusOpen, setStatusOpen] = useState(false);
  const [workspaceView, setWorkspaceView] = useState<'posts' | 'execution' | 'sessions'>('posts');
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
  const [createExecutionMode, setCreateExecutionMode] = useState<RoomExecutionMode>('workspace_managed');
  const [projectPaths, setProjectPaths] = useState<string[]>([]);
  const [workspaceRoots, setWorkspaceRoots] = useState<string[]>([]);
  const [workspacePicking, setWorkspacePicking] = useState(false);
  const [selectedRoleIds, setSelectedRoleIds] = useState<string[]>([]);
  const [coordinatorRoleId, setCoordinatorRoleId] = useState('');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsTitle, setSettingsTitle] = useState('');
  const [settingsAvatar, setSettingsAvatar] = useState('members');
  const [settingsDescription, setSettingsDescription] = useState('');
  const [settingsScenarioPrompt, setSettingsScenarioPrompt] = useState('');
  const [settingsExecutionMode, setSettingsExecutionMode] = useState<RoomExecutionMode>('workspace_managed');
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [settingsError, setSettingsError] = useState('');
  const [memberSavingRoleId, setMemberSavingRoleId] = useState('');
  const [memberRemovingId, setMemberRemovingId] = useState('');
  const [memberUpdatingId, setMemberUpdatingId] = useState('');
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteConfirmTitle, setDeleteConfirmTitle] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [topicsOpen, setTopicsOpen] = useState(false);
  const [topicTitle, setTopicTitle] = useState('');
  const [topicSummary, setTopicSummary] = useState('');
  const [topicEditingId, setTopicEditingId] = useState('');
  const [topicSaving, setTopicSaving] = useState(false);
  const [topicError, setTopicError] = useState('');
  const [artifactPicking, setArtifactPicking] = useState(false);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const [boundaryParticipant, setBoundaryParticipant] = useState<RoomParticipant>();
  const [abortingSessionIds, setAbortingSessionIds] = useState<Set<string>>(() => new Set());
  const [abortingTurnIds, setAbortingTurnIds] = useState<Set<string>>(() => new Set());
  const [sendingRoomIds, setSendingRoomIds] = useState<Set<string>>(() => new Set());
  const [startWorkOpen, setStartWorkOpen] = useState(false);
  const [startingWork, setStartingWork] = useState(false);
  const visibleTurnOrder = useRoomLiveStore(useShallow((state) => {
    const projection = state.projections[selectedId];
    return projection ? selectPublicRoomTurnOrder(projection) : emptyRoomTurnIds;
  }));

  selectedRoomIdRef.current = selectedId;

  function selectRoomId(roomId: string): void {
    selectedRoomIdRef.current = roomId;
    setSelectedId(roomId);
    setDraft(roomDraftsRef.current.get(roomId) ?? '');
    setError(roomErrorsRef.current.get(roomId)?.message ?? '');
  }

  function persistRoomDraft(roomId: string, value: string): void {
    if (roomId) roomDraftsRef.current.set(roomId, value);
  }

  function updateRoomDraft(roomId: string, value: string): void {
    persistRoomDraft(roomId, value);
    if (selectedRoomIdRef.current === roomId) setDraft(value);
  }

  function setRoomError(
    roomId: string,
    value: string,
    source: 'connection' | 'operation' = 'operation',
  ): void {
    if (roomId) {
      if (value) roomErrorsRef.current.set(roomId, { message: value, source });
      else roomErrorsRef.current.delete(roomId);
    }
    if (selectedRoomIdRef.current === roomId) setError(value);
  }

  function clearRoomConnectionError(roomId: string): void {
    if (roomErrorsRef.current.get(roomId)?.source !== 'connection') return;
    roomErrorsRef.current.delete(roomId);
    if (selectedRoomIdRef.current === roomId) setError('');
  }

  function closeRoomRail(restoreFocus = true): void {
    if (!roomRailOpen) return;
    setRoomRailOpen(false);
    if (restoreFocus) requestAnimationFrame(() => roomRailTriggerRef.current?.focus());
  }

  function closeRoomRailIfOverlay(restoreFocus = true): void {
    if (roomRailOverlay) closeRoomRail(restoreFocus);
  }

  useEffect(() => {
    if (!roomRailOpen || !roomRailOverlay) return;
    roomRailCloseRef.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setRoomRailOpen(false);
        requestAnimationFrame(() => roomRailTriggerRef.current?.focus());
        return;
      }
      if (event.key !== 'Tab') return;
      const focusable = [...(roomRailRef.current?.querySelectorAll<HTMLButtonElement>('button:not([disabled])') ?? [])];
      const first = focusable[0];
      const last = focusable.at(-1);
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', closeOnEscape);
    return () => document.removeEventListener('keydown', closeOnEscape);
  }, [roomRailOpen, roomRailOverlay]);

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
        setSelectedId((current) => {
          const next = items.some((item) => item.id === current)
            ? current
            : items.find((item) => item.status === 'active')?.id ?? items[0]?.id ?? '';
          selectedRoomIdRef.current = next;
          return next;
        });
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
      const loadedSessionRoots = sessionResult.status === 'fulfilled'
        ? sessionWorkspaceRoots(sessionResult.value)
        : [];
      setProjectPaths(uniquePaths([
        ...loadedRooms.flatMap((item) => item.workspaceRoots ?? []),
        ...loadedSessionRoots,
      ]));
    }).finally(() => { if (active) setCatalogLoading(false); });
    return () => { active = false; };
  }, [includeArchived, transport]);

  useEffect(() => {
    if (!selectedId) {
      setDraft('');
      setError('');
      return;
    }
    setDraft(roomDraftsRef.current.get(selectedId) ?? '');
    setError(roomErrorsRef.current.get(selectedId)?.message ?? '');
  }, [selectedId]);
  useRoomLiveSession({
    roomId: selectedId,
    transport,
    onLoadingChange: setSnapshotLoading,
    onSnapshot: (_roomId, snapshot) => {
      const snapshotRoom = snapshot.room as unknown as RoomSummary;
      setRooms((current) => current.map((item) => (
        item.id === snapshotRoom.id ? snapshotRoom : item
      )));
    },
    onMetadata: (roomId, value) => {
      const refreshedRoom = roomFromGetResponse(value, roomId);
      if (!refreshedRoom) return;
      setRooms((current) => current.map((item) => (
        item.id === refreshedRoom.id ? refreshedRoom : item
      )));
    },
    onConnectionRestored: clearRoomConnectionError,
    onConnectionError: (roomId, liveError, fallback) => {
      setRoomError(
        roomId,
        publicErrorText(liveError, fallback),
        'connection',
      );
    },
  });

  const room = rooms.find((item) => item.id === selectedId);
  const activeParticipants = room?.participants.filter((participant) => participant.status === 'active') ?? [];
  const activeWork = room?.workItems?.find((work) => ['blocked', 'review', 'active', 'queued'].includes(work.state));
  async function send(composerDraft = draft): Promise<void> {
    const message = composerDraft.trim();
    if (!room || room.status !== 'active' || !message) return;
    if (roomSendLocksRef.current.has(room.id)) return;
    const addressedParticipants = roomMentionedParticipants(
      activeParticipants,
      message,
    );
    const clientMessageId = `room-web-${crypto.randomUUID()}`;
    roomSendLocksRef.current.add(room.id);
    setSendingRoomIds((current) => new Set(current).add(room.id));
    useRoomLiveStore.getState().appendOptimistic(
      room.id,
      { clientMessageId, text: message, nowMs: Date.now() },
    );
    updateRoomDraft(room.id, '');
    setRoomError(room.id, '');
    try {
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.room.message',
        params: { roomId: room.id },
        body: {
          message,
          clientMessageId,
          ...(addressedParticipants.length
            ? { participantIds: addressedParticipants.map((participant) => participant.id) }
            : {}),
        },
      });
      useRoomLiveStore.getState().acceptMessage(room.id, response);
    }
    catch (requestError) {
      useRoomLiveStore.getState().discardOptimistic(room.id, clientMessageId);
      updateRoomDraft(room.id, message);
      setRoomError(room.id, publicErrorText(requestError, '消息暂时未发送，请稍后重试。'));
    } finally {
      roomSendLocksRef.current.delete(room.id);
      setSendingRoomIds((current) => {
        const next = new Set(current);
        next.delete(room.id);
        return next;
      });
    }
  }
  async function startManagedWork(workDraft: ManagedWorkDraft): Promise<void> {
    if (!room) throw new Error('请先选择一个 Room。');
    if (room.status !== 'active') throw new Error('当前 Room 已归档，不能开始受管执行。');
    if (room.roomKind === 'roleplay') throw new Error('角色群聊不创建受管任务。');
    if (startingWork) return;
    if (activeWork && !managedWorkReceiptsRef.current.has(workDraft.requestId)) {
      throw new Error('当前已有受管任务，请先完成、取消或处理阻塞。');
    }
    const clientMessageId = `room-start-${workDraft.requestId}`;
    const message = managedWorkStartMessage(workDraft);
    setStartingWork(true);
    setRoomError(room.id, '');
    useRoomLiveStore.getState().appendOptimistic(
      room.id,
      { clientMessageId, text: message, nowMs: Date.now() },
    );
    try {
      let workItemId = managedWorkReceiptsRef.current.get(workDraft.requestId) ?? '';
      let workItem: RoomWorkItem | undefined;
      if (!workItemId) {
        const createResponse = await transport.request<Record<string, unknown>>({
          pathId: 'agent.room.workItem.create',
          params: { roomId: room.id },
          body: {
            objective: workDraft.objective,
            expectedOutput: workDraft.expectedOutput,
            acceptanceCriteria: [
              ...workDraft.acceptanceCriteria,
              ...workDraft.forbiddenAreas.map((item) => `不得违反：${item}`),
            ],
            currentOwnerParticipantId: workDraft.ownerParticipantId,
            clientMessageId: `room-work-${workDraft.requestId}`,
          },
        });
        workItem = roomWorkItem(record(createResponse).workItem);
        if (!workItem) throw new Error('服务端没有返回可验证的任务定义。');
        workItemId = workItem.id;
        managedWorkReceiptsRef.current.set(workDraft.requestId, workItemId);
      }
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.room.message',
        params: { roomId: room.id },
        body: {
          message,
          clientMessageId,
          workItemId,
          participantIds: [workDraft.ownerParticipantId],
        },
      });
      useRoomLiveStore.getState().acceptMessage(room.id, response);
      const acceptedWorkItem = roomWorkItem(record(response).workItem) ?? workItem;
      if (acceptedWorkItem) {
        setRooms((current) => current.map((item) => (
          item.id === room.id
            ? {
              ...item,
              workItems: [
                acceptedWorkItem,
                ...(item.workItems ?? []).filter(
                  (candidate) => candidate.id !== acceptedWorkItem.id,
                ),
              ],
            }
            : item
        )));
      }
      managedWorkReceiptsRef.current.delete(workDraft.requestId);
    } catch (requestError) {
      useRoomLiveStore.getState().discardOptimistic(room.id, clientMessageId);
      if (managedWorkReceiptsRef.current.has(workDraft.requestId)) {
        throw new Error('任务定义已保存，但受管执行尚未启动。请重试本次确认。');
      }
      throw new Error(publicErrorText(
        requestError,
        '任务暂时无法开始，请稍后重试。',
      ));
    } finally {
      setStartingWork(false);
    }
  }
  async function abortParticipantTurn(sessionId: string, turnId: string): Promise<void> {
    if (!sessionId || abortingSessionIds.has(sessionId)) return;
    setAbortingSessionIds((current) => new Set(current).add(sessionId));
    const sourceRoomId = room?.id ?? '';
    setRoomError(sourceRoomId, '');
    try {
      await transport.request({
        pathId: 'agent.session.abort',
        params: { sessionId },
      });
      const participantId = room?.participants.find(
        (participant) => participant.sessionId === sessionId,
      )?.id ?? '';
      const roomId = room?.id ?? '';
      if (roomId) {
        useRoomLiveStore.getState().abortParticipant(
          roomId,
          turnId,
          participantId,
          Date.now(),
        );
      }
    } catch (requestError) {
      setRoomError(sourceRoomId, publicErrorText(requestError, '暂时无法停止这个 Agent，请稍后重试。'));
    } finally {
      setAbortingSessionIds((current) => {
        const next = new Set(current);
        next.delete(sessionId);
        return next;
      });
    }
  }
  async function abortRootTurn(turnId: string): Promise<void> {
    if (!room || !turnId || abortingTurnIds.has(turnId)) return;
    setAbortingTurnIds((current) => new Set(current).add(turnId));
    setRoomError(room.id, '');
    try {
      const receipt = await transport.request<Record<string, unknown>>({
        pathId: 'agent.room.abort',
        params: { roomId: room.id },
        body: {
          roomTurnId: turnId,
          clientRequestId: `room-abort-${crypto.randomUUID()}`,
        },
      });
      if (receipt.ok !== true || receipt.status === 'cancellation_pending') {
        const pending = cancellationTargetLabels(receipt.pendingTargets);
        setRoomError(
          room.id,
          pending.length > 0
            ? `停止信号已送达，但仍在确认：${pending.join('、')}。可再次停止，界面不会把它误报为已结束。`
            : '停止信号已送达，但后台尚未返回完整终止凭据。可再次停止。',
        );
        return;
      }
      useRoomLiveStore.getState().abortTurn(
        room.id,
        turnId,
        Date.now(),
      );
    } catch (requestError) {
      setRoomError(room.id, publicErrorText(requestError, '暂时无法停止整条 Room 任务，请稍后重试。'));
    } finally {
      setAbortingTurnIds((current) => {
        const next = new Set(current);
        next.delete(turnId);
        return next;
      });
    }
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
    const timelineDefaults = ['companion-future-v1', 'companion-present-v1', 'companion-firstlight-v1']
      .map((roleId) => eligiblePersonas.find((persona) => persona.roleId === roleId)?.roleId)
      .filter((roleId): roleId is string => Boolean(roleId));
    const defaults = timelineDefaults.length >= 2
      ? timelineDefaults
      : eligiblePersonas.slice(0, Math.min(3, eligiblePersonas.length)).map((persona) => persona.roleId);
    setError('');
    setCreateError('');
    setCreateTitle('');
    setCreateRoomKind('collaboration');
    setCreateExecutionMode('workspace_managed');
    setCreateAvatar('briefcase');
    setCreateDescription('');
    setCreateScenarioPrompt('');
    setWorkspaceRoots(projectPaths.slice(0, 1));
    setSelectedRoleIds(defaults);
    setCoordinatorRoleId(defaults[0] ?? '');
    setCreateOpen(true);
  }
  function updateCreateRoomKind(kind: RoomKind): void {
    const requiredMode = kind === 'collaboration' ? 'coordinator' : 'assistant';
    const eligible = personas.filter((persona) => persona.selectableModes.includes(requiredMode));
    const timelineDefaults = ['companion-future-v1', 'companion-present-v1', 'companion-firstlight-v1']
      .map((roleId) => eligible.find((persona) => persona.roleId === roleId)?.roleId)
      .filter((roleId): roleId is string => Boolean(roleId));
    const defaults = timelineDefaults.length >= 2
      ? timelineDefaults
      : eligible.slice(0, Math.min(3, eligible.length)).map((persona) => persona.roleId);
    setCreateRoomKind(kind);
    setCreateExecutionMode(kind === 'collaboration' ? 'workspace_managed' : 'per_action');
    setCreateAvatar(kind === 'roleplay' ? 'sparkles' : 'briefcase');
    setSelectedRoleIds(defaults);
    setCoordinatorRoleId(defaults[0] ?? '');
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
      if (!next.includes(coordinatorRoleId)) setCoordinatorRoleId(next[0] ?? '');
      return next;
    });
  }
  async function createRoom(): Promise<void> {
    if (creating) return;
    const participants = selectedRoleIds
      .map((roleId) => personas.find((persona) => persona.roleId === roleId))
      .filter((persona): persona is AgentPersonaV1 => Boolean(persona))
      .map((persona) => ({
        roleId: persona.roleId,
        roleVersion: persona.version,
        displayName: persona.displayName,
        ...(createRoomKind === 'collaboration'
          ? { collaborationRole: persona.roleId === coordinatorRoleId ? 'coordinator' : 'implementer' }
          : {}),
      }));
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
          routingPolicy: 'natural',
          workspaceRoots: createRoomKind === 'collaboration' ? workspaceRoots : [],
          executionMode: createExecutionMode,
          ...(createExecutionMode === 'workspace_managed'
            ? { workspaceScopeConfirmation: 'APPROVE_WORKSPACE_SCOPE' }
            : {}),
          ...(createExecutionMode === 'full_trust'
            ? { dangerousModeConfirmation: 'ENABLE_FULL_TRUST' }
            : {}),
          routingConfig: { maxResponders: 1, naturalJitter: createRoomKind === 'roleplay' ? 0.04 : 0, fallbackParticipantId: '' },
        },
      });
      const created = isRoom(record(response).room) ? record(response).room as unknown as RoomSummary : undefined;
      if (!created) throw new Error('服务端没有返回可验证的 Room。');
      setRooms((current) => [created, ...current]);
      selectRoomId(created.id);
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
      selectRoomId(nextRooms.some((item) => item.id === room.id) ? room.id : nextRooms[0]?.id ?? '');
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
    setSettingsExecutionMode(room.executionMode ?? (room.roomKind === 'roleplay' ? 'per_action' : 'workspace_managed'));
    setSettingsError('');
    setSettingsOpen(true);
  }
  async function saveRoomSettings(): Promise<void> {
    if (!room || settingsSaving || !settingsTitle.trim()) return;
    setSettingsSaving(true);
    setSettingsError('');
    try {
      const currentExecutionMode = room.executionMode
        ?? (room.roomKind === 'roleplay' ? 'per_action' : 'workspace_managed');
      const executionModeChanged = settingsExecutionMode !== currentExecutionMode;
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.room.archive',
        params: { roomId: room.id },
        body: {
          title: settingsTitle.trim(),
          avatar: settingsAvatar,
          description: settingsDescription.trim(),
          scenarioPrompt: settingsScenarioPrompt.trim(),
          routingPolicy: room.routingPolicy,
          routingConfig: room.routingConfig ?? { maxResponders: 1, naturalJitter: room.roomKind === 'roleplay' ? 0.04 : 0, fallbackParticipantId: '' },
          ...(executionModeChanged
            ? { executionMode: settingsExecutionMode }
            : {}),
          ...(executionModeChanged && settingsExecutionMode === 'workspace_managed'
            ? { workspaceScopeConfirmation: 'APPROVE_WORKSPACE_SCOPE' }
            : {}),
          ...(executionModeChanged && settingsExecutionMode === 'full_trust'
            ? { dangerousModeConfirmation: 'ENABLE_FULL_TRUST' }
            : {}),
        },
      });
      const updated = isRoom(record(response).room) ? record(response).room as unknown as RoomSummary : undefined;
      if (!updated) throw new Error('服务端没有返回更新后的 Room。');
      setRooms((current) => current.map((item) => item.id === updated.id ? updated : item));
      setSettingsOpen(false);
    } catch (requestError) {
      setSettingsError(publicErrorText(requestError, 'Room 设置暂时无法保存，请稍后重试。'));
    } finally {
      setSettingsSaving(false);
    }
  }
  async function addRoomParticipant(persona: AgentPersonaV1): Promise<void> {
    if (!room || room.status !== 'active' || memberSavingRoleId || activeParticipants.length >= 4) return;
    setMemberSavingRoleId(persona.roleId);
    setSettingsError('');
    try {
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.room.participant.add',
        params: { roomId: room.id },
        body: {
          roleId: persona.roleId,
          roleVersion: persona.version,
          collaborationRole: 'implementer',
        },
      });
      const updated = isRoom(record(response).room) ? record(response).room as unknown as RoomSummary : undefined;
      if (!updated) throw new Error('服务端没有返回新增成员后的 Room。');
      setRooms((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (requestError) {
      setSettingsError(publicErrorText(requestError, '角色暂时无法加入 Room，请稍后重试。'));
    } finally {
      setMemberSavingRoleId('');
    }
  }
  async function removeRoomParticipant(participant: RoomParticipant): Promise<void> {
    if (!room || room.status !== 'active' || memberRemovingId) return;
    setMemberRemovingId(participant.id);
    setSettingsError('');
    try {
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.room.participant.remove',
        params: { roomId: room.id },
        body: { participantId: participant.id },
      });
      const updated = isRoom(record(response).room) ? record(response).room as unknown as RoomSummary : undefined;
      if (!updated) throw new Error('服务端没有返回移除成员后的 Room。');
      setRooms((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (requestError) {
      setSettingsError(publicErrorText(requestError, '角色暂时无法移出 Room；请先完成或转交她名下的工作。'));
    } finally {
      setMemberRemovingId('');
    }
  }
  async function updateRoomParticipantRole(
    participant: RoomParticipant,
    collaborationRole: RoomCollaborationRole,
  ): Promise<void> {
    if (!room || room.status !== 'active' || memberUpdatingId || participant.collaborationRole === collaborationRole) return;
    setMemberUpdatingId(participant.id);
    setSettingsError('');
    try {
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.room.participant.update',
        params: { roomId: room.id },
        body: { participantId: participant.id, collaborationRole },
      });
      const updated = isRoom(record(response).room) ? record(response).room as unknown as RoomSummary : undefined;
      if (!updated) throw new Error('服务端没有返回更新岗位后的 Room。');
      setRooms((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (requestError) {
      setSettingsError(publicErrorText(requestError, '岗位暂时无法修改；请先等待这个角色完成当前回合。'));
    } finally {
      setMemberUpdatingId('');
    }
  }
  async function deleteRoomPermanently(): Promise<void> {
    if (!room || room.status !== 'archived' || deleting || deleteConfirmTitle !== room.title) return;
    setDeleting(true);
    setSettingsError('');
    try {
      await transport.request({
        pathId: 'agent.room.delete',
        params: { roomId: room.id },
        body: { confirmTitle: deleteConfirmTitle },
      });
      const nextRooms = rooms.filter((item) => item.id !== room.id);
      useRoomLiveStore.getState().remove(room.id);
      roomDraftsRef.current.delete(room.id);
      roomErrorsRef.current.delete(room.id);
      setRooms(nextRooms);
      selectRoomId(nextRooms[0]?.id ?? '');
      setDeleteOpen(false);
      setSettingsOpen(false);
      setDeleteConfirmTitle('');
    } catch (requestError) {
      setSettingsError(publicErrorText(requestError, 'Room 暂时无法永久删除；请确认已归档且没有未完成责任。'));
      setDeleteOpen(false);
    } finally {
      setDeleting(false);
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
    const sourceRoomId = room.id;
    if (!room.workspaceRoots?.length) {
      setRoomError(sourceRoomId, '角色扮演 Room 没有项目路径；先在协作 Room 中绑定工作区，才能共享文件。');
      return;
    }
    if (!transport.pickFiles) {
      setRoomError(sourceRoomId, '当前平台不能选择共享文件，请在桌面控制中心中操作。');
      return;
    }
    setArtifactPicking(true);
    setRoomError(sourceRoomId, '');
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
        params: { roomId: sourceRoomId },
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
      setRoomError(sourceRoomId, publicErrorText(requestError, '共享文件暂时无法加入 Room，请确认文件位于授权项目路径内。'));
    } finally {
      setArtifactPicking(false);
    }
  }
  return <>
    <main className="rooms-feature" data-route-id="rooms" data-rail-open={roomRailOpen} data-status-open={statusOpen}>
      <aside ref={roomRailRef} className="rooms-rail" id="rooms-list-drawer" aria-label="Rooms 列表" role={roomRailOpen && roomRailOverlay ? 'dialog' : undefined} aria-modal={roomRailOpen && roomRailOverlay ? true : undefined}>
        <header><span><strong>Rooms</strong><small>多 Agent 协作</small></span><div className="rooms-rail-actions"><IconButton label={includeArchived ? '隐藏已归档 Room' : '显示已归档 Room'} icon={includeArchived ? <ArchiveRestore size={16} /> : <Archive size={16} />} aria-pressed={includeArchived} onClick={() => setIncludeArchived((current) => !current)} tooltip /><IconButton disabled={catalogLoading || creating} label="新建 Room" icon={<MessageSquarePlus size={17} />} onClick={() => { closeRoomRailIfOverlay(false); beginCreateRoom(); }} tooltip /></div><IconButton ref={roomRailCloseRef} className="rooms-rail-mobile-close" label="关闭 Rooms 列表" icon={<X size={17} />} onClick={() => closeRoomRail()} tooltip /></header>
        <div>{rooms.length ? rooms.map((item) => <button type="button" key={item.id} aria-label={`打开 Room：${item.title}`} aria-current={item.id === selectedId} onClick={() => { selectRoomId(item.id); closeRoomRailIfOverlay(); }}>{roomAvatarIcon(item)}<span><strong>{item.title}</strong><small>{item.status === 'archived' ? '已归档 · ' : ''}{item.participants.filter((participant) => participant.status === 'active').map((participant) => participant.displayName).join(' · ')}</small></span></button>) : !catalogLoading ? <p className="rooms-rail-empty">还没有 Room</p> : null}</div>
      </aside>
      <button className="rooms-rail-backdrop" aria-label="关闭 Rooms 列表" disabled={!roomRailOpen} onClick={() => closeRoomRail()} type="button" />
      <section className="room-workspace">
        <header><IconButton ref={roomRailTriggerRef} className="rooms-rail-trigger" label={roomRailOpen ? '收起 Rooms 列表' : '打开 Rooms 列表'} icon={roomRailOpen ? <PanelLeftClose size={17} /> : <PanelLeftOpen size={17} />} aria-controls="rooms-list-drawer" aria-expanded={roomRailOpen} onClick={() => setRoomRailOpen((current) => !current)} tooltip /><span><strong>{room?.title ?? 'Room'}</strong><small>{!room ? '选择或新建群聊' : room.status === 'archived' ? '已归档' : `${room.roomKind === 'roleplay' ? '角色群聊' : roomPathName(room)} · ${activeWork ? '受管执行中' : '对话与对齐'}`}</small></span><SegmentedControl aria-label="Room 工作区" items={[{ value: 'posts', label: 'Posts' }, { value: 'execution', label: '执行' }, { value: 'sessions', label: 'Sessions' }]} onValueChange={(value) => setWorkspaceView(value as typeof workspaceView)} value={workspaceView} /><div className="room-header-actions">{room ? <IconButton label="Room 设置" icon={<Settings2 size={16} />} onClick={beginRoomSettings} tooltip /> : null}{room ? <IconButton label={room.status === 'archived' ? '恢复 Room' : '归档 Room'} icon={room.status === 'archived' ? <ArchiveRestore size={16} /> : <Archive size={16} />} onClick={() => { setError(''); setArchiveOpen(true); }} tooltip /> : null}<IconButton label={statusOpen ? '隐藏 Room 证据栏' : '展开 Room 证据'} icon={<PanelRightOpen size={17} />} onClick={() => setStatusOpen((current) => !current)} tooltip /></div></header>
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
        {workspaceView === 'posts' ? <><div className="room-timeline" aria-label="Room Posts 时间线">
          {room ? visibleTurnOrder.length ? <Virtuoso data={visibleTurnOrder} increaseViewportBy={300} itemContent={(_index, turnId) => <RoomTurn key={turnId} turnId={turnId} roomId={room.id} room={room} personas={personas} abortingSessionIds={abortingSessionIds} abortingTurnIds={abortingTurnIds} onAbortTurn={(rootId) => void abortRootTurn(rootId)} onAbortSession={(sessionId) => void abortParticipantTurn(sessionId, turnId)} />} /> : snapshotLoading ? <p className="room-empty">正在读取 Room Posts…</p> : <EmptyState icon={MessagesSquare} title="还没有公开 Post" description="先对话澄清目标、交付物、验收和禁区；确认后再开始受管执行。" /> : catalogLoading ? <p className="room-empty">正在读取 Rooms…</p> : <EmptyState icon={MessagesSquare} title="选择一个 Room" description="从 Rooms 列表选择，或新建协作 Room。" />}
        </div><div className="room-composer-dock">{room?.roomKind !== 'roleplay' && room ? <RoomExecutionPhase
          activeWork={activeWork}
          ownerName={activeWork ? participantName(room, activeWork.currentOwnerParticipantId) : ''}
          canStart={room.status === 'active' && !startingWork}
          onStart={() => setStartWorkOpen(true)}
        /> : null}{room ? <RoomComposer
          key={room.id}
          room={room}
          personas={personas}
          draft={draft}
          sending={sendingRoomIds.has(room.id)}
          onDraftChange={(value) => {
            persistRoomDraft(room.id, value);
            if (roomErrorsRef.current.has(room.id)) setRoomError(room.id, '');
          }}
          onSend={(value) => void send(value)}
        /> : !catalogLoading ? <RoomComposer
          room={undefined}
          personas={personas}
          draft=""
          sending={false}
          onDraftChange={() => undefined}
          onSend={() => undefined}
        /> : null}</div></> : workspaceView === 'execution' ? <section className="room-execution-workspace" aria-label="Root、Task 与 Dispatch">
          {room ? <RoomKernelLivePanel roomId={room.id} /> : <p className="room-empty">请选择一个 Room。</p>}
        </section> : <section className="room-session-workspace" aria-label="Room 成员运行">
          <header><span><strong>成员运行边界</strong><small>每位伙伴拥有独立 Session；只有显式 Post 进入 Room，思考与工具细节保持私有。</small></span></header>
          <div>{activeParticipants.map((participant) => <article key={participant.id}><PersonaAvatar persona={personas.find((item) => item.roleId === participant.roleId)} size="small" /><span><strong>{participant.displayName}</strong><small>{collaborationRoleLabel(participant.collaborationRole)} · 完整工作权限</small></span><Button variant="quiet" size="small" leadingIcon={<ShieldCheck size={14} />} onClick={() => setBoundaryParticipant(participant)}>查看运行边界</Button></article>)}</div>
          {!activeParticipants.length ? <p className="room-empty">当前没有绑定 Session。</p> : null}
        </section>}
      </section>
      <button className="agent-status-backdrop room-status-backdrop" aria-label="关闭 Room 状态" disabled={!statusOpen} onClick={() => setStatusOpen(false)} type="button" />
      <RoomStatusPanel room={room} roomId={room?.id ?? ''} open={statusOpen} onClose={() => setStatusOpen(false)} />
    </main>
    <RoomStartWorkDialog
      open={startWorkOpen}
      participants={activeParticipants}
      preferredOwnerParticipantId={room?.moderatorParticipantId ?? activeParticipants[0]?.id ?? ''}
      submitting={startingWork}
      onOpenChange={setStartWorkOpen}
      onSubmit={startManagedWork}
    />
    <Dialog open={createOpen} onOpenChange={(open) => { if (!creating) { setCreateOpen(open); if (!open) setCreateError(''); } }}>
      <DialogContent className="room-create-dialog">
        <DialogHeader><DialogTitle>新建 Room</DialogTitle><DialogDescription>直接说话，或随时用 @ 点名角色；任务需要分工时，Agent 会通过结构化交接继续协作。</DialogDescription></DialogHeader>
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
          <fieldset><legend>执行权限</legend><div className="room-kind-options">
            {roomExecutionModeOptions(createRoomKind).map((option) => <label key={option.value}><input type="radio" name="room-execution-mode" checked={createExecutionMode === option.value} onChange={() => setCreateExecutionMode(option.value)} /><span><ShieldCheck size={17} /><strong>{option.label}</strong><small>{option.description}</small></span></label>)}
          </div></fieldset>
          <div className="room-create-pair">
            <label className="room-create-field"><span>名称</span><input maxLength={120} value={createTitle} onChange={(event) => { setCreateTitle(event.target.value); setCreateError(''); }} placeholder={createRoomKind === 'roleplay' ? '例如：深夜茶话会' : '例如：发布前检查'} aria-label="Room 名称" /></label>
            <label className="room-create-field"><span>头像</span><Select aria-label="Room 头像" onValueChange={setCreateAvatar} options={roomAvatarOptions()} value={createAvatar} /></label>
          </div>
          <label className="room-create-field"><span>简介</span><input maxLength={500} value={createDescription} onChange={(event) => setCreateDescription(event.target.value)} placeholder="一句话说明这个 Room 的用途" aria-label="Room 简介" /></label>
          <fieldset><legend>参与角色 <small>{selectedRoleIds.length}/4</small></legend><div className="room-role-options">{personas.filter((persona) => persona.selectableModes.includes(createRoomKind === 'roleplay' ? 'assistant' : 'coordinator')).map((persona) => { const checked = selectedRoleIds.includes(persona.roleId); return <label key={`${persona.roleId}:${persona.version}`}><input type="checkbox" checked={checked} disabled={!checked && selectedRoleIds.length >= 4} onChange={() => toggleParticipant(persona.roleId)} /><PersonaAvatar persona={persona} size="small" /><span><strong>{persona.displayName}<em>{createRoomKind === 'roleplay' ? '群聊角色' : roomRoleLabel(persona.roleId, coordinatorRoleId)}</em></strong><small>{persona.tagline}</small></span></label>; })}</div></fieldset>
          <label className="room-create-field"><span>共同设定</span><textarea maxLength={8000} rows={3} value={createScenarioPrompt} onChange={(event) => setCreateScenarioPrompt(event.target.value)} placeholder={createRoomKind === 'roleplay' ? '共同背景、关系和交流边界。它不会覆盖安全策略。' : '团队共同遵守的项目背景与交付约束。'} aria-label="Room 共同设定" /></label>
        </form>
        <DialogFooter><Button variant="quiet" disabled={creating || workspacePicking} onClick={() => setCreateOpen(false)}>取消</Button><Button type="submit" form="room-create-form" variant="primary" loading={creating} disabled={(createRoomKind === 'collaboration' && !workspaceRoots.length) || !createTitle.trim() || selectedRoleIds.length < 2 || workspacePicking}>创建 Room</Button></DialogFooter>
      </DialogContent>
    </Dialog>
    <Dialog open={settingsOpen} onOpenChange={(open) => { if (!settingsSaving && !memberSavingRoleId && !memberRemovingId && !memberUpdatingId && !deleting) { setSettingsOpen(open); if (!open) setSettingsError(''); } }}>
      <DialogContent className="room-settings-dialog">
        <DialogHeader><DialogTitle>Room 设置</DialogTitle><DialogDescription>共同设定和角色权限彼此独立；普通消息与 @ 点名始终可用，修改只影响后续回合。</DialogDescription></DialogHeader>
        <form id="room-settings-form" className="room-create-form" onSubmit={(event) => { event.preventDefault(); void saveRoomSettings(); }}>
          {settingsError ? <p className="room-dialog-error" role="alert">{settingsError}</p> : null}
          <div className="room-create-pair">
            <label className="room-create-field"><span>名称</span><input maxLength={120} value={settingsTitle} onChange={(event) => setSettingsTitle(event.target.value)} aria-label="Room 设置名称" /></label>
            <label className="room-create-field"><span>头像</span><Select aria-label="Room 设置头像" onValueChange={setSettingsAvatar} options={roomAvatarOptions()} value={settingsAvatar} /></label>
          </div>
          <label className="room-create-field"><span>简介</span><input maxLength={500} value={settingsDescription} onChange={(event) => setSettingsDescription(event.target.value)} aria-label="Room 设置简介" /></label>
          <label className="room-create-field"><span>执行权限</span><Select aria-label="Room 执行权限" onValueChange={(value) => setSettingsExecutionMode(value as RoomExecutionMode)} options={roomExecutionModeOptions(room?.roomKind ?? 'collaboration').map((option) => ({ value: option.value, label: option.label }))} value={settingsExecutionMode} /></label>
          <fieldset className="room-member-manager">
            <legend>参与角色 <small>{activeParticipants.length}/4</small></legend>
            <p>默认岗位只影响未分派任务的路由和提示词；具体任务仍按责任账本动态交接。新成员不会重放此前完整聊天。</p>
            <div>{personas.filter((persona) => persona.selectableModes.includes(room?.roomKind === 'roleplay' ? 'assistant' : 'coordinator')).map((persona) => {
              const participant = activeParticipants.find((item) => item.roleId === persona.roleId && item.roleVersion === persona.version);
              const isRequiredModerator = room?.routingPolicy === 'moderator' && participant?.id === room.moderatorParticipantId;
              const mutationPending = Boolean(memberRemovingId || memberSavingRoleId || memberUpdatingId);
              const removeDisabled = !participant || room?.status !== 'active' || activeParticipants.length <= 2 || isRequiredModerator || mutationPending;
              return <article key={`${persona.roleId}:${persona.version}`} data-active={Boolean(participant)}>
                <PersonaAvatar persona={persona} size="small" />
                <span><strong>{persona.displayName}</strong><small>{participant ? `${room?.roomKind === 'roleplay' ? '群聊角色' : roomParticipantRoleLabel(participant)} · 已加入` : persona.tagline}</small></span>
                <div className="room-member-actions">
                  {participant && room?.roomKind !== 'roleplay' ? <Select aria-label={`${persona.displayName} 的默认岗位`} disabled={room?.status !== 'active' || mutationPending} onValueChange={(value) => void updateRoomParticipantRole(participant, value as RoomCollaborationRole)} options={roomCollaborationRoleOptions()} value={participant.collaborationRole ?? 'implementer'} /> : null}
                  {participant ? <IconButton label={`将 ${persona.displayName} 移出 Room`} icon={memberRemovingId === participant.id ? <LoaderCircle className="ui-spin" size={15} /> : <UserMinus size={15} />} disabled={removeDisabled} onClick={() => void removeRoomParticipant(participant)} tooltip /> : <IconButton label={`邀请 ${persona.displayName} 加入 Room`} icon={memberSavingRoleId === persona.roleId ? <LoaderCircle className="ui-spin" size={15} /> : <UserPlus size={15} />} disabled={room?.status !== 'active' || activeParticipants.length >= 4 || mutationPending} onClick={() => void addRoomParticipant(persona)} tooltip />}
                </div>
              </article>;
            })}</div>
          </fieldset>
          <label className="room-create-field"><span>共同设定</span><textarea maxLength={8000} rows={5} value={settingsScenarioPrompt} onChange={(event) => setSettingsScenarioPrompt(event.target.value)} aria-label="Room 设置共同设定" /></label>
        </form>
        <section className="room-danger-zone"><span><strong>永久删除</strong><small>{room?.status === 'archived' ? '删除 Room、对话审计和专属 Agent Session，不可恢复。' : '为防止误删，必须先归档 Room 并清空未完成责任。'}</small></span><Button variant="danger" leadingIcon={<Trash2 size={15} />} disabled={room?.status !== 'archived' || settingsSaving || deleting} onClick={() => { setDeleteConfirmTitle(''); setDeleteOpen(true); }}>删除 Room</Button></section>
        <DialogFooter><Button variant="quiet" disabled={settingsSaving || Boolean(memberSavingRoleId || memberRemovingId || memberUpdatingId)} onClick={() => setSettingsOpen(false)}>取消</Button><Button type="submit" form="room-settings-form" variant="primary" loading={settingsSaving} disabled={!settingsTitle.trim() || Boolean(memberSavingRoleId || memberRemovingId || memberUpdatingId)}>保存设置</Button></DialogFooter>
      </DialogContent>
    </Dialog>
    <Dialog open={deleteOpen} onOpenChange={(open) => { if (!deleting) { setDeleteOpen(open); if (!open) setDeleteConfirmTitle(''); } }}>
      <DialogContent><DialogHeader><DialogTitle>永久删除这个 Room？</DialogTitle><DialogDescription>这会删除“{room?.title}”的消息、协作审计和专属 Agent Session。请输入完整 Room 名称确认。</DialogDescription></DialogHeader><label className="room-create-field"><span>Room 名称</span><input autoComplete="off" value={deleteConfirmTitle} onChange={(event) => setDeleteConfirmTitle(event.target.value)} aria-label="输入 Room 名称确认永久删除" /></label><DialogFooter><Button variant="quiet" disabled={deleting} onClick={() => setDeleteOpen(false)}>取消</Button><Button variant="danger" leadingIcon={<Trash2 size={15} />} loading={deleting} disabled={!room || deleteConfirmTitle !== room.title} onClick={() => void deleteRoomPermanently()}>永久删除</Button></DialogFooter></DialogContent>
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
    <RoomMemberBoundaryDialog participant={boundaryParticipant} onClose={() => setBoundaryParticipant(undefined)} />
  </>;
}



function roomItems(value: unknown): RoomSummary[] { const source = record(value); return (Array.isArray(source.items) ? source.items : Array.isArray(source.rooms) ? source.rooms : []).filter(isRoom); }
function isRoom(value: unknown): value is RoomSummary { const item = record(value); return typeof item.id === 'string' && typeof item.title === 'string' && Array.isArray(item.participants); }
function sessionWorkspaceRoots(value: unknown): string[] {
  const source = record(value);
  const items = Array.isArray(source.items)
    ? source.items
    : Array.isArray(source.sessions) ? source.sessions : [];
  return items.flatMap((value) => {
    const roots = record(value).workspaceRoots;
    return Array.isArray(roots) ? roots.map(String) : [];
  });
}
function roomParticipantRoleLabel(participant: RoomParticipant): string {
  if (participant.collaborationRole === 'coordinator') return '协作主持';
  if (participant.collaborationRole === 'researcher') return '调研与核对';
  if (participant.collaborationRole === 'implementer') return '实施与交付';
  if (participant.collaborationRole === 'reviewer') return '独立验收';
  if (participant.collaborationRole === 'specialist') return '领域判断';
  return '协作角色';
}
function cancellationTargetLabels(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const labels: Record<string, string> = {
    provider: '模型生成',
    tool: '工具调用',
    shell: '命令行进程',
    retry: '自动重试',
    compaction: '上下文压缩',
    branch_summary: '分支整理',
    timer: '定时唤醒',
    continuation: '后续任务',
    session: 'Agent Session',
  };
  return [...new Set(value.flatMap((raw) => {
    if (typeof raw === 'string' && raw.trim()) return [raw.trim()];
    const item = record(raw);
    const surface = textValue(item.surface);
    if (!surface) return [];
    const targetCount = Array.isArray(item.targetIds) ? item.targetIds.length : 0;
    const label = labels[surface] ?? '后台任务';
    return [targetCount > 1 ? `${label}（${targetCount} 项）` : label];
  }))];
}
function textValue(value: unknown): string { return typeof value === 'string' ? value : ''; }
function roomRailInitiallyOpen(): boolean {
  return typeof window === 'undefined'
    || typeof window.matchMedia !== 'function'
    || !window.matchMedia('(max-width: 760px)').matches;
}
function record(value: unknown): Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function uniquePaths(values: string[]): string[] { return values.map((value) => value.trim()).filter((value, index, all) => value.startsWith('/') && all.indexOf(value) === index).slice(0, 12); }
function pathName(path: string): string { return path.split('/').filter(Boolean).at(-1) ?? path; }
function roomPathName(room: RoomSummary): string { return room.workspaceRoots?.[0] ? pathName(room.workspaceRoots[0]) : '未绑定项目'; }

function roomExecutionModeOptions(roomKind: RoomKind): Array<{
  value: RoomExecutionMode;
  label: string;
  description: string;
}> {
  const base = [
    { value: 'read_only' as const, label: '只读', description: '只读自动，写入与 Shell 全拦' },
    { value: 'per_action' as const, label: '每次确认', description: '写入与 Shell 逐项批准' },
  ];
  if (roomKind === 'roleplay') return base;
  return [
    ...base,
    { value: 'workspace_managed' as const, label: '工作区托管', description: '范围内自动，越界再问' },
    { value: 'full_trust' as const, label: '完全信任', description: '最大自治，仍保留硬边界' },
  ];
}
function roomRoleLabel(roleId: string, coordinatorRoleId: string): string {
  return roleId === coordinatorRoleId ? '协作主持' : '实施者';
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

function roomWorkItem(value: unknown): RoomWorkItem | undefined {
  const candidate = record(value);
  return (
    typeof candidate.id === 'string'
    && candidate.id.length > 0
    && typeof candidate.objective === 'string'
    && typeof candidate.currentOwnerParticipantId === 'string'
  )
    ? candidate as unknown as RoomWorkItem
    : undefined;
}

function roomFromGetResponse(value: unknown, roomId: string): RoomSummary | undefined {
  const candidate = record(record(value).room);
  return (
    candidate.id === roomId
    && typeof candidate.title === 'string'
    && Array.isArray(candidate.participants)
  )
    ? candidate as unknown as RoomSummary
    : undefined;
}

function managedWorkStartMessage(draft: ManagedWorkDraft): string {
  const sections = [
    '确认开始受管执行。',
    `目标：${draft.objective}`,
    `交付物：${draft.expectedOutput}`,
    `验收条件：\n${draft.acceptanceCriteria.map((item) => `- ${item}`).join('\n')}`,
  ];
  if (draft.forbiddenAreas.length) {
    sections.push(
      `禁区与不可做：\n${draft.forbiddenAreas.map((item) => `- ${item}`).join('\n')}`,
    );
  }
  return sections.join('\n\n');
}

function roomAvatarOptions(): { value: string; label: string }[] {
  return [
    { value: 'briefcase', label: '任务协作' },
    { value: 'members', label: '成员群聊' },
    { value: 'sparkles', label: '角色互动' },
    { value: 'messages', label: '讨论空间' },
  ];
}

function roomCollaborationRoleOptions(): { value: RoomCollaborationRole; label: string }[] {
  return [
    { value: 'coordinator', label: '协作主持' },
    { value: 'implementer', label: '实施与交付' },
    { value: 'researcher', label: '调研与核对' },
    { value: 'reviewer', label: '独立验收' },
    { value: 'specialist', label: '领域专家' },
  ];
}

function roomAvatarIcon(room: RoomSummary) {
  if (room.avatar === 'sparkles' || room.roomKind === 'roleplay') return <Sparkles size={16} />;
  if (room.avatar === 'briefcase') return <BriefcaseBusiness size={16} />;
  if (room.avatar === 'messages') return <MessagesSquare size={16} />;
  return <UsersRound size={16} />;
}

function collaborationRoleLabel(role: RoomParticipant['collaborationRole']): string {
  if (role === 'coordinator') return '协作主持';
  if (role === 'researcher') return '调研与核对';
  if (role === 'reviewer') return '独立验收';
  if (role === 'specialist') return '领域专家';
  return '实施与交付';
}
