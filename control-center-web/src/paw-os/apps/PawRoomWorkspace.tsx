import {
  Archive,
  CircleAlert,
  ExternalLink,
  Focus,
  GitBranch,
  ListChecks,
  LoaderCircle,
  MessageCircle,
  Orbit,
  Plus,
  Settings2,
  StopCircle,
  UserMinus,
  UserPlus,
  Users,
  X,
  type LucideIcon,
} from 'lucide-react';
import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { useControlTransport } from '@/app/control-transport';
import { Select } from '@/components/primitives';
import { isComposerAttachmentMimeType } from '@/contracts/attachment-policy';
import type { RoomActivityProjection, RoomAttachmentReceipt } from '@/contracts/room-reducer';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import type { ControlRequest, PickedFile } from '@/platform/transport';
import { GenericUserInputCard } from '@/features/agent/review/AgentReviewDialogs';
import { QueueTray, useConversationQueue } from '@/features/conversation-ui';
import { usePawOsDesktop } from '@/features/paw-os/surface-context';
import { publicErrorText } from '@/features/overview/management-ui';
import {
  publicAgentErrorText,
  ROOM_WORKSPACE_MISSING_TEXT,
  SESSION_WORKSPACE_MISSING_TEXT,
} from '@/features/agent/public-error';
import { TraceAgentHandoffButton } from '@/features/trace-agent/handoff';
import { RoomComposer, roomMentionedParticipants } from '@/features/rooms/composer/RoomComposer';
import { roomCollaborationRoleLabel, roomPlanetName } from '@/features/rooms/room-copy';
import { latestPendingGroupedRoomInput, type PendingRoomQuestion } from '@/features/rooms/room-question';
import {
  RoomPermissionPolicyEditor,
  roomCollaborationRoleOptions,
  roomPermissionLayerPresentation,
  roomWorkStateLabel,
} from '@/features/rooms/room-presentation';
import {
  selectActivePublicRoomTurn,
  selectPublicRoomTurnOrder,
} from '@/features/rooms/runtime/room-execution-lanes';
import { useRoomLiveSession } from '@/features/rooms/runtime/use-room-live-session';
import { usePageVisibility } from '@/platform/use-page-visibility';
import { pulsePawCompositionForRuntimeEvents } from '../runtime/composition-pulse';
import {
  createRuntimeToolWindowProjector,
  shouldAutoOpenRuntimeToolWindow,
} from '../runtime/runtime-tool-window';
import { PawWindowChromePortal, usePawWindowChromeTarget } from '../shell/PawWindowChrome';
import { roomProjection, useRoomLiveStore } from '@/features/rooms/state/live-store';
import {
  parseRoomPermissionPolicy,
  roomPermissionPoliciesEqual,
  roomPermissionPolicyNeedsDangerousConfirmation,
  roomPermissionPolicyNeedsWorkspaceConfirmation,
  type RoomPermissionPolicy,
  type RoomSummary,
  type RoomWorkItem,
} from '@/features/rooms/room-types';
import { PawRoomConversation, roomProcessWindowRequest } from './PawRoomConversation';
import { PawRoomFocusOverview } from './PawRoomFocusOverview';
import { PawRoomRoundSheet } from './PawRoomRoundSheet';
import type { RoomRoundTaskRow } from './room-round-task-sheet';
/* 星空按钮按下之前，星空代码不进入 Room 默认对话的 bundle 路径。 */
import { LazyPawRoomStarfield } from './PawStarfieldLazy';
import { buildRoomFocusProjection, roomFocusHasCoordinator, roomFocusOriginLabel, type RoomFocusProjection } from './room-focus-projection';
import {
  roomCollaborationPlanetRequests,
  roomPartnerSessionWindowRequest,
  roomPlanetObserverWindowRequest,
} from './room-satellite-auto-open';
/* Shared conversation modules (tool result panels, diff reader) style the
 * Room's tool receipts too; the Room window must not depend on a Session
 * window having loaded them first. */
import '@/features/agent/agent.css';
import '@/features/rooms/rooms.css';

export { PawRoomConversation } from './PawRoomConversation';

type RoomToolPanel = 'focus' | 'governance';

type OptimisticSteerReceipt = {
  clientActionId: string;
  message: string;
  participantId: string;
};

type RoomStartConfirmation = {
  gateId: string;
  objective: string;
  workItemId: string;
  restoreDraft?: string;
  restoreAttachments?: RoomAttachmentReceipt[];
  optimisticClientMessageId?: string;
};

const roomToolPanelLabels: Record<RoomToolPanel, string> = {
  focus: '态势',
  governance: '治理',
};

const roomToolPanelIcons: Record<RoomToolPanel, LucideIcon> = {
  focus: Focus,
  governance: Settings2,
};
const roomToolPanelItems = Object.keys(roomToolPanelLabels) as RoomToolPanel[];

/* This is the active-participant ceiling enforced by agent-room.v1 and
   AgentRoomService. The displayed count still comes only from the current
   Room snapshot; this constant is a capacity rule, not a second roster. */
const ROOM_PARTICIPANT_LIMIT = 8;
const ROOM_TIMELINE_END_THRESHOLD_PX = 96;

export function followRoomTimelineIfReaderAtEnd(
  timeline: HTMLElement | null,
  scheduleFrame: (callback: FrameRequestCallback) => number = requestAnimationFrame,
): boolean {
  if (!timeline) return false;
  const readerIsAtEnd = () => (
    timeline.scrollHeight - timeline.clientHeight - timeline.scrollTop
    <= ROOM_TIMELINE_END_THRESHOLD_PX
  );
  if (!readerIsAtEnd()) return false;
  scheduleFrame(() => {
    if (!readerIsAtEnd()) return;
    if (typeof timeline.scrollTo === 'function') {
      timeline.scrollTo({ top: timeline.scrollHeight, behavior: 'smooth' });
    } else {
      timeline.scrollTop = timeline.scrollHeight;
    }
  });
  return true;
}

