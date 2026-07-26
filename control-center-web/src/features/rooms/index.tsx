import { Archive, ArchiveRestore, BriefcaseBusiness, FilePlus2, FolderOpen, GitBranch, LoaderCircle, MessageSquarePlus, MessagesSquare, MoreHorizontal, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen, Plus, Settings2, ShieldCheck, Sparkles, Trash2, UserMinus, UserPlus, UsersRound, X } from 'lucide-react';
import * as RadioGroup from '@radix-ui/react-radio-group';
import { useEffect, useRef, useState } from 'react';
import { Virtuoso } from 'react-virtuoso';
import { useShallow } from 'zustand/react/shallow';
import { useControlTransport } from '@/app/control-transport';
import { useComposerClearance } from '@/components/layout/use-composer-clearance';
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
  Menu,
  MenuContent,
  MenuItem,
  MenuTrigger,
  SegmentedControl,
  Select,
} from '@/components/primitives';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import { PersonaAvatar } from '@/features/agent/timeline/PersonaAvatar';
import { roleItems } from '@/features/agent/types';
import { useMediaQuery, useModalPanel } from '@/features/agent/overlay-dialog';
import { publicErrorText } from '@/features/overview/management-ui';
import { RoomStatusPanel } from './RoomStatusPanel';
import { RoomMemberBoundaryDialog } from './RoomMemberBoundaryDialog';
import { RoomPaneResizer } from './RoomPaneResizer';
import { RoomComposer, roomMentionedParticipants } from './composer/RoomComposer';
import { RoomKernelLivePanel } from './kernel/RoomKernelLivePanel';
import {
  roomCollaborationRoleDescription,
  roomCollaborationRoleLabel,
} from './room-copy';
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
const roomTimelineComponents = {
  Header: RoomTimelineScrollHeader,
  Footer: RoomTimelineScrollFooter,
};

function RoomTimelineScrollHeader() {
  return <div aria-hidden="true" className="room-timeline__header-space" />;
}