export function PawRoomWorkspace({
  active = true,
  initialDraft,
  initialError,
  participantProcessLocation = 'session-window',
  personas,
  record,
  recordId,
  onRoomUpdated,
}: {
  active?: boolean;
  initialDraft?: string;
  initialError?: string;
  /** Extension Apps can keep public Room inspection inside their own surface. */
  participantProcessLocation?: 'session-window' | 'room-transcript';
  personas: AgentPersonaV1[];
  record?: RoomSummary;
  recordId: string;
  onRoomUpdated: (room: RoomSummary) => void;
}) {
  const transport = useControlTransport();
  const desktop = usePawOsDesktop();
  const windowChromeTarget = usePawWindowChromeTarget();
  const pageVisible = usePageVisibility();
  // A covered-but-open PAW window is still a live conversation. Focus only
  // controls interaction/animation; document visibility owns network pause.
  const liveActive = pageVisible;
  const timelineRef = useRef<HTMLDivElement>(null);
  const runtimeWarmupSessionIdsRef = useRef(new Set<string>());
  const [draft, setDraft] = useState(initialDraft ?? '');
  const [attachments, setAttachments] = useState<RoomAttachmentReceipt[]>([]);
  const [sending, setSending] = useState(false);
  const [optimisticSteer, setOptimisticSteer] = useState<OptimisticSteerReceipt | null>(null);
  const optimisticSteerRef = useRef<OptimisticSteerReceipt | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(initialError ?? '');
  const [startConfirmation, setStartConfirmation] = useState<RoomStartConfirmation | null>(null);
  const [panel, setPanel] = useState<RoomToolPanel | 'none'>('none');
  const [embeddedFocusActive, setEmbeddedFocusActive] = useState(false);
  const roomFocusGroup = `room:${recordId}`;
  const desktopFocusGroup = desktop?.collaborationFocusGroup;
  const hasDesktopFocusSource = desktopFocusGroup !== undefined;
  const collaborationFocusActive = hasDesktopFocusSource
    ? desktopFocusGroup === roomFocusGroup
    : embeddedFocusActive;
  const previousFocusRef = useRef(collaborationFocusActive);
  useEffect(() => {
    const gate = record?.startGate;
    if (gate?.status === 'pending') {
      setStartConfirmation((current) => ({
        gateId: gate.gateId,
        objective: gate.objective,
        workItemId: gate.workItemId,
        ...(current?.gateId === gate.gateId
          ? {
              restoreDraft: current.restoreDraft,
              restoreAttachments: current.restoreAttachments,
              optimisticClientMessageId: current.optimisticClientMessageId,
            }
          : {}),
      }));
    } else if (!gate || gate.status === 'confirmed') {
      setStartConfirmation(null);
    }
  }, [record?.id, record?.startGate?.status, record?.startGate?.gateId, record?.startGate?.objective, record?.startGate?.workItemId]);
  const [view, setView] = useState<'rounds' | 'conversation' | 'starfield'>('rounds');
  const [selectedParticipantId, setSelectedParticipantId] = useState('');
  const collaborationTriggerRef = useRef<HTMLButtonElement>(null);
  const [abortingTurnIds, setAbortingTurnIds] = useState<Set<string>>(() => new Set());
  const [collaborationOpenFailures, setCollaborationOpenFailures] = useState<Set<string>>(() => new Set());
  const [resumeErrorByRow, setResumeErrorByRow] = useState<Record<string, string>>({});
  const [resumingWorkItemId, setResumingWorkItemId] = useState('');
  const [recoveryState, setRecoveryState] = useState<'recovering' | 'failed' | 'synced'>('recovering');
  const runtimeToolWindow = useMemo(() => createRuntimeToolWindowProjector(), [recordId]);

  useEffect(() => {
    if (initialDraft !== undefined) setDraft(initialDraft);
    if (initialError) setError(initialError);
  }, [initialDraft, initialError]);

  useEffect(() => {
    setView('rounds');
    setPanel('none');
    setEmbeddedFocusActive(false);
    setSelectedParticipantId('');
    setCollaborationOpenFailures(new Set());
  }, [recordId]);
  useEffect(() => {
    runtimeWarmupSessionIdsRef.current.clear();
  }, [recordId]);
  useEffect(() => {
    const previousFocus = previousFocusRef.current;
    previousFocusRef.current = collaborationFocusActive;
    if (!previousFocus || collaborationFocusActive) return;
    /* A desktop-wide exit may arrive from the shell, another Room, or a
       surviving window. Only presentation owned by this Room is stale then;
       the desktop focus owner remains the store. */
    setPanel('none');
    setSelectedParticipantId('');
  }, [collaborationFocusActive]);

  const clearOptimisticSteer = useCallback((clientActionId: string) => {
    if (optimisticSteerRef.current?.clientActionId !== clientActionId) return;
    optimisticSteerRef.current = null;
    setOptimisticSteer(null);
  }, []);
  const acknowledgeOptimisticSteer = useCallback((events: readonly unknown[]) => {
    const pending = optimisticSteerRef.current;
    if (!pending) return;
    const acknowledged = events.some((event) => roomEventClientActionId(event) === pending.clientActionId);
    if (acknowledged) clearOptimisticSteer(pending.clientActionId);
  }, [clearOptimisticSteer]);

  useEffect(() => {
    optimisticSteerRef.current = null;
    setOptimisticSteer(null);
  }, [recordId]);

  const projection = useRoomLiveStore((state) => state.projections[recordId]);
  const focusProjection = useMemo(
    () => record ? buildRoomFocusProjection(record, projection) : undefined,
    [projection, record],
  );
  const participantAliases = useMemo(() => Object.fromEntries(
    focusProjection?.partners.map((partner) => [partner.participantId, partner.celestialName]) ?? [],
  ), [focusProjection]);
  const prewarmParticipantSession = useCallback((sessionId: string) => {
    if (!sessionId || runtimeWarmupSessionIdsRef.current.has(sessionId)) return;
    runtimeWarmupSessionIdsRef.current.add(sessionId);
    void transport.request({
      pathId: 'agent.runtime.ensure',
      body: { sessionId },
    }).catch(() => {
      runtimeWarmupSessionIdsRef.current.delete(sessionId);
    });
  }, [transport]);
  const moderatorSessionId = record?.participants.find((participant) => (
    participant.id === record.moderatorParticipantId
    && participant.status === 'active'
  ))?.sessionId ?? '';
  useEffect(() => {
    if (!liveActive) return;
    prewarmParticipantSession(moderatorSessionId);
  }, [liveActive, moderatorSessionId, prewarmParticipantSession]);
  useEffect(() => {
    if (!liveActive || !record || !draft.trim()) return;
    const mentioned = roomMentionedParticipants(
      record.participants.filter((participant) => participant.status === 'active'),
      draft,
      participantAliases,
    );
    for (const participant of mentioned) {
      prewarmParticipantSession(participant.sessionId);
    }
  }, [draft, liveActive, participantAliases, prewarmParticipantSession, record]);
  const turnOrder = useRoomLiveStore(useShallow((state) => {
    const current = state.projections[recordId];
    return current ? selectPublicRoomTurnOrder(current) : [];
  }));
  const pendingQuestion = projection?.pendingUserQuestion;
  const pendingGroupedInput = latestPendingGroupedRoomInput(projection);
  const activeTurn = projection ? selectActivePublicRoomTurn(projection) : undefined;
  const latestTurn = projection
    ? projection.turnsById[selectPublicRoomTurnOrder(projection).at(-1) ?? '']
    : undefined;
  const collaborationParticipantSignature = useMemo(() => record?.participants
    .map((participant) => [
      participant.id,
      participant.status,
      participant.sessionId,
      participant.ordinal,
      participant.collaborationRole ?? '',
    ].join(':'))
    .sort()
    .join('\u0000') ?? '', [record?.participants]);
  const collaborationParticipantRequests = useMemo(
    () => record ? roomCollaborationPlanetRequests(record) : [],
    [collaborationParticipantSignature, record],
  );
  const collaborationParticipantIds = useRef(new Map<string, Set<string>>());
  const collaborationSyncKeyRef = useRef('');
  const activeWork = record?.workItems?.find((item) => ['queued', 'active', 'review', 'blocked'].includes(item.state));
  const taskBusyState = record?.roomKind === 'roleplay'
    ? undefined
    : activeWork?.state === 'blocked'
      ? 'blocked' as const
      : activeTurn || activeWork
        ? 'running' as const
        : undefined;
  /* Sending into a running Room steers the active partner. Queueing is the
   * other honest choice: the follow-up stays in the browser, ahead of the
   * Runtime send path, until this turn settles — so it can still be reordered,
   * edited, or pulled back into the composer on stop. */
  const queue = useConversationQueue({
    busy: Boolean(activeTurn) || sending,
    conversationId: recordId,
    send: (value) => { void send(value); },
  });
  const queueFollowUp = useCallback((value: string) => queue.enqueue(value), [queue]);

  const retrySnapshot = useRoomLiveSession({
    active: liveActive,
    roomId: recordId,
    transport,
    onLoadingChange: setLoading,
    onSnapshot: (_roomId, snapshot) => {
      acknowledgeOptimisticSteer(snapshot.events);
      const room = asRoom(snapshot.room);
      if (room) onRoomUpdated(room);
    },
    onMetadata: (_roomId, value) => {
      const room = roomFromResponse(value);
      if (room) onRoomUpdated(room);
    },
    onConnectionRestored: () => setError((current) => (
      current === ROOM_WORKSPACE_MISSING_TEXT ? current : ''
    )),
    onRecoveryState: (_roomId, state) => setRecoveryState(state),
    onConnectionError: (_roomId, reason, fallback) => setError(roomErrorText(reason, fallback)),
    onEvents: (_roomId, events) => {
      acknowledgeOptimisticSteer(events);
      pulsePawCompositionForRuntimeEvents('room', events.map((event) => event.eventType));
      for (const event of events) {
        const runtimeWindow = runtimeToolWindow(event);
        if (runtimeWindow && shouldAutoOpenRuntimeToolWindow(runtimeWindow)) {
          desktop?.openWindow(runtimeWindow);
        }
      }
    },
  });

  async function send(
    rawValue: string,
    options: { question?: PendingRoomQuestion; retryOfRootId?: string; preserveDraft?: boolean } = {},
  ): Promise<boolean> {
    if (!record || record.status !== 'active' || sending) return false;
    const authoritativeQuestion = roomProjection(recordId).pendingUserQuestion;
    const answersQuestion = Boolean(
      options.question
      && authoritativeQuestion
      && options.question.postId === authoritativeQuestion.postId
      && options.question.rootId === authoritativeQuestion.rootId
    );
    const message = rawValue.trim() || (attachments.length ? '请查看附件。' : '');
    if (!message) return false;
    const steering = Boolean(activeTurn && !answersQuestion);
    if (steering && attachments.length) {
      setError('当前回合执行中只能发送文字干预；图片会保留到下一轮。');
      return false;
    }
    const clientMessageId = `paw-room-${crypto.randomUUID()}`;
    /* The composer writes the visible planet name (@Mars); resolving it back
     * through the same alias map is what submits the stable Runtime ID. */
    const addressed = answersQuestion
      ? []
      : roomMentionedParticipants(
          record.participants.filter((item) => item.status === 'active'),
          message,
          participantAliases,
        );
    if (steering && addressed.length > 1) {
      if (!options.preserveDraft) setDraft(rawValue);
      setError('当前回合只能点名一位伙伴，请只保留一个 @伙伴。');
      return false;
    }
    const steerParticipantId = steering
      ? addressed[0]?.id
        ?? activeTurn?.participantIds[0]
        ?? record.participants.find((item) => item.status === 'active')?.id
        ?? ''
      : '';
    if (steering && !steerParticipantId) {
      if (!options.preserveDraft) setDraft(rawValue);
      setError('当前回合还没有可点名的伙伴，请稍后重试。');
      return false;
    }
    const selectedAttachments = answersQuestion ? [] : attachments;
    setSending(true);
    if (!options.preserveDraft) setDraft('');
    if (!answersQuestion) setAttachments([]);
    setError('');
    if (!steering) {
      useRoomLiveStore.getState().appendOptimistic(recordId, {
        clientMessageId,
        text: message,
        attachments: selectedAttachments,
        nowMs: Date.now(),
        ...(answersQuestion && authoritativeQuestion ? { answerToPostId: authoritativeQuestion.postId } : {}),
        ...(options.retryOfRootId ? { retryOfRootId: options.retryOfRootId } : {}),
      });
    } else {
      const receipt = {
        clientActionId: clientMessageId,
        message,
        participantId: steerParticipantId,
      } satisfies OptimisticSteerReceipt;
      optimisticSteerRef.current = receipt;
      setOptimisticSteer(receipt);
    }
    try {
      const response = await transport.request<Record<string, unknown>>(steering && activeTurn
        ? {
            pathId: 'agent.room.participant.steer',
            params: { roomId: recordId },
            body: {
              action: 'steer_participant',
              rootId: activeTurn.rootId ?? activeTurn.id,
              participantId: steerParticipantId,
              clientActionId: clientMessageId,
              message,
            },
          }
        : {
            pathId: 'agent.room.message',
            params: { roomId: recordId },
            body: {
              message,
              clientMessageId,
              attachmentIds: selectedAttachments.map((item) => item.mediaId),
              ...(options.retryOfRootId ? { retryOfRootId: options.retryOfRootId } : {}),
              ...(answersQuestion && authoritativeQuestion
                ? { answerToPostId: authoritativeQuestion.postId, answerToRootId: authoritativeQuestion.rootId }
                : {}),
              ...(addressed.length ? { participantIds: addressed.map((item) => item.id) } : {}),
              ...(record.roomKind !== 'roleplay' && activeWork?.id
                ? { workItemId: activeWork.id }
                : {}),
            },
          });
      useRoomLiveStore.getState().acceptMessage(recordId, response);
      const requestedStart = asRecord(asRecord(response).startConfirmation);
      if (requestedStart.status === 'pending' && typeof requestedStart.gateId === 'string') {
        setStartConfirmation({
          gateId: requestedStart.gateId,
          objective: typeof requestedStart.objective === 'string' ? requestedStart.objective : message,
          workItemId: typeof requestedStart.workItemId === 'string' ? requestedStart.workItemId : '',
          ...(!options.preserveDraft
            ? {
                restoreDraft: rawValue,
                restoreAttachments: [...selectedAttachments],
                optimisticClientMessageId: clientMessageId,
              }
            : {}),
        });
      }
      const timelineEvents = asRecord(response).timelineEvents;
      if (Array.isArray(timelineEvents)) acknowledgeOptimisticSteer(timelineEvents);
      const workItem = asWorkItem(asRecord(response).workItem);
      if (workItem) onRoomUpdated({
        ...record,
        workItems: [...(record.workItems ?? []).filter((item) => item.id !== workItem.id), workItem],
      });
      followRoomTimelineIfReaderAtEnd(timelineRef.current);
      return true;
    } catch (reason) {
      if (!steering) useRoomLiveStore.getState().discardOptimistic(recordId, clientMessageId);
      if (steering) clearOptimisticSteer(clientMessageId);
      if (!options.preserveDraft) setDraft(rawValue);
      if (!answersQuestion) setAttachments(selectedAttachments);
      setError(roomErrorText(reason, 'Room 消息没有发送，请重试。'));
      return false;
    } finally {
      setSending(false);
    }
  }

  async function abortTurn(rootId: string): Promise<void> {
    if (!rootId || abortingTurnIds.has(rootId)) return;
    /* Stopping must not silently discard held follow-ups: the queue only ever
     * held them, so they go back to the composer the user can still edit. */
    if (queue.queue.length) setDraft(queue.restoreToDraft(draft));
    setAbortingTurnIds((current) => new Set(current).add(rootId));
    try {
      const receipt = await transport.request<Record<string, unknown>>({
        pathId: 'agent.room.abort',
        params: { roomId: recordId },
        body: { roomTurnId: rootId, clientRequestId: `paw-room-abort-${crypto.randomUUID()}` },
      });
      if (receipt.ok === true && receipt.status !== 'cancellation_pending') {
        useRoomLiveStore.getState().abortTurn(recordId, rootId, Date.now());
      } else {
        setError('停止信号已送达，仍在等待所有伙伴返回终止回执。');
      }
    } catch (reason) { setError(publicErrorText(reason, '暂时无法停止这轮协作。')); }
    finally {
      setAbortingTurnIds((current) => { const next = new Set(current); next.delete(rootId); return next; });
    }
  }

  async function decideApproval(approvalId: string, decision: 'approved' | 'rejected', payloadSha256: string): Promise<void> {
    try {
      await transport.request({
        pathId: 'agent.approval.decide',
        params: { approvalId },
        body: { decision: decision === 'approved' ? 'approve' : 'reject', payloadSha256 },
      });
      setError('');
    } catch (reason) {
      setError(publicErrorText(reason, '审批没有完成，请重试。'));
      throw reason;
    }
  }

  async function confirmRoomStart(decision: 'confirm' | 'reject'): Promise<void> {
    if (!startConfirmation || sending) return;
    const pendingConfirmation = startConfirmation;
    setSending(true);
    try {
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.room.startGate.confirm',
        params: { roomId: recordId },
        body: { gateId: pendingConfirmation.gateId, decision },
      });
      if (decision === 'confirm') {
        useRoomLiveStore.getState().acceptMessage(recordId, response);
      } else {
        if (pendingConfirmation.optimisticClientMessageId) {
          useRoomLiveStore.getState().discardOptimistic(
            recordId,
            pendingConfirmation.optimisticClientMessageId,
          );
        }
        if (pendingConfirmation.restoreDraft !== undefined) {
          setDraft(pendingConfirmation.restoreDraft);
        }
        if (pendingConfirmation.restoreAttachments) {
          setAttachments([...pendingConfirmation.restoreAttachments]);
        }
      }
      setStartConfirmation(null);
    } catch (reason) {
      setError(publicErrorText(reason, '开始确认没有完成，请重试。'));
    } finally {
      setSending(false);
    }
  }

  async function pickAttachments(): Promise<void> {
    if (!transport.pickFiles) { setError('当前环境不能选择附件。'); return; }
    try {
      const imported = await transport.pickFiles({
        purpose: 'attachment',
        roomId: recordId,
        multiple: true,
        maxFiles: Math.max(1, 8 - attachments.length),
      });
      mergePickedAttachments(imported);
    } catch (reason) { setError(publicErrorText(reason, '附件没有导入，请重试。')); }
  }

  async function pasteFiles(files?: File[]): Promise<void> {
    if (!transport.pasteImages) { setError('当前环境不能导入剪贴板文件。'); return; }
    try {
      const imported = await transport.pasteImages({
        roomId: recordId,
        ...(files?.length ? { files } : {}),
        maxFiles: files?.length || Math.max(1, 8 - attachments.length),
      });
      mergePickedAttachments(imported);
    } catch (reason) { setError(publicErrorText(reason, '附件没有导入，请重试。')); }
  }

  function mergePickedAttachments(files: PickedFile[]): void {
    const receipts = files.map((file) => roomAttachment(file, recordId));
    setAttachments((current) => {
      const byId = new Map(current.map((item) => [item.mediaId, item]));
      receipts.forEach((item) => byId.set(item.mediaId, item));
      return [...byId.values()].slice(0, 8);
    });
  }

  async function manageWorkspaceRoots(): Promise<void> {
    if (!record || !transport.pickFiles) {
      setError('当前环境不能选择工作区。');
      return;
    }
    try {
      const picked = await transport.pickFiles({
        purpose: 'workspace-root',
        selection: 'directory',
        multiple: true,
        maxFiles: 4,
      });
      const workspaceRoots = picked
        .map((item) => item.path)
        .filter((path): path is string => Boolean(path));
      if (!workspaceRoots.length) return;
      const permissionPolicy = parseRoomPermissionPolicy(record.permissionPolicy, record.roomKind);
      const workspaceConfirmationRequired = permissionPolicy
        ? roomPermissionPolicyNeedsWorkspaceConfirmation(permissionPolicy)
        : record.executionMode === 'workspace_managed';
      const dangerousConfirmationRequired = permissionPolicy
        ? roomPermissionPolicyNeedsDangerousConfirmation(permissionPolicy)
        : record.executionMode === 'full_trust';
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.room.archive',
        params: { roomId: recordId },
        body: {
          workspaceRoots,
          ...(permissionPolicy ? { permissionPolicy } : {}),
          ...(workspaceConfirmationRequired
            ? { workspaceScopeConfirmation: 'APPROVE_WORKSPACE_SCOPE' }
            : {}),
          ...(dangerousConfirmationRequired
            ? { dangerousModeConfirmation: 'ENABLE_FULL_TRUST' }
            : {}),
        },
      });
      const updated = roomFromResponse(response);
      if (updated) onRoomUpdated(updated);
      setError('');
      retrySnapshot();
    } catch (reason) {
      setError(roomErrorText(reason, 'Room 工作目录没有更新。'));
    }
  }

  const title = record?.title || '未命名 Room';
  const activeParticipants = record?.participants.filter((participant) => participant.status === 'active') ?? [];
  const activeTopic = record?.topics?.find((topic) => topic.id === record.activeTopicId)
    ?? record?.topics?.find((topic) => topic.status === 'active');
  const activeRootId = activeTurn?.rootId ?? activeTurn?.id ?? '';
  /* The Room moderator is the backend's Root actor. Require that canonical
   * participant to be active before exposing a recovery command; never fall
   * back to the first participant or a lane that merely happens to be visible. */
  const activeRootActorId = activeTurn && record?.moderatorParticipantId
    && record.participants.some((participant) => (
      participant.id === record.moderatorParticipantId && participant.status === 'active'
    ))
    ? record.moderatorParticipantId
    : '';
  const abortingActiveTurn = Boolean(activeRootId && abortingTurnIds.has(activeRootId));
  const openParticipantObserver = useCallback((participant: RoomSummary['participants'][number], background = false) => desktop?.openWindow(
    roomPlanetObserverWindowRequest(participant, recordId, background),
  ), [desktop, recordId]);
  const openParticipantById = useCallback((participantId: string, background = false) => {
    const participant = record?.participants.find((candidate) => candidate.id === participantId);
    if (!participant) return;
    openParticipantObserver(participant, background);
  }, [openParticipantObserver, record?.participants]);
  const selectAndOpenParticipant = useCallback((participantId: string) => {
    setSelectedParticipantId(participantId);
    if (participantProcessLocation === 'room-transcript') {
      setView('conversation');
      setPanel('none');
      setEmbeddedFocusActive(false);
      desktop?.setCollaborationFocusGroup?.(null);
      return;
    }
    if (collaborationFocusActive) {
      openParticipantById(participantId);
      return;
    }
    const participant = record?.participants.find((candidate) => candidate.id === participantId);
    if (!participant) return;
    desktop?.openWindow(roomPartnerSessionWindowRequest(participant));
  }, [collaborationFocusActive, desktop, openParticipantById, participantProcessLocation, record?.participants]);
  const openProcessActivity = useCallback((activity: RoomActivityProjection) => {
    const request = roomProcessWindowRequest(activity, recordId);
    if (request) desktop?.openWindow({ ...request, background: false });
  }, [desktop, recordId]);
  const resumeBlockedWorkItem = useCallback(async (row: RoomRoundTaskRow): Promise<void> => {
    if (!record || !row.blockedWorkItemId) return;
    if (!activeRootActorId) {
      setResumeErrorByRow((current) => ({ ...current, [row.key]: '当前没有可用的 active Root，无法恢复。' }));
      return;
    }
    const workItemId = row.blockedWorkItemId;
    setResumingWorkItemId(workItemId);
    setResumeErrorByRow((current) => {
      if (!(row.key in current)) return current;
      const next = { ...current };
      delete next[row.key];
      return next;
    });
    try {
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.room.workItem.resume',
        params: { roomId: record.id, workItemId },
        body: {
          actorParticipantId: activeRootActorId,
          clientActionId: `paw-room-work-resume-${crypto.randomUUID()}`,
          phase: 'recovery',
          timeoutSeconds: 300,
        },
      });
      const workItem = asWorkItem(asRecord(response).workItem);
      if (!workItem) throw new Error('恢复回执缺少 WorkItem。');
      /* The response is an authoritative dispatch receipt. Reflect only its
       * WorkItem; the subsequent live snapshot supplies any later settlement. */
      onRoomUpdated({
        ...record,
        workItems: [...(record.workItems ?? []).filter((item) => item.id !== workItem.id), workItem],
      });
      retrySnapshot();
    } catch (reason) {
      setResumeErrorByRow((current) => ({
        ...current,
        [row.key]: publicErrorText(reason, '恢复没有完成，请重试。'),
      }));
    } finally {
      setResumingWorkItemId('');
    }
  }, [activeRootActorId, onRoomUpdated, record, retrySnapshot, transport]);
  /* PF-CM-013：协作态势可以弹出成一扇独立观察窗，主 Room 留给公开对话。 */
  const openFocusWindow = useCallback(() => {
    if (!record) return;
    desktop?.openWindow({
      appId: 'agent',
      target: {
        kind: 'room',
        id: recordId,
        title: `${record.title} · 协作态势`,
        subtitle: 'Sol 协作全景 · 目标、伙伴与交接实时同步',
        panel: 'focus',
      },
    });
  }, [desktop, record, recordId]);
  const enterCollaborationMode = useCallback(() => {
    setView('rounds');
    setPanel('focus');
    if (!hasDesktopFocusSource) setEmbeddedFocusActive(true);
    if (!desktop || !record) return;
    /* Collaboration focus is an explicit Room view choice. Opening a
       participant Session is still an ordinary desktop action and must not
       enter this mode as a side effect. */
    desktop.setCollaborationFocusGroup?.(roomFocusGroup);
    setCollaborationOpenFailures(new Set());
  }, [desktop, hasDesktopFocusSource, record, roomFocusGroup]);
  const exitCollaborationFocus = useCallback(() => {
    setEmbeddedFocusActive(false);
    setPanel('none');
    setSelectedParticipantId('');
    desktop?.setCollaborationFocusGroup?.(null);
  }, [desktop]);
  const closeCollaborationPanel = useCallback(() => {
    setPanel('none');
    collaborationTriggerRef.current?.focus();
  }, []);
  const retryCollaborationPlanet = useCallback((participantId: string) => {
    const participant = record?.participants.find((candidate) => candidate.id === participantId);
    if (!desktop || !participant) return;
    try {
      desktop.openWindow(roomPlanetObserverWindowRequest(participant, recordId, true));
      setCollaborationOpenFailures((current) => {
        if (!current.has(participantId)) return current;
        const next = new Set(current);
        next.delete(participantId);
        return next;
      });
    } catch {
      setCollaborationOpenFailures((current) => current.has(participantId)
        ? current
        : new Set(current).add(participantId));
    }
  }, [desktop, record?.participants, recordId]);
  /* Keep the collaboration perimeter in lockstep with the Room roster. The
   * effect runs only after the explicit focus choice, so ordinary Room work
   * never opens a window for every participant. Existing window ids are stable
   * (`agent:<participantId>`), which lets a removed member disappear without
   * inventing a second desktop store or changing Session semantics. */
  useEffect(() => {
    if (!collaborationFocusActive || !desktop || !record) {
      if (!collaborationFocusActive) collaborationSyncKeyRef.current = '';
      return;
    }
    /* Room snapshots are intentionally frequent. Reconcile the desktop only
       when the roster meaning changes; otherwise every progress event would
       reopen/focus all planet windows and make the canvas feel random. */
    const syncKey = `${record.id}:${collaborationParticipantSignature}`;
    if (syncKey === collaborationSyncKeyRef.current) return;
    collaborationSyncKeyRef.current = syncKey;
    const desired = new Set(collaborationParticipantRequests.map((request) => request.target.id));
    const previous = collaborationParticipantIds.current.get(record.id) ?? new Set<string>();
    for (const participantId of previous) {
      if (!desired.has(participantId)) desktop.closeWindow?.(`agent:${participantId}`);
    }
    const failures = new Set<string>();
    for (const request of collaborationParticipantRequests) {
      try {
        desktop.openWindow(request);
      } catch {
        failures.add(request.target.id);
      }
    }
    collaborationParticipantIds.current.set(record.id, desired);
    setCollaborationOpenFailures(failures);
  }, [
    collaborationParticipantRequests,
    collaborationParticipantSignature,
    collaborationFocusActive,
    desktop,
    record,
  ]);
  useEffect(() => {
    setCollaborationOpenFailures((current) => {
      if (!current.size) return current;
      const next = new Set([...current].filter((participantId) => record?.participants.some((participant) => (
        participant.id === participantId && participant.status === 'active'
      ))));
      return next.size === current.size ? current : next;
    });
  }, [record?.participants]);
  useEffect(() => {
    if (!selectedParticipantId) return;
    if (!record?.participants.some((participant) => (
      participant.id === selectedParticipantId && participant.status === 'active'
    ))) setSelectedParticipantId('');
  }, [record?.participants, selectedParticipantId]);
  useEffect(() => {
    if (!desktop || !record) return;
    desktop.bindRoomMain?.({ kind: 'room', id: record.id, title: record.title, subtitle: record.description });
  }, [desktop, record]);
  /* status overlay 克制：为 0 的计数是噪音，状态行只亮出真实存在的工作。 */
  const submittedPartnerCount = focusProjection?.partners.filter((partner) => partner.state === 'completed').length ?? 0;
  const signalChips = ([
    ['active', focusProjection?.counts.active ?? 0, '进行'],
    ['review', focusProjection?.counts.review ?? 0, '复核'],
    ['blocked', focusProjection?.counts.blocked ?? 0, '受阻'],
    ['submitted', submittedPartnerCount, '伙伴已提交结果'],
    ['complete', focusProjection?.counts.completed ?? 0, '任务完成'],
  ] as const).filter(([, count]) => count > 0);
  /* 没有主持就没有 Sol：signal chrome 只有在真的有伙伴担任 coordinator 时
     才用 Sol 命名这个 Room 的原点，否则统一叫「主 Room」。 */
  const coordinatorActive = focusProjection ? roomFocusHasCoordinator(focusProjection.partners) : false;
  const originLabel = roomFocusOriginLabel(coordinatorActive);
  const syncOffline = Boolean(error) && error !== ROOM_WORKSPACE_MISSING_TEXT;
  const visibleRecoveryState = syncOffline ? 'failed' : recoveryState;
  const runtimeBusy = visibleRecoveryState !== 'failed' && Boolean(activeTurn);
  const awaitingRoot = visibleRecoveryState !== 'failed'
    && latestTurn?.status === 'running'
    && !activeTurn
    && submittedPartnerCount > 0;
  const runtimeStatusLabel = abortingActiveTurn
    ? '正在停止'
    : syncOffline || recoveryState === 'failed'
      ? '同步离线 · 历史已保留'
      : sending && runtimeBusy
        ? '正在干预'
        : runtimeBusy
          ? '协作中'
          : awaitingRoot
            ? '伙伴已提交，等待 Root'
            : latestTurn?.status === 'completed'
              ? 'Room 已完成'
              : recoveryState === 'synced'
                ? '已同步'
                : '连接中';
  const roomChromeControls = <div aria-label="Room 窗口控制" className="paw-room-window-chrome" data-coordinator={coordinatorActive || undefined} data-status={abortingActiveTurn ? 'stopping' : runtimeBusy ? 'busy' : visibleRecoveryState}>
    {coordinatorActive ? <span aria-label="Agent 中的 Sol 协作模式" className="paw-room-workspace__mode">Sol</span> : null}
    <nav aria-label="Room 工作台视图">
      <button aria-label="任务" aria-pressed={!collaborationFocusActive && panel === 'none' && view === 'rounds'} data-room-view="rounds" onClick={() => { setView('rounds'); exitCollaborationFocus(); }} type="button"><ListChecks size={14} /><span>任务</span></button>
      <button aria-label="协同模式" aria-pressed={collaborationFocusActive} data-room-view="collaboration" onClick={enterCollaborationMode} ref={collaborationTriggerRef} type="button"><Focus size={14} /><span>协同模式</span></button>
      <button aria-label="公开记录" aria-pressed={!collaborationFocusActive && panel === 'none' && view === 'conversation'} data-room-view="conversation" onClick={() => { setView('conversation'); exitCollaborationFocus(); }} type="button"><MessageCircle size={14} /><span>公开记录</span></button>
      <button aria-label="星空" aria-pressed={view === 'starfield'} data-room-view="starfield" onClick={() => { setView('starfield'); exitCollaborationFocus(); }} type="button"><Orbit size={14} /><span>星空</span></button>
    </nav>
    <div className="paw-room-workspace__runtime"><span><i />{runtimeStatusLabel}</span>{runtimeBusy ? <button aria-label="停止整轮协作" disabled={abortingActiveTurn} onClick={() => void abortTurn(activeRootId)} type="button"><StopCircle size={16} /></button> : null}</div>
  </div>;
  return (
    <section
      className="paw-room-workspace paw-room-workspace--migrated-v1"
      data-agent-mode="room"
      data-collaboration-mode={collaborationFocusActive}
      data-panel={panel}
      data-view={view}
      data-window-chrome={windowChromeTarget ? 'portal' : 'fallback'}
      data-room-id={recordId}
      data-status={abortingActiveTurn ? 'stopping' : runtimeBusy ? 'busy' : visibleRecoveryState}
    >
      {windowChromeTarget ? <PawWindowChromePortal>{roomChromeControls}</PawWindowChromePortal> : <header className="paw-room-workspace__header">{roomChromeControls}</header>}

      <section aria-label="Room 当前协作" className="paw-room-workspace__signal">
        <div className="paw-room-workspace__objective">
          <div><small>目标</small><strong>{focusProjection?.goal.title || activeTopic?.title || activeWork?.objective || record?.description || '当前协作'}</strong></div>
          <span>{activeParticipants.length} 颗行星 · {focusProjection?.workItems.length ?? 0} 项任务{record?.ownerAppId === 'extension:agent-lab' ? ' · Agent Lab 只读沙盒' : ''}</span>
        </div>
        {focusProjection ? <div aria-label={`${originLabel} 当前状态`} className="paw-room-workspace__signal-status">
          {signalChips.length
            ? signalChips.map(([tone, count, label]) => <span data-tone={tone} key={tone}><i />{count} {label}</span>)
            : <span data-tone="idle"><i />待命</span>}
        </div> : null}
      </section>

      <div className="paw-room-workspace__body">
        <section aria-label={`${title} 主 Room`} className="paw-room-workspace__main" role="region">
          {view === 'starfield' && focusProjection ? (
            <LazyPawRoomStarfield
              active={active}
              focus={focusProjection}
              roomId={recordId}
              onExit={() => setView('conversation')}
              onOpenParticipant={openParticipantById}
            />
          ) : view === 'rounds' ? (
            <div className="paw-room-timeline" ref={timelineRef}>
              {projection && record ? (
                <PawRoomRoundSheet
                  onOpenParticipant={selectAndOpenParticipant}
                  onResumeBlocked={resumeBlockedWorkItem}
                  projection={projection}
                  resumeErrorByRow={resumeErrorByRow}
                  resumingWorkItemId={resumingWorkItemId}
                  room={record}
                  selectedParticipantId={selectedParticipantId}
                />
              ) : (
                <div className="paw-room-workspace__loading"><LoaderCircle className="ui-spin" size={18} />正在恢复 Room 协作现场</div>
              )}
            </div>
          ) : <div className="paw-room-timeline" ref={timelineRef}>
              {projection && record ? <PawRoomConversation
                empty={loading
                  ? <div className="paw-room-workspace__loading"><LoaderCircle className="ui-spin" size={18} />正在恢复 Room 协作现场</div>
                  : <div className="paw-room-workspace__empty"><Users size={24} /><strong>Room 已准备好</strong><p>发送目标，伙伴会分工、执行并汇合结果。</p></div>}
                {...(optimisticSteer ? {
                  lead: (
                    <article
                      className="ccui-turn ccui-user-turn paw-room-workspace__optimistic-steer"
                      data-client-action-id={optimisticSteer.clientActionId}
                      data-delivery="sending"
                    >
                      <div className="ccui-user-bubble">
                        <div className="ccui-user-text">{optimisticSteer.message}</div>
                      </div>
                      <div className="ccui-user-footer">
                        <div aria-label="等待 Room 回执" aria-live="polite" className="ccui-steer-receipt" role="status">
                          <span>尚未送达伙伴 · {roomPlanetName(record.participants.find((participant) => participant.id === optimisticSteer.participantId)?.ordinal ?? 0)}</span>
                        </div>
                      </div>
                    </article>
                  ),
                } : {})}
                onApprovalDecision={decideApproval}
                onOpenProcessActivity={openProcessActivity}
                onRetryTurn={(message, retryOfRootId) => void send(message, { retryOfRootId, preserveDraft: true })}
                projection={projection}
                retryingTurn={sending}
                room={record}
              /> : null}
          </div>}

          <div className="paw-room-workspace__composer">
              {startConfirmation ? <div className="paw-room-workspace__start-confirmation" aria-label="Room 开始执行确认" role="alert">
                <div><strong>先确认开始执行</strong><span>{startConfirmation.objective}</span><small>确认后将在授权工作区内连续执行已披露工具；停止、边界和审计仍然有效。</small></div>
                <div><button disabled={sending} onClick={() => void confirmRoomStart('reject')} type="button">暂不开始</button><button disabled={sending} onClick={() => void confirmRoomStart('confirm')} type="button">确认并开始</button></div>
              </div> : null}
              {collaborationOpenFailures.size ? <div className="paw-room-workspace__planet-open-error" role="alert">
                <CircleAlert size={14} />
                <div>
                  <span>{collaborationOpenFailures.size} 颗活跃行星未能打开</span>
                  <div aria-label="未打开的行星">
                    {[...collaborationOpenFailures].map((participantId) => <button
                      aria-label={`重试打开 ${participantAliases[participantId] ?? participantId}`}
                      key={participantId}
                      onClick={() => retryCollaborationPlanet(participantId)}
                      type="button"
                    >{participantAliases[participantId] ?? participantId} · 重试</button>)}
                  </div>
                  <TraceAgentHandoffButton handoff={{
                    kind: 'room',
                    entityId: `room-planets:${recordId}`,
                    title: 'Room 行星窗口打开失败',
                    summary: `${collaborationOpenFailures.size} 颗活跃行星未能打开。`,
                    roomId: recordId,
                    sourceRoute: `/rooms?room=${encodeURIComponent(recordId)}`,
                    refs: {
                      participantIds: [...collaborationOpenFailures].join(','),
                      participantCount: collaborationOpenFailures.size,
                    },
                  }} />
                </div>
              </div> : null}
              {error ? (
                <div className="paw-room-workspace__error" role="alert">
                  <CircleAlert size={14} />
                  <span>{error}</span>
                  {error === ROOM_WORKSPACE_MISSING_TEXT ? (
                    <button onClick={() => void manageWorkspaceRoots()} type="button">选择工作目录</button>
                  ) : (
                    <button onClick={() => { setError(''); retrySnapshot(); }} type="button">重新同步</button>
                  )}
                  <TraceAgentHandoffButton
                    handoff={{
                      kind: 'room',
                      entityId: recordId,
                      title: 'Room 同步失败',
                      summary: error,
                      error,
                      roomId: recordId,
                      sourceRoute: `/rooms?room=${encodeURIComponent(recordId)}`,
                    }}
                  />
                </div>
              ) : null}
              {pendingGroupedInput ? <GenericUserInputCard activity={pendingGroupedInput} sessionId={pendingGroupedInput.sourceSessionId} onError={setError} /> : (
                <>
                  <QueueTray busy={sending} controller={queue} />
                  <RoomComposer
                    room={record}
                    participantAliases={participantAliases}
                    personas={personas}
                    draft={draft}
                    attachments={attachments}
                    sending={sending}
                    taskBusyState={taskBusyState}
                    pendingUserAnswer={pendingQuestion?.roomId === recordId}
                    queueDepth={queue.queue.length}
                    onDraftChange={setDraft}
                    onQueue={queueFollowUp}
                    onSend={(value) => send(value, { question: pendingQuestion?.roomId === recordId ? pendingQuestion : undefined })}
                    onAttachmentsChange={setAttachments}
                    onPasteImages={(files) => void pasteFiles(files)}
                    onPasteFromClipboard={() => void pasteFiles()}
                    onPickAttachments={() => void pickAttachments()}
                  />
                </>
              )}
          </div>
        </section>
        {panel !== 'none' && record ? <PawRoomToolWorkspace
          onClosePanel={closeCollaborationPanel}
          onError={setError}
          onOpenParticipant={openParticipantById}
          onPanelChange={setPanel}
          {...(desktop ? { onPopout: openFocusWindow } : {})}
          onRefresh={async () => { retrySnapshot(); }}
          onRoomUpdated={onRoomUpdated}
          panel={panel}
          personas={personas}
          focusProjection={focusProjection}
          room={record}
          onSelectParticipant={setSelectedParticipantId}
          selectedParticipantId={selectedParticipantId}
        /> : null}
      </div>
    </section>
  );

}

function PawRoomToolWorkspace({
  onClosePanel,
  onError,
  onOpenParticipant,
  onSelectParticipant,
  onPanelChange,
  onPopout,
  onRefresh,
  onRoomUpdated,
  panel,
  personas,
  focusProjection,
  room,
  selectedParticipantId,
}: {
  onClosePanel: () => void;
  onError: (message: string) => void;
  onOpenParticipant: (participantId: string, background?: boolean) => void;
  onSelectParticipant: (participantId: string) => void;
  onPanelChange: (panel: RoomToolPanel) => void;
  onPopout?: () => void;
  onRefresh: () => Promise<void>;
  onRoomUpdated: (room: RoomSummary) => void;
  panel: RoomToolPanel;
  personas: AgentPersonaV1[];
  focusProjection?: RoomFocusProjection;
  room: RoomSummary;
  selectedParticipantId: string;
}) {
  const tabId = useId();
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const moveTabFocus = useCallback((event: KeyboardEvent<HTMLButtonElement>, current: RoomToolPanel) => {
    const currentIndex = roomToolPanelItems.indexOf(current);
    if (currentIndex < 0) return;
    let nextIndex: number;
    if (event.key === 'ArrowRight') nextIndex = (currentIndex + 1) % roomToolPanelItems.length;
    else if (event.key === 'ArrowLeft') nextIndex = (currentIndex - 1 + roomToolPanelItems.length) % roomToolPanelItems.length;
    else if (event.key === 'Home') nextIndex = 0;
    else if (event.key === 'End') nextIndex = roomToolPanelItems.length - 1;
    else return;
    event.preventDefault();
    onPanelChange(roomToolPanelItems[nextIndex]);
    tabRefs.current[nextIndex]?.focus();
  }, [onPanelChange]);
  const handleAsideKeyDown = useCallback((event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== 'Escape') return;
    event.stopPropagation();
    onClosePanel();
  }, [onClosePanel]);
  /* 空间指向：协作态势键在标题栏尾端，面板也必须从尾端展开。data-side 把这个
     朝向写成契约而不是 DOM 顺序的副作用，CSS 用同名网格区落位。 */
  return <aside aria-label="Room 协作态势" className="paw-room-tools" data-side="trailing" onKeyDown={handleAsideKeyDown}>
    <header className="paw-room-tools__header">
      <span><Focus aria-hidden="true" size={15} /><strong>协作态势</strong></span>
      <div className="paw-room-tools__actions">
        {onPopout ? <button aria-label="在协作窗口中打开协作态势" onClick={onPopout} type="button"><ExternalLink aria-hidden="true" size={14} /></button> : null}
        <button aria-label="关闭协作态势" onClick={onClosePanel} type="button"><X aria-hidden="true" size={15} /></button>
      </div>
    </header>
    <nav aria-label="协作工具视图" aria-orientation="horizontal" className="paw-room-tools__tabs" role="tablist">
      {roomToolPanelItems.map((item, index) => {
        const Icon = roomToolPanelIcons[item];
        return <button
          aria-controls={`${tabId}-panel`}
          aria-selected={item === panel}
          id={`${tabId}-${item}`}
          key={item}
          onClick={() => onPanelChange(item)}
          onKeyDown={(event) => moveTabFocus(event, item)}
          role="tab"
          ref={(node) => { tabRefs.current[index] = node; }}
          tabIndex={item === panel ? 0 : -1}
          type="button"
        ><Icon aria-hidden="true" size={14} /><span>{roomToolPanelLabels[item]}</span></button>;
      })}
    </nav>
    <div aria-labelledby={`${tabId}-${panel}`} className="paw-room-tools__content" id={`${tabId}-panel`} role="tabpanel">
      {panel === 'focus' && focusProjection ? <PawRoomFocusOverview
        focus={focusProjection}
        hideMission
        onOpenParticipant={onOpenParticipant}
        onSelectParticipant={onSelectParticipant}
        selectedParticipantId={selectedParticipantId}
      /> : null}
      {panel === 'governance' ? <PawRoomGovernance personas={personas} room={room} onError={onError} onRefresh={onRefresh} onRoomUpdated={onRoomUpdated} /> : null}
    </div>
  </aside>;
}