function RoomTimelineScrollFooter() {
  return <div aria-hidden="true" className="room-timeline__footer-space" />;
}

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
  const roomDraftsRef = useRef(roomDraftsStore);
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
  const roomStatusToggleRef = useRef<HTMLButtonElement>(null);
  const roomStatusRef = useRef<HTMLElement>(null);
  const roomWorkspaceRef = useRef<HTMLElement>(null);
  useComposerClearance(roomWorkspaceRef);
  const [roomRailOpen, setRoomRailOpen] = useState(roomRailInitiallyOpen);
  const roomRailOverlay = useMediaQuery('(max-width: 760px)');
  const roomStatusOverlay = useMediaQuery('(max-width: 1360px)');
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
  const roomRailModal = roomRailOverlay && roomRailOpen;
  const roomStatusModal = roomStatusOverlay && statusOpen;

  selectedRoomIdRef.current = selectedId;

  function selectRoomId(roomId: string): void {
    selectedRoomIdRef.current = roomId;
    setSelectedId(roomId);
    setWorkspaceView('posts');
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
    if (roomRailOverlay) setRoomRailOpen(false);
  }, [roomRailOverlay]);

  useEffect(() => {
    if (roomStatusOverlay) setStatusOpen(false);
  }, [roomStatusOverlay]);

  useModalPanel({
    active: roomStatusModal,
    panelRef: roomStatusRef,
    returnFocusRef: roomStatusToggleRef,
    onClose: () => setStatusOpen(false),
  });

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
        setRoomCatalogError(publicErrorText(roomResult.reason, '协作空间暂时无法读取，请稍后重试。'));
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
  const roomSettingsChanged = Boolean(room && (
    settingsTitle.trim() !== room.title
    || settingsAvatar !== (room.avatar ?? (room.roomKind === 'roleplay' ? 'sparkles' : 'briefcase'))
    || settingsDescription.trim() !== (room.description ?? '').trim()
    || settingsScenarioPrompt.trim() !== (room.scenarioPrompt ?? '').trim()
    || settingsExecutionMode !== (
      room.executionMode
      ?? (room.roomKind === 'roleplay' ? 'per_action' : 'workspace_managed')
    )
  ));
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
    if (!room) throw new Error('请先选择一个协作空间。');
    if (room.status !== 'active') throw new Error('这个协作空间已收起，不能开始任务。');
    if (room.roomKind === 'roleplay') throw new Error('“一起聊聊”不会创建执行任务。');
    if (startingWork) return;
    if (activeWork && !managedWorkReceiptsRef.current.has(workDraft.requestId)) {
      throw new Error('当前已有任务，请先完成、取消或处理阻塞。');
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
        throw new Error('任务已保存，但首次执行尚未启动。请重试。');
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
      setRoomError(sourceRoomId, publicErrorText(requestError, '暂时无法停止这位伙伴，请稍后重试。'));
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
      setRoomError(room.id, publicErrorText(requestError, '暂时无法停止整条协作任务，请稍后重试。'));
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
      setError('至少需要两位可用伙伴，才能开始多人协作。');
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
      setCreateError('当前页面不能选择本地工作目录，请在桌面应用中开始协作。');
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
          ? {
              collaborationRole: recommendedCreateRole(
                persona.roleId,
                selectedRoleIds,
                coordinatorRoleId,
              ),
            }
          : {}),
      }));
    if (participants.length < 2) {
      setCreateError('请选择 2 至 4 位伙伴。');
      return;
    }
    if (createRoomKind === 'collaboration' && !workspaceRoots.length) {
      setCreateError('请先选择伙伴可以工作的目录。');
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
      if (!created) throw new Error('服务端没有返回可验证的协作空间。');
      setRooms((current) => [created, ...current]);
      selectRoomId(created.id);
      setCreateOpen(false);
    } catch (requestError) { setCreateError(publicErrorText(requestError, '协作空间暂时无法创建，请稍后重试。')); }
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
      if (!updated || updated.status !== expectedStatus) throw new Error(`服务端没有确认协作空间已${archived ? '收起' : '恢复'}。`);
      const nextRooms = archived && !includeArchived
        ? rooms.filter((item) => item.id !== room.id)
        : rooms.map((item) => item.id === room.id ? updated : item);
      setRooms(nextRooms);
      selectRoomId(nextRooms.some((item) => item.id === room.id) ? room.id : nextRooms[0]?.id ?? '');
      setArchiveOpen(false);
    } catch (requestError) { setError(publicErrorText(requestError, '协作空间状态暂时无法更新，请稍后重试。')); }
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
    if (!room || settingsSaving || !settingsTitle.trim() || !roomSettingsChanged) return;
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
      if (!updated) throw new Error('服务端没有返回更新后的协作空间。');
      setRooms((current) => current.map((item) => item.id === updated.id ? updated : item));
      setSettingsOpen(false);
    } catch (requestError) {
      setSettingsError(publicErrorText(requestError, '协作空间设置暂时无法保存，请稍后重试。'));
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
      if (!updated) throw new Error('服务端没有返回加入伙伴后的协作空间。');
      setRooms((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (requestError) {
      setSettingsError(publicErrorText(requestError, '这位伙伴暂时无法加入，请稍后重试。'));
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
      if (!updated) throw new Error('服务端没有返回移出伙伴后的协作空间。');
      setRooms((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (requestError) {
      setSettingsError(publicErrorText(requestError, '这位伙伴暂时无法移出；请先完成或转交她名下的工作。'));
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
      if (!updated) throw new Error('服务端没有返回更新后的伙伴分工。');
      setRooms((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (requestError) {
      setSettingsError(publicErrorText(requestError, '分工暂时无法修改；请先等待这位伙伴完成当前回合。'));
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
      setSettingsError(publicErrorText(requestError, '暂时无法永久删除这个协作空间；请确认它已收起，并且没有未完成任务。'));
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
      setRoomError(sourceRoomId, '“一起聊聊”不会访问项目目录；请在任务协作空间中分享工作文件。');
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
      setRoomError(sourceRoomId, publicErrorText(requestError, '暂时无法分享这个文件，请确认它位于已授权的工作目录中。'));
    } finally {
      setArtifactPicking(false);
    }
  }
  return <>
    <main className="rooms-feature" data-route-id="rooms" data-rail-open={roomRailOpen} data-status-open={statusOpen}>
      <aside ref={roomRailRef} className="rooms-rail" id="rooms-list-drawer" aria-hidden={roomStatusModal || undefined} aria-label="协作空间列表" inert={roomStatusModal ? true : undefined} role={roomRailModal ? 'dialog' : undefined} aria-modal={roomRailModal ? true : undefined}>
        <header><span><strong>协作空间</strong><small>和伙伴一起聊，也一起把事做完</small></span><div className="rooms-rail-actions"><IconButton label={includeArchived ? '隐藏已收起的协作空间' : '显示已收起的协作空间'} icon={includeArchived ? <ArchiveRestore size={16} /> : <Archive size={16} />} aria-pressed={includeArchived} onClick={() => setIncludeArchived((current) => !current)} tooltip /><IconButton disabled={catalogLoading || creating} label="开始新的协作" icon={<MessageSquarePlus size={17} />} onClick={() => { closeRoomRailIfOverlay(false); beginCreateRoom(); }} tooltip /></div><IconButton ref={roomRailCloseRef} className="rooms-rail-mobile-close" label="关闭协作空间列表" icon={<X size={17} />} onClick={() => closeRoomRail()} tooltip /></header>
        <div>{rooms.length ? rooms.map((item) => <button type="button" key={item.id} aria-label={`打开协作空间：${item.title}`} aria-current={item.id === selectedId} onClick={() => { selectRoomId(item.id); closeRoomRailIfOverlay(); }}>{roomAvatarIcon(item)}<span><strong>{item.title}</strong><small>{item.status === 'archived' ? '已收起 · ' : ''}{item.participants.filter((participant) => participant.status === 'active').map((participant) => participant.displayName).join(' · ')}</small></span></button>) : !catalogLoading ? <p className="rooms-rail-empty">还没有协作空间</p> : null}</div>
      </aside>
      <RoomPaneResizer side="rail" />
      <button className="rooms-rail-backdrop" aria-hidden="true" disabled={!roomRailModal} tabIndex={-1} onClick={() => closeRoomRail()} type="button" />
      <section ref={roomWorkspaceRef} className="room-workspace" aria-hidden={roomRailModal || roomStatusModal || undefined} inert={roomRailModal || roomStatusModal ? true : undefined}>
        <header><IconButton ref={roomRailTriggerRef} className="rooms-rail-trigger" label={roomRailOpen ? '收起协作空间列表' : '打开协作空间列表'} icon={roomRailOpen ? <PanelLeftClose size={17} /> : <PanelLeftOpen size={17} />} aria-controls="rooms-list-drawer" aria-expanded={roomRailOpen} onClick={() => { if (!roomRailOpen && roomStatusModal) setStatusOpen(false); setRoomRailOpen((current) => !current); }} tooltip /><span><strong>{room?.title ?? '协作空间'}</strong><small>{!room ? '选一个协作空间，或开始新的对话' : room.status === 'archived' ? '已收起' : `${room.roomKind === 'roleplay' ? '一起聊聊' : roomPathName(room)} · ${activeWork ? '正在完成任务' : '先把目标聊清楚'}`}</small></span><SegmentedControl aria-label="协作空间视图" items={roomWorkspaceViewOptions(room?.roomKind)} onValueChange={(value) => setWorkspaceView(value as typeof workspaceView)} value={workspaceView} /><div className="room-header-actions"><span className="room-header-actions__desktop">{room ? <IconButton label="设置这个协作空间" icon={<Settings2 size={16} />} onClick={beginRoomSettings} tooltip /> : null}{room ? <Menu><MenuTrigger asChild><IconButton label="更多协作空间操作" icon={<MoreHorizontal size={17} />} tooltip /></MenuTrigger><MenuContent align="end"><MenuItem onSelect={() => { setError(''); setArchiveOpen(true); }}>{room.status === 'archived' ? <ArchiveRestore size={15} /> : <Archive size={15} />}{room.status === 'archived' ? '恢复协作空间' : '收起协作空间'}</MenuItem></MenuContent></Menu> : null}</span>{room ? <span className="room-header-actions__mobile"><Menu><MenuTrigger asChild><IconButton label="更多协作空间操作" icon={<MoreHorizontal size={17} />} tooltip /></MenuTrigger><MenuContent align="end"><MenuItem onSelect={beginRoomSettings}><Settings2 size={15} />设置协作空间</MenuItem><MenuItem onSelect={() => { setError(''); setArchiveOpen(true); }}>{room.status === 'archived' ? <ArchiveRestore size={15} /> : <Archive size={15} />}{room.status === 'archived' ? '恢复协作空间' : '收起协作空间'}</MenuItem></MenuContent></Menu></span> : null}<IconButton ref={roomStatusToggleRef} label={statusOpen ? '关闭协作进展' : '看看协作进展'} icon={statusOpen ? <PanelRightClose size={17} /> : <PanelRightOpen size={17} />} onClick={() => { if (!statusOpen && roomRailModal) setRoomRailOpen(false); setStatusOpen((current) => !current); }} tooltip /></div></header>
        {room ? <div className="room-context-bar">
          <div className="room-topic-tabs" aria-label="协作话题">
            <MessagesSquare size={14} />
            {(room.topics ?? []).filter((topic) => topic.status === 'active').map((topic) => <button type="button" key={topic.id} aria-current={topic.id === room.activeTopicId} onClick={() => { if (topic.id !== room.activeTopicId) void updateTopic(topic.id, { activate: true }); }}>{topic.title}</button>)}
            <IconButton label="管理话题" icon={<Plus size={14} />} disabled={topicSaving} onClick={() => { setTopicError(''); setTopicsOpen(true); }} tooltip />
          </div>
          <div className="room-context-actions">
            {activeWork ? <span className="room-work-summary" data-state={activeWork.state} title={activeWork.objective}><GitBranch size={13} />{roomWorkStateLabel(activeWork.state)} · {participantName(room, activeWork.currentOwnerParticipantId)} · {activeWork.objective}</span> : <span>{room.description || (room.roomKind === 'roleplay' ? '让几位伙伴一起聊聊' : '先聊清楚，再一起把事情做完')}</span>}
            {room.roomKind !== 'roleplay' ? <IconButton label="分享工作文件" icon={artifactPicking ? <LoaderCircle className="ui-spin" size={15} /> : <FilePlus2 size={15} />} disabled={artifactPicking || room.status !== 'active'} onClick={() => void addRoomArtifact()} tooltip /> : null}
          </div>
        </div> : <div aria-hidden="true" className="room-context-bar room-context-bar--empty" />}
        <div className="room-error-slot" aria-live="polite">
          {error ? <p className="room-error" role="alert">{error}</p> : null}
          {!error && roomCatalogError ? <p className="room-error" role="alert">{roomCatalogError}</p> : null}
          {!error && !roomCatalogError && roleCatalogError ? <p className="room-catalog-warning" role="status">{roleCatalogError}</p> : null}
        </div>
        {workspaceView === 'posts' ? <><div className="room-timeline" aria-label="协作对话时间线">
          {room ? visibleTurnOrder.length ? <Virtuoso alignToBottom components={roomTimelineComponents} data={visibleTurnOrder} followOutput={(isAtBottom) => isAtBottom ? 'auto' : false} increaseViewportBy={300} itemContent={(_index, turnId) => <RoomTurn key={turnId} turnId={turnId} roomId={room.id} room={room} personas={personas} abortingSessionIds={abortingSessionIds} abortingTurnIds={abortingTurnIds} onAbortTurn={(rootId) => void abortRootTurn(rootId)} onAbortSession={(sessionId) => void abortParticipantTurn(sessionId, turnId)} />} /> : snapshotLoading ? <p className="room-empty">正在读取对话…</p> : <EmptyState icon={MessagesSquare} title="还没有公开消息" description="先对话澄清目标、交付物、验收和禁区；确认后再开始任务。" /> : catalogLoading ? <p className="room-empty">正在读取协作空间…</p> : <EmptyState icon={MessagesSquare} title="选择一个协作空间" description="从左侧选择，或新建一个协作空间。" />}
        </div><div className="room-composer-dock"><div className="room-composer-cluster">{room?.roomKind !== 'roleplay' && room ? <RoomExecutionPhase
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
        /> : null}</div></div></> : workspaceView === 'execution' ? <section className="room-execution-workspace" aria-label="任务流转与验收">
          {room ? <RoomKernelLivePanel roomId={room.id} /> : <p className="room-empty">请选择一个协作空间。</p>}
        </section> : <section className="room-session-workspace" aria-label="伙伴与权限">
          <header><span><strong>伙伴与工作权限</strong><small>每位伙伴保留自己的工作上下文；分工负责引导协作，真正能做什么仍由工作目录、工具和你的授权决定。</small></span></header>
          <div>{activeParticipants.map((participant) => <article key={participant.id}><PersonaAvatar persona={personas.find((item) => item.roleId === participant.roleId)} size="small" /><span><strong>{participant.displayName}</strong><small>{roomCollaborationRoleLabel(participant.collaborationRole)} · {roomExecutionModeLabel(room?.executionMode)}</small></span><Button variant="quiet" size="small" leadingIcon={<ShieldCheck size={14} />} onClick={() => setBoundaryParticipant(participant)}>查看能做什么</Button></article>)}</div>
          {!activeParticipants.length ? <p className="room-empty">还没有伙伴加入这个协作空间。</p> : null}
        </section>}
      </section>
      <button className="agent-status-backdrop room-status-backdrop" aria-hidden="true" disabled={!roomStatusModal} tabIndex={-1} onClick={() => setStatusOpen(false)} type="button" />
      <RoomPaneResizer side="status" />
      <RoomStatusPanel ref={roomStatusRef} room={room} roomId={room?.id ?? ''} open={statusOpen} modal={roomStatusModal} onClose={() => setStatusOpen(false)} />
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
        <DialogHeader><DialogTitle>开始一起做事</DialogTitle><DialogDescription>先选这次是要完成任务，还是只想和几位伙伴聊聊。任务会先对齐目标，再开始执行。</DialogDescription></DialogHeader>
        <form id="room-create-form" className="room-create-form" onSubmit={(event) => { event.preventDefault(); void createRoom(); }}>
          {createError ? <p className="room-dialog-error" role="alert">{createError}</p> : null}
          <fieldset><legend>这次想怎么一起</legend><div className="room-kind-options">
            <label><input type="radio" name="room-kind" checked={createRoomKind === 'collaboration'} onChange={() => updateCreateRoomKind('collaboration')} /><span><BriefcaseBusiness size={17} /><strong>一起完成任务</strong><small>对齐目标后，伙伴可以分工、交接和验收</small></span></label>
            <label><input type="radio" name="room-kind" checked={createRoomKind === 'roleplay'} onChange={() => updateCreateRoomKind('roleplay')} /><span><Sparkles size={17} /><strong>一起聊聊</strong><small>只共享对话背景，不会访问项目文件</small></span></label>
          </div></fieldset>
          <label className="room-create-field"><span>取个名字 <small>必填</small></span><input maxLength={120} value={createTitle} onChange={(event) => { setCreateTitle(event.target.value); setCreateError(''); }} placeholder={createRoomKind === 'roleplay' ? '例如：深夜茶话会' : '例如：发布前检查'} aria-label="协作空间名称" /></label>
          <fieldset><legend>邀请伙伴 <small>至少 2 位 · {selectedRoleIds.length}/4</small></legend><div className="room-role-options">{personas.filter((persona) => persona.selectableModes.includes(createRoomKind === 'roleplay' ? 'assistant' : 'coordinator')).map((persona) => { const checked = selectedRoleIds.includes(persona.roleId); return <label key={`${persona.roleId}:${persona.version}`}><input type="checkbox" checked={checked} disabled={!checked && selectedRoleIds.length >= 4} onChange={() => toggleParticipant(persona.roleId)} /><PersonaAvatar persona={persona} size="small" /><span><strong>{persona.displayName}<em>{roomCreateParticipantLabel(createRoomKind, checked, persona.roleId, selectedRoleIds, coordinatorRoleId)}</em></strong><small>{persona.tagline}</small></span></label>; })}</div></fieldset>
          {createRoomKind === 'collaboration' ? <section className="room-create-projects" aria-label="工作目录">
            <header><strong>在哪个目录工作</strong><small>必选</small></header>
            {projectPaths.length ? <RadioGroup.Root aria-label="最近使用的工作目录" value={workspaceRoots[0] ?? ''} onValueChange={(value) => { setWorkspaceRoots([value]); setCreateError(''); }}>{projectPaths.map((path) => <RadioGroup.Item key={path} value={path} title={path}><FolderOpen size={16} /><span><strong>{pathName(path)}</strong><small>{path}</small></span></RadioGroup.Item>)}</RadioGroup.Root> : null}
            {workspaceRoots[0] && !projectPaths.includes(workspaceRoots[0]) ? <div className="room-create-project-picked" title={workspaceRoots.join('\n')}><FolderOpen size={16} /><span><strong>{pathName(workspaceRoots[0])}</strong><small>{workspaceRoots[0]}</small></span></div> : null}
            <Button type="button" variant="quiet" leadingIcon={workspacePicking ? <LoaderCircle className="ui-spin" size={15} /> : <FolderOpen size={15} />} disabled={workspacePicking || creating} onClick={() => void pickWorkspaceRoot()}>{workspaceRoots.length ? '换一个目录' : '选择工作目录'}</Button>
          </section> : null}
          {createRoomKind === 'collaboration' ? <fieldset><legend>允许伙伴怎样工作</legend><div className="room-kind-options">
            {roomExecutionModeOptions(createRoomKind).map((option) => <label key={option.value}><input type="radio" name="room-execution-mode" checked={createExecutionMode === option.value} onChange={() => setCreateExecutionMode(option.value)} /><span><ShieldCheck size={17} /><strong>{option.label}</strong><small>{option.description}</small></span></label>)}
          </div></fieldset> : null}
          <details className="room-create-optional">
            <summary>补充背景与外观 <small>可选</small></summary>
            <div>
              <div className="room-create-pair">
                <label className="room-create-field"><span>{createRoomKind === 'roleplay' ? '想聊些什么' : '这次大致想做什么'}</span><input maxLength={500} value={createDescription} onChange={(event) => setCreateDescription(event.target.value)} placeholder={createRoomKind === 'roleplay' ? '给伙伴一个轻松、明确的话题' : '任务细节可以稍后在对话中一起确认'} aria-label="协作空间简介" /></label>
                <label className="room-create-field"><span>图标</span><Select aria-label="协作空间图标" onValueChange={setCreateAvatar} options={roomAvatarOptions()} value={createAvatar} /></label>
              </div>
              <label className="room-create-field"><span>{createRoomKind === 'roleplay' ? '共同背景' : '一起工作的约定'}</span><textarea maxLength={8000} rows={3} value={createScenarioPrompt} onChange={(event) => setCreateScenarioPrompt(event.target.value)} placeholder={createRoomKind === 'roleplay' ? '可以写下彼此关系、共同背景，以及不希望触碰的话题。' : '可以写下项目背景、不能改动的地方和交付习惯。'} aria-label={createRoomKind === 'roleplay' ? '共同背景' : '协作约定'} /></label>
            </div>
          </details>
        </form>
        <DialogFooter><Button variant="quiet" disabled={creating || workspacePicking} onClick={() => setCreateOpen(false)}>先不开始</Button><Button type="submit" form="room-create-form" variant="primary" loading={creating} disabled={(createRoomKind === 'collaboration' && !workspaceRoots.length) || !createTitle.trim() || selectedRoleIds.length < 2 || workspacePicking}>{createRoomKind === 'roleplay' ? '开始群聊' : '开始协作'}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
    <Dialog open={settingsOpen} onOpenChange={(open) => { if (!settingsSaving && !memberSavingRoleId && !memberRemovingId && !memberUpdatingId && !deleting) { setSettingsOpen(open); if (!open) setSettingsError(''); } }}>
      <DialogContent className="room-settings-dialog">
        <DialogHeader><DialogTitle>设置协作空间</DialogTitle><DialogDescription>{room?.roomKind === 'roleplay' ? '名称和共同背景会在保存后更新；伙伴邀请会单独立即生效。已经发生的对话不会被改写。' : '名称、协作约定和工作权限会在保存后从下一轮生效；伙伴与分工会单独立即更新。'}</DialogDescription></DialogHeader>
        <form id="room-settings-form" className="room-create-form" onSubmit={(event) => { event.preventDefault(); void saveRoomSettings(); }}>
          {settingsError ? <p className="room-dialog-error" role="alert">{settingsError}</p> : null}
          <div className="room-create-pair">
            <label className="room-create-field"><span>名称</span><input maxLength={120} value={settingsTitle} onChange={(event) => setSettingsTitle(event.target.value)} aria-label="协作空间名称" /></label>
            <label className="room-create-field"><span>图标</span><Select aria-label="协作空间图标" onValueChange={setSettingsAvatar} options={roomAvatarOptions()} value={settingsAvatar} /></label>
          </div>
          <label className="room-create-field"><span>简介</span><input maxLength={500} value={settingsDescription} onChange={(event) => setSettingsDescription(event.target.value)} aria-label="协作空间简介" /></label>
          {room?.roomKind !== 'roleplay' ? <label className="room-create-field"><span>工作权限</span><Select aria-label="工作权限" onValueChange={(value) => setSettingsExecutionMode(value as RoomExecutionMode)} options={roomExecutionModeOptions('collaboration').map((option) => ({ value: option.value, label: option.label }))} value={settingsExecutionMode} /></label> : null}
          <fieldset className="room-member-manager">
            <legend>伙伴 <small>至少 2 位 · {activeParticipants.length}/4</small></legend>
            <p>这里的邀请、移出与分工调整会立即生效，但不会扩大工具权限。新伙伴从下一轮开始参与，不会补读此前的完整对话；任务中仍可随时点名或正式交接。</p>
            <div>{personas.filter((persona) => persona.selectableModes.includes(room?.roomKind === 'roleplay' ? 'assistant' : 'coordinator')).map((persona) => {
              const participant = activeParticipants.find((item) => item.roleId === persona.roleId && item.roleVersion === persona.version);
              const isRequiredModerator = room?.routingPolicy === 'moderator' && participant?.id === room.moderatorParticipantId;
              const mutationPending = Boolean(memberRemovingId || memberSavingRoleId || memberUpdatingId);
              const removeDisabled = !participant || room?.status !== 'active' || activeParticipants.length <= 2 || isRequiredModerator || mutationPending;
              return <article key={`${persona.roleId}:${persona.version}`} data-active={Boolean(participant)}>
                <PersonaAvatar persona={persona} size="small" />
                <span><strong>{persona.displayName}</strong><small>{participant ? room?.roomKind === 'roleplay' ? '一起聊天 · 已加入' : `${roomCollaborationRoleLabel(participant.collaborationRole)} · ${roomCollaborationRoleDescription(participant.collaborationRole)}` : persona.tagline}</small></span>
                <div className="room-member-actions">
                  {participant && room?.roomKind !== 'roleplay' ? <Select aria-label={`${persona.displayName} 负责什么`} disabled={room?.status !== 'active' || mutationPending} onValueChange={(value) => void updateRoomParticipantRole(participant, value as RoomCollaborationRole)} options={roomCollaborationRoleOptions(participant.collaborationRole)} value={participant.collaborationRole ?? 'implementer'} /> : null}
                  {participant ? <IconButton label={`移出 ${persona.displayName}`} icon={memberRemovingId === participant.id ? <LoaderCircle className="ui-spin" size={15} /> : <UserMinus size={15} />} disabled={removeDisabled} onClick={() => void removeRoomParticipant(participant)} tooltip /> : <IconButton label={`邀请 ${persona.displayName}`} icon={memberSavingRoleId === persona.roleId ? <LoaderCircle className="ui-spin" size={15} /> : <UserPlus size={15} />} disabled={room?.status !== 'active' || activeParticipants.length >= 4 || mutationPending} onClick={() => void addRoomParticipant(persona)} tooltip />}
                </div>
              </article>;
            })}</div>
          </fieldset>
          <label className="room-create-field"><span>{room?.roomKind === 'roleplay' ? '共同背景' : '一起工作的约定'}</span><textarea maxLength={8000} rows={5} value={settingsScenarioPrompt} onChange={(event) => setSettingsScenarioPrompt(event.target.value)} aria-label={room?.roomKind === 'roleplay' ? '共同背景' : '协作约定'} /></label>
        </form>
        <section className="room-danger-zone"><span><strong>永久删除</strong><small>{room?.status === 'archived' ? '这会删除对话、协作记录和伙伴工作记录，无法恢复。' : '为防止误删，请先收起这个协作空间并结束未完成任务。'}</small></span><Button variant="danger" leadingIcon={<Trash2 size={15} />} disabled={room?.status !== 'archived' || settingsSaving || deleting} onClick={() => { setDeleteConfirmTitle(''); setDeleteOpen(true); }}>删除协作空间</Button></section>
        <DialogFooter><Button variant="quiet" disabled={settingsSaving || Boolean(memberSavingRoleId || memberRemovingId || memberUpdatingId)} onClick={() => setSettingsOpen(false)}>关闭</Button><Button type="submit" form="room-settings-form" variant="primary" loading={settingsSaving} disabled={!settingsTitle.trim() || !roomSettingsChanged || Boolean(memberSavingRoleId || memberRemovingId || memberUpdatingId)}>保存更改</Button></DialogFooter>
      </DialogContent>
    </Dialog>
    <Dialog open={deleteOpen} onOpenChange={(open) => { if (!deleting) { setDeleteOpen(open); if (!open) setDeleteConfirmTitle(''); } }}>
      <DialogContent><DialogHeader><DialogTitle>永久删除这个协作空间？</DialogTitle><DialogDescription>这会删除“{room?.title}”的消息、协作记录和伙伴工作记录。请输入完整名称确认。</DialogDescription></DialogHeader><label className="room-create-field"><span>协作空间名称</span><input autoComplete="off" value={deleteConfirmTitle} onChange={(event) => setDeleteConfirmTitle(event.target.value)} aria-label="输入协作空间名称确认永久删除" /></label><DialogFooter><Button variant="quiet" disabled={deleting} onClick={() => setDeleteOpen(false)}>取消</Button><Button variant="danger" leadingIcon={<Trash2 size={15} />} loading={deleting} disabled={!room || deleteConfirmTitle !== room.title} onClick={() => void deleteRoomPermanently()}>永久删除</Button></DialogFooter></DialogContent>
    </Dialog>
    <Dialog open={topicsOpen} onOpenChange={(open) => { if (!topicSaving) { setTopicsOpen(open); if (!open) { setTopicError(''); setTopicEditingId(''); setTopicTitle(''); setTopicSummary(''); } } }}>
      <DialogContent className="room-topics-dialog">
        <DialogHeader><DialogTitle>整理话题</DialogTitle><DialogDescription>用话题把讨论分开，伙伴和历史不会被复制。切换后，下一条消息会沿用新的话题上下文。</DialogDescription></DialogHeader>
        {topicError ? <p className="room-dialog-error" role="alert">{topicError}</p> : null}
        <div className="room-topic-manager">
          {(room?.topics ?? []).map((topic) => <div key={topic.id} data-archived={topic.status === 'archived'} data-active={topic.id === room?.activeTopicId}><span><strong>{topic.title}</strong><small>{topic.summary || '还没有摘要'}</small></span><div><Button variant="quiet" disabled={topicSaving} onClick={() => { setTopicEditingId(topic.id); setTopicTitle(topic.title); setTopicSummary(topic.summary); }}>编辑</Button>{topic.status === 'active' && topic.id !== room?.activeTopicId ? <Button variant="quiet" disabled={topicSaving} onClick={() => void updateTopic(topic.id, { activate: true })}>聊这个话题</Button> : null}{topic.status === 'active' && topic.id !== room?.activeTopicId ? <IconButton label={`归档话题 ${topic.title}`} icon={<Archive size={15} />} disabled={topicSaving} onClick={() => void updateTopic(topic.id, { archived: true })} tooltip /> : null}</div></div>)}
        </div>
        <form id="room-topic-form" className="room-topic-form" onSubmit={(event) => { event.preventDefault(); void createTopic(); }}>
          <label className="room-create-field"><span>{topicEditingId ? '编辑名称' : '新话题'}</span><input maxLength={120} value={topicTitle} onChange={(event) => setTopicTitle(event.target.value)} placeholder="例如：发布风险" aria-label="话题名称" /></label>
          <label className="room-create-field"><span>摘要</span><textarea maxLength={2000} rows={2} value={topicSummary} onChange={(event) => setTopicSummary(event.target.value)} placeholder="记录这个话题正在解决什么" aria-label="话题摘要" /></label>
        </form>
        <DialogFooter>{topicEditingId ? <Button variant="quiet" disabled={topicSaving} onClick={() => { setTopicEditingId(''); setTopicTitle(''); setTopicSummary(''); }}>取消编辑</Button> : <Button variant="quiet" disabled={topicSaving} onClick={() => setTopicsOpen(false)}>关闭</Button>}<Button type="submit" form="room-topic-form" variant="primary" loading={topicSaving} disabled={!topicTitle.trim()}>{topicEditingId ? '保存话题' : '创建话题'}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
    <Dialog open={archiveOpen} onOpenChange={(open) => { if (!archiving) setArchiveOpen(open); }}>
      <DialogContent><DialogHeader><DialogTitle>{room?.status === 'archived' ? '恢复这个协作空间？' : '先把这个协作空间收起来？'}</DialogTitle><DialogDescription>{room?.status === 'archived' ? `“${room.title}”会回到列表，可以继续聊天和协作。` : `“${room?.title}”会从当前列表收起，但对话和交付仍会安全保留在本机。`}</DialogDescription></DialogHeader>{error ? <p className="room-dialog-error" role="alert">{error}</p> : null}<DialogFooter><Button variant="quiet" disabled={archiving} onClick={() => setArchiveOpen(false)}>保持原样</Button><Button variant={room?.status === 'archived' ? 'primary' : 'danger'} loading={archiving} onClick={() => void updateRoomArchiveState(room?.status !== 'archived')}>{room?.status === 'archived' ? '恢复协作空间' : '收起协作空间'}</Button></DialogFooter></DialogContent>
    </Dialog>
    <RoomMemberBoundaryDialog
      executionMode={room?.executionMode}
      participant={boundaryParticipant}
      workspaceRoots={room?.workspaceRoots ?? []}
      onClose={() => setBoundaryParticipant(undefined)}
    />
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
    session: '伙伴工作记录',
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
/* Drafts survive route unmount (the route is lazy-mounted): module scope, not
   component refs — the pattern Clowder gets right. */
const roomDraftsStore = new Map<string, string>();
((globalThis as { __RAG_DRAFT_STORES__?: Array<{ clear(): void }> }).__RAG_DRAFT_STORES__ ??= []).push(roomDraftsStore);

function roomRailInitiallyOpen(): boolean {
  return typeof window === 'undefined'
    || typeof window.matchMedia !== 'function'
    || !window.matchMedia('(max-width: 760px)').matches;
}
function record(value: unknown): Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function uniquePaths(values: string[]): string[] { return values.map((value) => value.trim()).filter((value, index, all) => value.startsWith('/') && all.indexOf(value) === index).slice(0, 12); }
function pathName(path: string): string { return path.split('/').filter(Boolean).at(-1) ?? path; }
function roomPathName(room: RoomSummary): string { return room.workspaceRoots?.[0] ? pathName(room.workspaceRoots[0]) : '未选择工作目录'; }

function roomExecutionModeOptions(roomKind: RoomKind): Array<{
  value: RoomExecutionMode;
  label: string;
  description: string;
}> {
  const base = [
    { value: 'read_only' as const, label: '只读', description: '可以查看文件；写入和命令都不执行' },
    { value: 'per_action' as const, label: '每次确认', description: '每次写文件或运行命令前都先问你' },
  ];
  if (roomKind === 'roleplay') return base;
  return [
    ...base,
    { value: 'workspace_managed' as const, label: '工作区托管', description: '在选定目录内自主工作，越界时再问你' },
    { value: 'full_trust' as const, label: '完全信任', description: '在选定目录内持续工作；危险系统操作仍禁止' },
  ];
}

function roomWorkspaceViewOptions(roomKind: RoomKind | undefined) {
  if (roomKind === 'roleplay') {
    return [
      { value: 'posts' as const, label: '对话' },
      { value: 'sessions' as const, label: '伙伴' },
    ];
  }
  return [
    { value: 'posts' as const, label: '对话' },
    { value: 'execution' as const, label: '任务' },
    { value: 'sessions' as const, label: '伙伴' },
  ];
}

function roomExecutionModeLabel(value: RoomExecutionMode | undefined): string {
  return {
    read_only: '只读',
    per_action: '每次确认',
    workspace_managed: '工作区托管',
    full_trust: '完全信任',
  }[value ?? 'per_action'];
}
function recommendedCreateRole(
  roleId: string,
  selectedRoleIds: string[],
  coordinatorRoleId: string,
): RoomCollaborationRole {
  if (roleId === coordinatorRoleId) return 'coordinator';
  const collaboratorIndex = selectedRoleIds
    .filter((selectedRoleId) => selectedRoleId !== coordinatorRoleId)
    .indexOf(roleId);
  return (['implementer', 'reviewer', 'researcher'] as const)[collaboratorIndex] ?? 'implementer';
}

function roomCreateParticipantLabel(
  roomKind: RoomKind,
  selected: boolean,
  roleId: string,
  selectedRoleIds: string[],
  coordinatorRoleId: string,
): string {
  if (!selected) return '可邀请';
  if (roomKind === 'roleplay') return '一起聊天';
  return roomCollaborationRoleLabel(
    recommendedCreateRole(roleId, selectedRoleIds, coordinatorRoleId),
  );
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
    { value: 'briefcase', label: '任务' },
    { value: 'members', label: '伙伴' },
    { value: 'sparkles', label: '灵感' },
    { value: 'messages', label: '对话' },
  ];
}

function roomCollaborationRoleOptions(
  currentRole?: RoomCollaborationRole,
): { value: RoomCollaborationRole; label: string; disabled?: boolean }[] {
  const options: { value: RoomCollaborationRole; label: string; disabled?: boolean }[] = [
    { value: 'coordinator', label: roomCollaborationRoleLabel('coordinator') },
    { value: 'implementer', label: roomCollaborationRoleLabel('implementer') },
    { value: 'researcher', label: roomCollaborationRoleLabel('researcher') },
    { value: 'reviewer', label: roomCollaborationRoleLabel('reviewer') },
  ];
  if (currentRole === 'specialist') {
    options.push({
      value: 'specialist',
      label: roomCollaborationRoleLabel('specialist'),
      disabled: true,
    });
  }
  return options;
}

function roomAvatarIcon(room: RoomSummary) {
  if (room.avatar === 'sparkles' || room.roomKind === 'roleplay') return <Sparkles size={16} />;
  if (room.avatar === 'briefcase') return <BriefcaseBusiness size={16} />;
  if (room.avatar === 'messages') return <MessagesSquare size={16} />;
  return <UsersRound size={16} />;
}