export function PawRoomGovernance({
  personas,
  room,
  onError,
  onRefresh,
  onRoomUpdated,
}: {
  personas: AgentPersonaV1[];
  room?: RoomSummary;
  onError: (message: string) => void;
  onRefresh: () => Promise<void>;
  onRoomUpdated: (room: RoomSummary) => void;
}) {
  if (!room) return <div className="paw-room-governance paw-room-governance--empty">Room 元数据尚未恢复。</div>;
  return (
    <PawRoomGovernanceInner
      key={room.id}
      onError={onError}
      onRefresh={onRefresh}
      onRoomUpdated={onRoomUpdated}
      personas={personas}
      room={room}
    />
  );
}


function PawRoomGovernanceInner({
  personas,
  room,
  onError,
  onRefresh,
  onRoomUpdated,
}: {
  personas: AgentPersonaV1[];
  room: RoomSummary;
  onError: (message: string) => void;
  onRefresh: () => Promise<void>;
  onRoomUpdated: (room: RoomSummary) => void;
}) {
  const transport = useControlTransport();
  const [busyKey, setBusyKey] = useState('');
  const [topicTitle, setTopicTitle] = useState('');
  const [topicSummary, setTopicSummary] = useState('');
  const [workObjective, setWorkObjective] = useState('');
  const [workOutput, setWorkOutput] = useState('');
  const [workOwner, setWorkOwner] = useState('');
  const [title, setTitle] = useState(room.title);
  const [description, setDescription] = useState(room.description ?? '');
  const storedPermissionPolicy = useMemo(
    () => parseRoomPermissionPolicy(room.permissionPolicy, room.roomKind),
    [room.permissionPolicy, room.roomKind],
  );
  const [permissionPolicy, setPermissionPolicy] = useState<RoomPermissionPolicy | undefined>(
    storedPermissionPolicy,
  );
  const activeParticipants = room.participants.filter((item) => item.status === 'active');
  const availablePersonas = personas.filter((persona) => !activeParticipants.some((item) => item.roleId === persona.roleId && item.roleVersion === persona.version));
  const participantLimitReached = activeParticipants.length >= ROOM_PARTICIPANT_LIMIT;
  const nextPlanetName = roomPlanetName(Math.max(-1, ...room.participants.map((participant) => participant.ordinal)) + 1);
  const permissionPolicyChanged = !roomPermissionPoliciesEqual(
    permissionPolicy,
    storedPermissionPolicy,
  );
  const permissionDisplayLabel = permissionPolicy
    ? roomPermissionLayerPresentation(
        permissionPolicy,
        'room',
        room.roomKind ?? 'collaboration',
      ).effectiveLabel
    : '分层权限不可用';

  async function mutate(key: string, request: ControlRequest): Promise<void> {
    setBusyKey(key);
    onError('');
    try {
      const response = await transport.request<Record<string, unknown>>(request);
      const updated = roomFromResponse(response);
      if (updated) onRoomUpdated(updated);
      else await onRefresh();
    } catch (reason) { onError(publicErrorText(reason, 'Room 设置没有更新。')); }
    finally { setBusyKey(''); }
  }

  async function createTopic(): Promise<void> {
    if (!topicTitle.trim()) return;
    await mutate('topic:create', { pathId: 'agent.room.topic.create', params: { roomId: room.id }, body: { title: topicTitle.trim(), summary: topicSummary.trim() } });
    setTopicTitle(''); setTopicSummary('');
  }

  async function createWorkItem(): Promise<void> {
    const ownerId = workOwner || activeParticipants[0]?.id || '';
    if (!workObjective.trim() || !workOutput.trim() || !ownerId) return;
    await mutate('work:create', {
      pathId: 'agent.room.workItem.create',
      params: { roomId: room.id },
      body: {
        objective: workObjective.trim(),
        expectedOutput: workOutput.trim(),
        currentOwnerParticipantId: ownerId,
        accountableParticipantId: room.moderatorParticipantId || ownerId,
        createdByParticipantId: room.moderatorParticipantId || ownerId,
        clientMessageId: `paw-work-${crypto.randomUUID()}`,
        topicId: room.activeTopicId ?? '',
        acceptanceCriteria: [],
        state: 'queued',
        depth: 0,
      },
    });
    setWorkObjective(''); setWorkOutput('');
  }

  return <div className="paw-room-governance">
    <header><span><strong>Room 治理</strong><small>伙伴、话题、工作项与边界</small></span><button onClick={() => void onRefresh()} type="button">刷新</button></header>
    <section>
      <header><span><Users size={15} /><strong>伙伴与分工</strong></span><small>{activeParticipants.length}/{ROOM_PARTICIPANT_LIMIT}</small></header>
      <div className="paw-room-governance__members">{activeParticipants.map((participant) => <article key={participant.id}>
        <span aria-hidden="true" className="paw-room-governance__member-mark"><Users size={14} /></span>
        <span><strong>{roomPlanetName(participant.ordinal)}</strong><small>{roomCollaborationRoleLabel(participant.collaborationRole)}</small></span>
        {room.roomKind !== 'roleplay' ? <Select aria-label={`${roomPlanetName(participant.ordinal)} 的分工`} disabled={Boolean(busyKey)} onValueChange={(collaborationRole) => void mutate(`role:${participant.id}`, { pathId: 'agent.room.participant.update', params: { roomId: room.id }, body: { participantId: participant.id, collaborationRole } })} options={roomCollaborationRoleOptions(participant.collaborationRole)} value={participant.collaborationRole ?? 'implementer'} /> : null}
        <button aria-label={`移出 ${roomPlanetName(participant.ordinal)}`} disabled={Boolean(busyKey) || activeParticipants.length <= 2 || participant.id === room.moderatorParticipantId} onClick={() => void mutate(`remove:${participant.id}`, { pathId: 'agent.room.participant.remove', params: { roomId: room.id }, body: { participantId: participant.id } })} type="button">{busyKey === `remove:${participant.id}` ? <LoaderCircle className="ui-spin" size={14} /> : <UserMinus size={14} />}</button>
      </article>)}</div>
      {availablePersonas.length ? <div className="paw-room-governance__invite"><span aria-hidden="true"><UserPlus size={14} />邀请伙伴</span><Select aria-label="邀请伙伴" disabled={Boolean(busyKey) || participantLimitReached} onValueChange={(key) => { if (participantLimitReached) return; const persona = personas.find((item) => `${item.roleId}:${item.version}` === key); if (persona) void mutate(`add:${persona.roleId}`, { pathId: 'agent.room.participant.add', params: { roomId: room.id }, body: { roleId: persona.roleId, roleVersion: persona.version, collaborationRole: 'implementer' } }); }} options={participantLimitReached ? [{ value: '', label: `已达 ${ROOM_PARTICIPANT_LIMIT} 人上限` }] : availablePersonas.map((persona) => ({ value: `${persona.roleId}:${persona.version}`, label: `${nextPlanetName} · ${persona.tagline || '协作伙伴'}` }))} placeholder={participantLimitReached ? `已达 ${ROOM_PARTICIPANT_LIMIT} 人上限` : `选择 ${nextPlanetName} 的分工…`} value="" /></div> : null}
    </section>

    <section>
      <header><span><MessageCircle size={15} /><strong>话题</strong></span><small>{room.topics?.length ?? 0}</small></header>
      <div className="paw-room-governance__topics">{(room.topics ?? []).map((topic) => <article data-active={topic.id === room.activeTopicId || undefined} key={topic.id}><span><strong>{topic.title}</strong><small>{topic.summary || '暂无摘要'}</small></span>{topic.status === 'active' && topic.id !== room.activeTopicId ? <button onClick={() => void mutate(`topic:${topic.id}`, { pathId: 'agent.room.topic.update', params: { roomId: room.id }, body: { topicId: topic.id, activate: true } })} type="button">切换</button> : null}{topic.status === 'active' && topic.id !== room.activeTopicId ? <button aria-label={`归档 ${topic.title}`} onClick={() => void mutate(`archive-topic:${topic.id}`, { pathId: 'agent.room.topic.update', params: { roomId: room.id }, body: { topicId: topic.id, archived: true } })} type="button"><Archive size={13} /></button> : null}</article>)}</div>
      <div className="paw-room-governance__form"><input aria-label="新话题名称" maxLength={120} onChange={(event) => setTopicTitle(event.target.value)} placeholder="新话题" value={topicTitle} /><input aria-label="新话题摘要" maxLength={2000} onChange={(event) => setTopicSummary(event.target.value)} placeholder="摘要（可选）" value={topicSummary} /><button disabled={!topicTitle.trim() || Boolean(busyKey)} onClick={() => void createTopic()} type="button"><Plus size={14} />创建</button></div>
    </section>

    <section>
      <header><span><GitBranch size={15} /><strong>工作项</strong></span><small>{room.workItems?.length ?? 0}</small></header>
      <div className="paw-room-governance__work">{(room.workItems ?? []).map((work) => <article data-state={work.state} key={work.id}><span><strong>{work.objective}</strong><small>{roomWorkStateLabel(work.state)} · {participantName(room, work.currentOwnerParticipantId)}</small></span><Select aria-label={`重新分配 ${work.objective}`} disabled={Boolean(busyKey) || ['done', 'failed', 'cancelled'].includes(work.state)} onValueChange={(targetParticipantId) => void mutate(`work:${work.id}`, { pathId: 'agent.room.workItem.reassign', params: { roomId: room.id, workItemId: work.id }, body: { actorParticipantId: room.moderatorParticipantId || activeParticipants[0]?.id, targetParticipantId, reason: '用户在 Room 治理面板重新分配' } })} options={activeParticipants.map((participant) => ({ value: participant.id, label: roomPlanetName(participant.ordinal) }))} value={work.currentOwnerParticipantId} /></article>)}</div>
      <div className="paw-room-governance__form"><input aria-label="工作项目标" maxLength={500} onChange={(event) => setWorkObjective(event.target.value)} placeholder="要完成什么" value={workObjective} /><input aria-label="工作项交付" maxLength={500} onChange={(event) => setWorkOutput(event.target.value)} placeholder="期望交付" value={workOutput} /><Select aria-label="工作项负责人" onValueChange={setWorkOwner} options={activeParticipants.map((participant) => ({ value: participant.id, label: roomPlanetName(participant.ordinal) }))} placeholder="选择负责人" value={workOwner} /><button disabled={!workObjective.trim() || !workOutput.trim() || Boolean(busyKey)} onClick={() => void createWorkItem()} type="button"><Plus size={14} />创建</button></div>
    </section>

    <section>
      <header><span><Settings2 size={15} /><strong>空间设置</strong></span><small>{permissionDisplayLabel}</small></header>
      <div className="paw-room-governance__form">
        <input aria-label="Room 名称" maxLength={120} onChange={(event) => setTitle(event.target.value)} value={title} />
        <input aria-label="Room 简介" maxLength={500} onChange={(event) => setDescription(event.target.value)} placeholder="简介" value={description} />
        <RoomPermissionPolicyEditor
          onChange={permissionPolicy ? setPermissionPolicy : undefined}
          menuSelect
          policy={permissionPolicy}
          roomKind={room.roomKind ?? 'collaboration'}
        />
        <button
          disabled={!title.trim() || Boolean(busyKey)}
          onClick={() => void mutate('settings', {
            pathId: 'agent.room.archive',
            params: { roomId: room.id },
            body: {
              archived: false,
              title: title.trim(),
              description: description.trim(),
              ...(permissionPolicy ? { permissionPolicy } : {}),
              routingPolicy: room.routingPolicy,
              routingConfig: (room.routingConfig ?? null) as unknown as Record<string, unknown>,
              moderatorParticipantId: room.moderatorParticipantId,
              ...(permissionPolicyChanged
                && permissionPolicy
                && roomPermissionPolicyNeedsWorkspaceConfirmation(permissionPolicy)
                ? { workspaceScopeConfirmation: 'APPROVE_WORKSPACE_SCOPE' }
                : {}),
              ...(permissionPolicyChanged
                && permissionPolicy
                && roomPermissionPolicyNeedsDangerousConfirmation(permissionPolicy)
                ? { dangerousModeConfirmation: 'ENABLE_FULL_TRUST' }
                : {}),
            } as unknown as ControlRequest['body'],
          })}
          type="button"
        >
          保存
        </button>
      </div>
      <button className="paw-room-governance__archive" disabled={Boolean(busyKey)} onClick={() => void mutate('archive', { pathId: 'agent.room.archive', params: { roomId: room.id }, body: { archived: true } })} type="button"><Archive size={14} />收起 Room</button>
    </section>
  </div>;
}

function roomAttachment(file: PickedFile, roomId: string): RoomAttachmentReceipt {
  if (file.roomId !== roomId || !isComposerAttachmentMimeType(file.mimeType) || !file.sha256) throw new TypeError('Room 附件回执无效。');
  return { mediaId: file.id, roomId, fileName: file.name.slice(0, 160) || '附件', mimeType: file.mimeType.toLowerCase(), byteSize: file.byteSize, sha256: file.sha256 };
}

function roomFromResponse(value: unknown): RoomSummary | undefined {
  const source = asRecord(value);
  return asRoom(source.room) ?? asRoom(value);
}

function roomErrorText(reason: unknown, fallback: string): string {
  const message = publicAgentErrorText(reason, fallback);
  return message === SESSION_WORKSPACE_MISSING_TEXT
    ? ROOM_WORKSPACE_MISSING_TEXT
    : message;
}

function asRoom(value: unknown): RoomSummary | undefined {
  const source = asRecord(value);
  return typeof source.id === 'string' && typeof source.title === 'string' && Array.isArray(source.participants) ? source as unknown as RoomSummary : undefined;
}

function asWorkItem(value: unknown): RoomWorkItem | undefined {
  const source = asRecord(value);
  return typeof source.id === 'string' && typeof source.roomId === 'string' && typeof source.objective === 'string' ? source as unknown as RoomWorkItem : undefined;
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function roomEventClientActionId(value: unknown): string {
  const event = asRecord(value);
  const payload = asRecord(event.payload);
  const message = asRecord(payload.message);
  const post = asRecord(payload.post);
  const publicationSource = asRecord(post.publicationSource);
  const candidates = [
    payload.clientActionId,
    payload.clientMessageId,
    payload.client_action_id,
    payload.client_message_id,
    message.clientActionId,
    message.clientMessageId,
    post.clientActionId,
    post.clientMessageId,
    publicationSource.kind === 'user' ? publicationSource.ref : undefined,
  ];
  return candidates.find((candidate): candidate is string => (
    typeof candidate === 'string' && candidate.trim().length > 0
  ))?.trim() ?? '';
}

function participantName(room: RoomSummary | undefined, participantId: string): string {
  const participant = room?.participants.find((item) => item.id === participantId);
  return participant ? roomPlanetName(participant.ordinal) : '未分配';
}
