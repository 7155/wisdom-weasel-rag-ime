import {
  ChevronRight,
  Archive,
  CircleAlert,
  CheckCircle2,
  Focus,
  GitBranch,
  LoaderCircle,
  MessageCircle,
  Plus,
  Settings2,
  ShieldAlert,
  StopCircle,
  UserMinus,
  UserPlus,
  Users,
  X,
  type LucideIcon,
} from 'lucide-react';
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { useControlTransport } from '@/app/control-transport';
import { approvalNeedsHumanDecision } from '@/contracts/approval-decision';
import type { RoomActivityProjection, RoomAttachmentReceipt, RoomMessageProjection, RoomProjectionState, RoomTurnProjection } from '@/contracts/room-reducer';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import type { ControlRequest, PickedFile } from '@/platform/transport';
import { GenericUserInputCard } from '@/features/agent/review/AgentReviewDialogs';
import { publicAgentErrorText } from '@/features/agent/public-error';
import { MarkdownBody } from '@/features/agent/timeline/BlockRenderer';
import { SmoothDisclosureReveal } from '@/features/agent/timeline/SmoothDisclosureReveal';
import {
  toggleDisclosureOnKeyPreservingAnchor,
  toggleDisclosurePreservingAnchor,
} from '@/features/agent/timeline/disclosure-anchor';
import { usePawOsDesktop } from '@/features/paw-os/surface-context';
import { publicErrorText } from '@/features/overview/management-ui';
import { RoomComposer, roomMentionedParticipants } from '@/features/rooms/composer/RoomComposer';
import { roomCollaborationRoleLabel } from '@/features/rooms/room-copy';
import { latestPendingGroupedRoomInput, type PendingRoomQuestion } from '@/features/rooms/room-question';
import {
  roomExecutionModeLabel,
  roomWorkStateLabel,
} from '@/features/rooms/room-presentation';
import {
  selectPublicRoomTurnOrder,
} from '@/features/rooms/runtime/room-execution-lanes';
import { useRoomLiveSession } from '@/features/rooms/runtime/use-room-live-session';
import { pulsePawCompositionForRuntimeEvents } from '../runtime/composition-pulse';
import {
  createRuntimeToolWindowProjector,
  runtimeToolWindowRequest,
  shouldAutoOpenRuntimeToolWindow,
} from '../runtime/runtime-tool-window';
import { PawWindowChromePortal, usePawWindowChromeTarget } from '../shell/PawWindowChrome';
import { roomProjection, useRoomLiveStore } from '@/features/rooms/state/live-store';
import type { RoomExecutionMode, RoomSummary, RoomWorkItem } from '@/features/rooms/room-types';
import { PawRoomFocusOverview } from './PawRoomFocusOverview';
import { buildRoomFocusProjection, roomFocusCelestialName, type RoomFocusProjection } from './room-focus-projection';
import { roomAutoSatelliteRequests } from './room-satellite-auto-open';
import '@/features/rooms/rooms.css';

type RoomToolPanel = 'focus' | 'governance';

const roomToolPanelLabels: Record<RoomToolPanel, string> = {
  focus: '态势',
  governance: '治理',
};

const roomToolPanelIcons: Record<RoomToolPanel, LucideIcon> = {
  focus: Focus,
  governance: Settings2,
};

const imageTypes = new Set(['image/png', 'image/jpeg', 'image/gif', 'image/webp']);

export function PawRoomWorkspace({
  initialDraft,
  initialError,
  personas,
  record,
  recordId,
  onRoomUpdated,
}: {
  initialDraft?: string;
  initialError?: string;
  personas: AgentPersonaV1[];
  record?: RoomSummary;
  recordId: string;
  onRoomUpdated: (room: RoomSummary) => void;
}) {
  const transport = useControlTransport();
  const desktop = usePawOsDesktop();
  const windowChromeTarget = usePawWindowChromeTarget();
  const timelineRef = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState(initialDraft ?? '');
  const [attachments, setAttachments] = useState<RoomAttachmentReceipt[]>([]);
  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(initialError ?? '');
  const [panel, setPanel] = useState<RoomToolPanel | 'none'>('focus');
  const [abortingTurnIds, setAbortingTurnIds] = useState<Set<string>>(() => new Set());
  const [recoveryState, setRecoveryState] = useState<'recovering' | 'failed' | 'synced'>('recovering');
  const runtimeToolWindow = useMemo(() => createRuntimeToolWindowProjector(), [recordId]);

  useEffect(() => {
    if (initialDraft !== undefined) setDraft(initialDraft);
    if (initialError) setError(initialError);
  }, [initialDraft, initialError]);

  const projection = useRoomLiveStore((state) => state.projections[recordId]);
  const focusProjection = useMemo(
    () => record ? buildRoomFocusProjection(record, projection) : undefined,
    [projection, record],
  );
  const participantAliases = useMemo(() => Object.fromEntries(
    focusProjection?.partners.map((partner) => [partner.participantId, partner.celestialName]) ?? [],
  ), [focusProjection]);
  const turnOrder = useRoomLiveStore(useShallow((state) => {
    const current = state.projections[recordId];
    return current ? selectPublicRoomTurnOrder(current) : [];
  }));
  const pendingQuestion = projection?.pendingUserQuestion;
  const pendingGroupedInput = latestPendingGroupedRoomInput(projection);
  const activeTurn = [...turnOrder]
    .reverse()
    .map((turnId) => projection?.turnsById[turnId])
    .find((turn) => turn?.status === 'queued' || turn?.status === 'running');
  const activeWork = record?.workItems?.find((item) => ['queued', 'active', 'review', 'blocked'].includes(item.state));
  const taskBusyState = record?.roomKind === 'roleplay'
    ? undefined
    : activeWork?.state === 'blocked'
      ? 'blocked' as const
      : activeTurn || activeWork
        ? 'running' as const
        : undefined;

  const retrySnapshot = useRoomLiveSession({
    roomId: recordId,
    transport,
    onLoadingChange: setLoading,
    onSnapshot: (_roomId, snapshot) => {
      const room = asRoom(snapshot.room);
      if (room) onRoomUpdated(room);
    },
    onMetadata: (_roomId, value) => {
      const room = roomFromResponse(value);
      if (room) onRoomUpdated(room);
    },
    onConnectionRestored: () => setError(''),
    onRecoveryState: (_roomId, state) => setRecoveryState(state),
    onConnectionError: (_roomId, reason, fallback) => setError(publicErrorText(reason, fallback)),
    onEvents: (_roomId, events) => {
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
    }
    try {
      const response = await transport.request<Record<string, unknown>>(steering && activeTurn
        ? {
            pathId: 'agent.room.participant.steer',
            params: { roomId: recordId },
            body: {
              action: 'steer_participant',
              rootId: activeTurn.rootId ?? activeTurn.id,
              participantId: activeTurn.participantIds[0] ?? '',
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
            },
          });
      useRoomLiveStore.getState().acceptMessage(recordId, response);
      const workItem = asWorkItem(asRecord(response).workItem);
      if (workItem) onRoomUpdated({
        ...record,
        workItems: [...(record.workItems ?? []).filter((item) => item.id !== workItem.id), workItem],
      });
      requestAnimationFrame(() => timelineRef.current?.scrollTo({ top: timelineRef.current.scrollHeight, behavior: 'smooth' }));
      return true;
    } catch (reason) {
      if (!steering) useRoomLiveStore.getState().discardOptimistic(recordId, clientMessageId);
      if (!options.preserveDraft) setDraft(rawValue);
      if (!answersQuestion) setAttachments(selectedAttachments);
      setError(publicErrorText(reason, 'Room 消息没有发送，请重试。'));
      return false;
    } finally {
      setSending(false);
    }
  }

  async function abortTurn(rootId: string): Promise<void> {
    if (!rootId || abortingTurnIds.has(rootId)) return;
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

  async function pickImages(): Promise<void> {
    if (!transport.pickFiles) { setError('当前环境不能选择图片。'); return; }
    try {
      const imported = await transport.pickFiles({
        purpose: 'attachment',
        roomId: recordId,
        accepts: [...imageTypes],
        multiple: true,
        maxFiles: Math.max(1, 8 - attachments.length),
      });
      mergePickedImages(imported);
    } catch (reason) { setError(publicErrorText(reason, '图片没有导入，请重试。')); }
  }

  async function pasteImages(files?: File[]): Promise<void> {
    if (!transport.pasteImages) { setError('当前环境不能导入剪贴板图片。'); return; }
    try {
      const imported = await transport.pasteImages({
        roomId: recordId,
        ...(files?.length ? { files } : {}),
        maxFiles: files?.length || Math.max(1, 8 - attachments.length),
      });
      mergePickedImages(imported);
    } catch (reason) { setError(publicErrorText(reason, '图片没有导入，请重试。')); }
  }

  function mergePickedImages(files: PickedFile[]): void {
    const receipts = files.map((file) => roomAttachment(file, recordId));
    setAttachments((current) => {
      const byId = new Map(current.map((item) => [item.mediaId, item]));
      receipts.forEach((item) => byId.set(item.mediaId, item));
      return [...byId.values()].slice(0, 8);
    });
  }

  const title = record?.title || '未命名 Room';
  const activeParticipants = record?.participants.filter((participant) => participant.status === 'active') ?? [];
  const activeTopic = record?.topics?.find((topic) => topic.id === record.activeTopicId)
    ?? record?.topics?.find((topic) => topic.status === 'active');
  const activeRootId = activeTurn?.rootId ?? activeTurn?.id ?? '';
  const abortingActiveTurn = Boolean(activeRootId && abortingTurnIds.has(activeRootId));
  const openParticipant = useCallback((participant: RoomSummary['participants'][number], background = false) => desktop?.openWindow({
    appId: 'agent',
    background,
    target: {
      kind: 'participant',
      id: participant.id,
      roomId: recordId,
      title: participantAliases[participant.id] || participant.displayName,
      subtitle: `${participant.displayName} · ${roomCollaborationRoleLabel(participant.collaborationRole)} · ${participant.sessionId}`,
    },
  }), [desktop, participantAliases, recordId]);
  const openParticipantById = useCallback((participantId: string) => {
    const participant = record?.participants.find((candidate) => candidate.id === participantId);
    if (!participant) return;
    setPanel('none');
    openParticipant(participant);
  }, [openParticipant, record?.participants]);
  const openProcessActivity = useCallback((activity: RoomActivityProjection) => {
    const request = roomProcessWindowRequest(activity, recordId);
    if (request) desktop?.openWindow({ ...request, background: false });
  }, [desktop, recordId]);
  useEffect(() => {
    if (!desktop || !record) return;
    desktop.bindRoomMain?.({ kind: 'room', id: record.id, title: record.title, subtitle: record.description });
  }, [desktop, record]);
  /* UR-054：进入 Room 自动展开活跃伙伴卫星窗（后台，不抢主 Room 焦点）。
     每位伙伴每次进入只展开一次，用户关闭后不会被循环重开。 */
  const autoExpandedParticipantIds = useRef(new Set<string>());
  useEffect(() => { autoExpandedParticipantIds.current = new Set(); }, [recordId]);
  useEffect(() => {
    if (!desktop || !record || record.id !== recordId) return;
    for (const request of roomAutoSatelliteRequests(record, participantAliases, autoExpandedParticipantIds.current)) {
      if (request.target.kind === 'participant') autoExpandedParticipantIds.current.add(request.target.id);
      desktop.openWindow(request);
    }
  }, [desktop, participantAliases, record, recordId]);
  const roomChromeControls = <div aria-label="Room 窗口控制" className="paw-room-window-chrome" data-status={abortingActiveTurn ? 'stopping' : activeTurn ? 'busy' : recoveryState}>
    <span aria-label="Agent 中的 Sol 协作模式" className="paw-room-workspace__mode">Sol</span>
    <nav aria-label="Room 工作台视图">
      <button aria-pressed={panel === 'none'} onClick={() => setPanel('none')} type="button"><MessageCircle size={14} /><span>公开对话</span></button>
      <button aria-pressed={panel !== 'none'} onClick={() => setPanel((current) => current === 'none' ? 'focus' : current)} type="button"><Focus size={14} /><span>协作态势</span></button>
    </nav>
    <div className="paw-room-workspace__runtime"><span><i />{abortingActiveTurn ? '正在停止' : sending && activeTurn ? '正在干预' : activeTurn ? '协作中' : recoveryState === 'synced' ? '已同步' : '连接中'}</span>{activeTurn ? <button aria-label="停止整轮协作" disabled={abortingActiveTurn} onClick={() => void abortTurn(activeRootId)} type="button"><StopCircle size={16} /></button> : null}</div>
  </div>;
  return (
    <section
      className="paw-room-workspace paw-room-workspace--migrated-v1"
      data-agent-mode="room"
      data-panel={panel}
      data-window-chrome={windowChromeTarget ? 'portal' : 'fallback'}
      data-room-id={recordId}
      data-status={abortingActiveTurn ? 'stopping' : activeTurn ? 'busy' : recoveryState}
    >
      {windowChromeTarget ? <PawWindowChromePortal>{roomChromeControls}</PawWindowChromePortal> : <header className="paw-room-workspace__header">{roomChromeControls}</header>}

      <section aria-label="Room 当前协作" className="paw-room-workspace__signal">
        <div className="paw-room-workspace__objective">
          <div><small>目标</small><strong>{focusProjection?.goal.title || activeTopic?.title || activeWork?.objective || record?.description || '当前协作'}</strong></div>
          <span>{activeParticipants.length} 颗行星 · {focusProjection?.workItems.length ?? 0} 个 WorkItem</span>
        </div>
        {focusProjection ? <div aria-label="Sol 当前状态" className="paw-room-workspace__signal-status">
          <span data-tone="active"><i />{focusProjection.counts.active} 进行</span>
          <span data-tone="review"><i />{focusProjection.counts.review} 复核</span>
          <span data-tone="blocked"><i />{focusProjection.counts.blocked} 受阻</span>
          <span data-tone="complete"><i />{focusProjection.counts.completed} 完成</span>
        </div> : null}
      </section>

      <div className="paw-room-workspace__body">
        <main aria-label={`${title} 主 Room`} className="paw-room-workspace__main">
          <div aria-label="Root 对话与公开协作事件" className="paw-room-timeline" ref={timelineRef} role="log">
              <div className="paw-room-timeline__canvas">
                {loading && !turnOrder.length ? <div className="paw-room-workspace__loading"><LoaderCircle className="ui-spin" size={18} />正在恢复 Room 协作现场</div> : null}
                {!loading && !turnOrder.length ? <div className="paw-room-workspace__empty"><Users size={24} /><strong>Room 已准备好</strong><p>发送目标，伙伴会分工、执行并汇合结果。</p></div> : null}
                {projection && record ? <PawRoomConversation
                  onApprovalDecision={decideApproval}
                  onOpenProcessActivity={openProcessActivity}
                  onRetryTurn={(message, retryOfRootId) => void send(message, { retryOfRootId, preserveDraft: true })}
                  projection={projection}
                  retryingTurn={sending}
                  room={record}
                /> : null}
              </div>
          </div>

          <div className="paw-room-workspace__composer">
              {error ? <div className="paw-room-workspace__error" role="alert"><CircleAlert size={14} /><span>{error}</span><button onClick={() => { setError(''); retrySnapshot(); }} type="button">重新同步</button></div> : null}
              {pendingGroupedInput ? <GenericUserInputCard activity={pendingGroupedInput} sessionId={pendingGroupedInput.sourceSessionId} onError={setError} /> : (
                <RoomComposer
                  room={record}
                  participantAliases={participantAliases}
                  personas={personas}
                  draft={draft}
                  attachments={attachments}
                  sending={sending}
                  taskBusyState={taskBusyState}
                  pendingUserAnswer={pendingQuestion?.roomId === recordId}
                  onDraftChange={setDraft}
                  onSend={(value) => void send(value, { question: pendingQuestion?.roomId === recordId ? pendingQuestion : undefined })}
                  onAttachmentsChange={setAttachments}
                  onPasteImages={(files) => void pasteImages(files)}
                  onPasteFromClipboard={() => void pasteImages()}
                  onPickAttachments={() => void pickImages()}
                />
              )}
          </div>
        </main>
        {panel !== 'none' && record ? <PawRoomToolWorkspace
          onClose={() => setPanel('none')}
          onError={setError}
          onOpenParticipant={openParticipantById}
          onPanelChange={setPanel}
          onRefresh={async () => { retrySnapshot(); }}
          onRoomUpdated={onRoomUpdated}
          panel={panel}
          personas={personas}
          focusProjection={focusProjection}
          room={record}
        /> : null}
      </div>
    </section>
  );

}

function PawRoomToolWorkspace({
  onClose,
  onError,
  onOpenParticipant,
  onPanelChange,
  onRefresh,
  onRoomUpdated,
  panel,
  personas,
  focusProjection,
  room,
}: {
  onClose: () => void;
  onError: (message: string) => void;
  onOpenParticipant: (participantId: string) => void;
  onPanelChange: (panel: RoomToolPanel) => void;
  onRefresh: () => Promise<void>;
  onRoomUpdated: (room: RoomSummary) => void;
  panel: RoomToolPanel;
  personas: AgentPersonaV1[];
  focusProjection?: RoomFocusProjection;
  room: RoomSummary;
}) {
  const tabId = useId();
  return <aside aria-label="Room 协作态势" className="paw-room-tools">
    <header className="paw-room-tools__header">
      <span><Focus aria-hidden="true" size={15} /><strong>协作态势</strong></span>
      <button aria-label="关闭协作态势" onClick={onClose} type="button"><X aria-hidden="true" size={15} /></button>
    </header>
    <nav aria-label="协作工具视图" className="paw-room-tools__tabs" role="tablist">
      {(Object.keys(roomToolPanelLabels) as RoomToolPanel[]).map((item) => {
        const Icon = roomToolPanelIcons[item];
        return <button
          aria-controls={`${tabId}-panel`}
          aria-selected={item === panel}
          id={`${tabId}-${item}`}
          key={item}
          onClick={() => onPanelChange(item)}
          role="tab"
          tabIndex={item === panel ? 0 : -1}
          type="button"
        ><Icon aria-hidden="true" size={14} /><span>{roomToolPanelLabels[item]}</span></button>;
      })}
    </nav>
    <div aria-labelledby={`${tabId}-${panel}`} className="paw-room-tools__content" id={`${tabId}-panel`} role="tabpanel">
      {panel === 'focus' && focusProjection ? <PawRoomFocusOverview focus={focusProjection} hideMission onOpenParticipant={onOpenParticipant} /> : null}
      {panel === 'governance' ? <PawRoomGovernance personas={personas} room={room} onError={onError} onRefresh={onRefresh} onRoomUpdated={onRoomUpdated} /> : null}
    </div>
  </aside>;
}

type PawRoomChronologyEntry =
  | { id: string; kind: 'message'; message: RoomMessageProjection; order: number }
  | { id: string; kind: 'activity'; activity: RoomActivityProjection; order: number }
  | { id: string; kind: 'terminal'; turn: RoomTurnProjection; order: number };

/** PAWOS-owned public chronology. It consumes the production Room projection
 * directly, but deliberately does not inherit the legacy RoomTurn card DOM.
 * 中央叙事按真实 Turn 分组：一次 loop 一张卡；Tool/分派/进度折叠进对应
 * Turn（UR-085 折叠不丢 trace）；待决审批永不折叠（UR-004 审批在 Room 内）。 */
export function PawRoomConversation({
  onApprovalDecision,
  onOpenProcessActivity,
  onRetryTurn,
  projection,
  retryingTurn,
  room,
}: {
  onApprovalDecision: (approvalId: string, decision: 'approved' | 'rejected', payloadSha256: string) => Promise<void>;
  onOpenProcessActivity?: (activity: RoomActivityProjection) => void;
  onRetryTurn: (message: string, rootId: string) => void;
  projection: RoomProjectionState;
  retryingTurn: boolean;
  room: RoomSummary;
}) {
  const turnGroups = useMemo(() => pawRoomTurnGroups(projection), [projection]);
  return <section aria-label="Room 公开对话" className="paw-room-chronology">
    {turnGroups.map((group) => (
      <section className="paw-room-chronology__turn" data-status={group.status} key={group.id}>
        {group.items.map((item) => {
          if (item.kind === 'fold') {
            return <PawRoomActivityFold
              activities={item.activities}
              foldId={item.id}
              key={item.id}
              onApprovalDecision={onApprovalDecision}
              onOpenProcessActivity={onOpenProcessActivity}
              room={room}
            />;
          }
          if (item.kind === 'activity') return <PawRoomInlineActivity activity={item.activity} key={item.id} onApprovalDecision={onApprovalDecision} onOpenProcessActivity={onOpenProcessActivity} room={room} />;
          if (item.kind === 'terminal') {
            const retrySource = roomTurnSupersededByUserInput(item.turn, projection)
              ? undefined
              : item.turn.messageIds
                  .map((messageId) => projection.messagesById[messageId])
                  .find((message) => message?.role === 'user' && message.text.trim());
            return <section className="paw-room-chronology__terminal" data-status={item.turn.status} key={item.id} role="status">
              <CircleAlert aria-hidden="true" size={15} />
              <span><strong>{item.turn.status === 'aborted' ? '这轮协作已停止' : '这轮协作未完成'}</strong><small>{publicAgentErrorText(item.turn.failure, '可以保留原请求并开始一次新的尝试。')}</small></span>
              {retrySource ? <button disabled={retryingTurn} onClick={() => onRetryTurn(retrySource.text, item.turn.rootId || item.turn.id)} type="button">{retryingTurn ? '正在重试' : '再试一次'}</button> : null}
            </section>;
          }
          const { message } = item;
          const participant = message.participantId ? room.participants.find((candidate) => candidate.id === message.participantId) : undefined;
          const actor = participant ? roomFocusCelestialName(participant.ordinal) : 'Sol';
          return <article className="paw-room-chronology__message" data-role={message.role} data-status={message.status} key={item.id}>
            {message.role === 'user' ? (
              <time className="sr-only" dateTime={new Date(message.createdAtMs).toISOString()}>用户消息，发送于 {pawRoomClock(message.createdAtMs)}</time>
            ) : <header><strong title={participant?.displayName}>{actor}</strong>{participant ? <small>{roomCollaborationRoleLabel(participant.collaborationRole)}</small> : null}<time>{pawRoomClock(message.createdAtMs)}</time></header>}
            <div><MarkdownBody text={message.text || '这条公开消息没有正文。'} /></div>
            {message.status === 'streaming' ? <small className="paw-room-chronology__live">正在生成公开回复</small> : null}
          </article>;
        })}
      </section>
    ))}
  </section>;
}

/**
 * A Room turn can contain many pages of routing and tool activity. The summary
 * stays in the native `details` shell for its familiar semantics, while the
 * measured reveal owns opening, closing, and a reversible in-flight transition.
 * A running fold opens once by default, but a user's later choice always wins.
 */
function PawRoomActivityFold({
  activities,
  foldId,
  onApprovalDecision,
  onOpenProcessActivity,
  room,
}: {
  activities: RoomActivityProjection[];
  foldId: string;
  onApprovalDecision: (approvalId: string, decision: 'approved' | 'rejected', payloadSha256: string) => Promise<void>;
  onOpenProcessActivity?: (activity: RoomActivityProjection) => void;
  room: RoomSummary;
}) {
  const active = activities.some((activity) => activity.status === 'running' || activity.status === 'waiting');
  const latest = activities.at(-1)!;
  const latestEventType = roomText(latest.payload.sourceEventType, latest.kind);
  const disclosureId = `paw-room-fold-${useId().replaceAll(':', '')}`;
  const [open, setOpen] = useState(active);
  const [presence, setPresence] = useState(active);
  const userChoiceRef = useRef(false);
  const wasActiveRef = useRef(active);

  useEffect(() => {
    const wasActive = wasActiveRef.current;
    wasActiveRef.current = active;
    // A new running phase should reveal itself once, unless the reader has
    // already chosen the compact view. Completion deliberately changes nothing.
    if (active && !wasActive && !userChoiceRef.current) setOpen(true);
  }, [active]);

  const markUserChoice = () => { userChoiceRef.current = true; };
  return <details
    className="paw-room-chronology__fold"
    data-active={active || undefined}
    data-fold-id={foldId}
    open={open || presence}
  >
    <summary
      aria-controls={disclosureId}
      aria-expanded={open}
      onClick={(event) => {
        markUserChoice();
        toggleDisclosurePreservingAnchor(event, setOpen);
      }}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') markUserChoice();
        toggleDisclosureOnKeyPreservingAnchor(event, setOpen);
      }}
    >
      <ChevronRight aria-hidden="true" size={13} />
      <strong>运行与流转 {activities.length} 项</strong>
      <small>{pawRoomActivitySummary(latest, latestEventType)}</small>
    </summary>
    <SmoothDisclosureReveal
      className="paw-room-chronology__reveal"
      id={disclosureId}
      onPresenceChange={setPresence}
      open={open}
    >
      <div className="paw-room-chronology__fold-content">
        {activities.map((activity) => <PawRoomInlineActivity activity={activity} key={activity.id} onApprovalDecision={onApprovalDecision} onOpenProcessActivity={onOpenProcessActivity} room={room} />)}
      </div>
    </SmoothDisclosureReveal>
  </details>;
}

type PawRoomChronologyItem =
  | PawRoomChronologyEntry
  | { id: string; kind: 'fold'; activities: RoomActivityProjection[]; order: number };

type PawRoomTurnGroup = { id: string; status?: string; items: PawRoomChronologyItem[] };

/** Group the public chronology by real Room turn (sequence first), then fold
 * each turn's tool/route/progress runs into one disclosure. Folding changes
 * projection only: no trace is deleted, no event is reordered. */
function pawRoomTurnGroups(projection: RoomProjectionState): PawRoomTurnGroup[] {
  const groups: PawRoomTurnGroup[] = [];
  const groupById = new Map<string, PawRoomTurnGroup>();
  for (const entry of pawRoomChronologyEntries(projection)) {
    const turnId = entry.kind === 'message'
      ? entry.message.turnId || entry.message.rootId
      : entry.kind === 'activity'
        ? entry.activity.turnId || roomText(entry.activity.payload.rootId)
        : entry.turn.id;
    const key = turnId || 'room:ungrouped';
    let group = groupById.get(key);
    if (!group) {
      group = { id: key, status: projection.turnsById[key]?.status, items: [] };
      groupById.set(key, group);
      groups.push(group);
    }
    group.items.push(entry);
  }
  for (const group of groups) {
    const folded: PawRoomChronologyItem[] = [];
    for (const item of group.items) {
      if (item.kind === 'activity' && !pawRoomActivityNeedsInlineDecision(item.activity)) {
        const previous = folded.at(-1);
        if (previous?.kind === 'fold') {
          previous.activities.push(item.activity);
        } else {
          folded.push({ id: `fold:${item.id}`, kind: 'fold', activities: [item.activity], order: item.order });
        }
      } else {
        folded.push(item);
      }
    }
    group.items = folded;
  }
  return groups;
}

/** Pending approvals stay inline so the Room resolves them where they happen. */
function pawRoomActivityNeedsInlineDecision(activity: RoomActivityProjection): boolean {
  const approvalId = roomText(activity.payload.approvalId);
  const approvalHash = roomText(activity.payload.payloadSha256);
  const resolutionState = roomText(activity.payload.resolutionState || activity.payload.state);
  return Boolean(
    approvalId
    && approvalHash
    && approvalNeedsHumanDecision(activity.payload)
    && !['approved', 'rejected', 'applied', 'resolved', 'cancelled'].includes(resolutionState),
  );
}

function roomTurnSupersededByUserInput(
  turn: RoomTurnProjection,
  projection: RoomProjectionState,
): boolean {
  const turnMessageIndexes = turn.messageIds
    .map((messageId) => projection.messageOrder.indexOf(messageId))
    .filter((index) => index >= 0);
  const messageBoundary = turnMessageIndexes.length ? Math.max(...turnMessageIndexes) : -1;
  if (messageBoundary >= 0) {
    return projection.messageOrder.slice(messageBoundary + 1).some((messageId) => {
      const message = projection.messagesById[messageId];
      return message?.role === 'user' && message.text.trim().length > 0;
    });
  }
  const turnIndex = projection.turnOrder.indexOf(turn.id);
  if (turnIndex < 0) return false;
  return projection.turnOrder.slice(turnIndex + 1).some((turnId) => {
    const laterTurn = projection.turnsById[turnId];
    return laterTurn?.messageIds.some((messageId) => {
      const message = projection.messagesById[messageId];
      return message?.role === 'user' && message.text.trim().length > 0;
    }) ?? false;
  });
}

function pawRoomChronologyEntries(projection: RoomProjectionState): PawRoomChronologyEntry[] {
  const entries: PawRoomChronologyEntry[] = [];
  for (const messageId of projection.messageOrder) {
    const message = projection.messagesById[messageId];
    if (!message || message.projectionKind === 'execution' || (!message.text.trim() && !message.question)) continue;
    entries.push({ id: `message:${message.id}`, kind: 'message', message, order: message.sequence ?? message.createdAtMs });
  }
  for (const activityId of projection.activityOrder) {
    const activity = projection.activitiesById[activityId];
    if (!activity || !pawRoomInlineActivityVisible(activity)) continue;
    entries.push({ id: `activity:${activity.id}`, kind: 'activity', activity, order: activity.sequence ?? activity.createdAtMs });
  }
  for (const turnId of projection.turnOrder) {
    const turn = projection.turnsById[turnId];
    if (!turn || (turn.status !== 'failed' && turn.status !== 'aborted')) continue;
    entries.push({ id: `terminal:${turn.id}`, kind: 'terminal', turn, order: (turn.updatedAtMs || turn.createdAtMs) + .75 });
  }
  return entries.sort((left, right) => left.order - right.order || left.id.localeCompare(right.id));
}

function pawRoomInlineActivityVisible(activity: RoomActivityProjection): boolean {
  const eventType = roomText(activity.payload.sourceEventType, activity.kind);
  return Boolean(roomText(activity.payload.approvalId))
    || eventType.startsWith('tool_')
    || ['reasoning', 'progress', 'route', 'route_decision', 'dispatch', 'status'].includes(activity.kind)
    || eventType.includes('route')
    || eventType.includes('dispatch');
}

function PawRoomInlineActivity({ activity, onApprovalDecision, onOpenProcessActivity, room }: {
  activity: RoomActivityProjection;
  onApprovalDecision: (approvalId: string, decision: 'approved' | 'rejected', payloadSha256: string) => Promise<void>;
  onOpenProcessActivity?: (activity: RoomActivityProjection) => void;
  room: RoomSummary;
}) {
  const approvalId = roomText(activity.payload.approvalId);
  const approvalHash = roomText(activity.payload.payloadSha256);
  const resolutionState = roomText(activity.payload.resolutionState || activity.payload.state);
  const approvalPending = Boolean(
    approvalId
    && approvalHash
    && approvalNeedsHumanDecision(activity.payload)
    && !['approved', 'rejected', 'applied', 'resolved', 'cancelled'].includes(resolutionState),
  );
  const [submitting, setSubmitting] = useState<'' | 'approved' | 'rejected'>('');
  const [decisionError, setDecisionError] = useState('');
  const participant = activity.participantId ? room.participants.find((item) => item.id === activity.participantId) : undefined;
  const eventType = roomText(activity.payload.sourceEventType, activity.kind);
  const summary = pawRoomActivitySummary(activity, eventType);
  const rawDetail = activity.summary.trim();
  const processWindow = onOpenProcessActivity
    ? roomProcessWindowRequest(activity, room.id)
    : null;
  const decide = (decision: 'approved' | 'rejected') => {
    if (!approvalPending || submitting) return;
    setDecisionError('');
    setSubmitting(decision);
    void onApprovalDecision(approvalId, decision, approvalHash)
      .catch((error: unknown) => setDecisionError(publicAgentErrorText(error)))
      .finally(() => setSubmitting(''));
  };
  return <article className="paw-room-chronology__activity" data-kind={approvalId ? 'approval' : eventType} data-status={activity.status}>
    <span aria-hidden="true">{approvalId ? <ShieldAlert size={14} /> : activity.status === 'completed' ? <CheckCircle2 size={14} /> : <LoaderCircle className={activity.status === 'running' ? 'ui-spin' : undefined} size={14} />}</span>
    <div><strong>{participant?.displayName || 'Root'} · {pawRoomActivityKindLabel(eventType, approvalId)}</strong><p>{summary}</p></div>
    <time>{pawRoomClock(activity.createdAtMs)}</time>
    {rawDetail && rawDetail !== summary ? <PawRoomRawActivityDetail detail={rawDetail} /> : null}
    {processWindow ? <footer><button onClick={() => onOpenProcessActivity?.(activity)} type="button">查看后台 Bash</button></footer> : null}
    {approvalPending ? <footer><button disabled={Boolean(submitting)} onClick={() => decide('approved')} type="button">{submitting === 'approved' ? '正在批准' : '批准并继续'}</button><button disabled={Boolean(submitting)} onClick={() => decide('rejected')} type="button">{submitting === 'rejected' ? '正在拒绝' : '拒绝'}</button></footer> : null}
    {decisionError ? <small role="alert">{decisionError}</small> : null}
  </article>;
}

function PawRoomRawActivityDetail({ detail }: { detail: string }) {
  const detailId = `paw-room-activity-detail-${useId().replaceAll(':', '')}`;
  const [open, setOpen] = useState(false);
  const [presence, setPresence] = useState(false);
  return <details className="paw-room-chronology__activity-detail" open={open || presence}>
    <summary
      aria-controls={detailId}
      aria-expanded={open}
      onClick={(event) => toggleDisclosurePreservingAnchor(event, setOpen)}
      onKeyDown={(event) => toggleDisclosureOnKeyPreservingAnchor(event, setOpen)}
    >详情</summary>
    <SmoothDisclosureReveal
      className="paw-room-chronology__detail-reveal"
      id={detailId}
      onPresenceChange={setPresence}
      open={open}
    >
      <p>{detail}</p>
    </SmoothDisclosureReveal>
  </details>;
}

function roomProcessWindowRequest(activity: RoomActivityProjection, roomId: string) {
  const request = runtimeToolWindowRequest({
    eventType: 'participant_activity',
    roomId,
    participantId: activity.participantId ?? undefined,
    sourceSessionId: activity.sourceSessionId,
    payload: {
      sourceEventType: roomText(activity.payload.sourceEventType, activity.kind),
      data: activity.payload,
    },
  });
  return request?.target.kind === 'process-terminal'
    && Boolean(request.target.runId || request.target.terminalId)
    ? request
    : null;
}

function pawRoomActivitySummary(activity: RoomActivityProjection, eventType: string): string {
  const detail = activity.summary.trim();
  const tool = roomText(activity.payload.displayName, roomText(activity.payload.toolName, roomText(activity.payload.toolId, '工具')));
  if (roomText(activity.payload.approvalId)) return detail && !pawRoomRawDetail(detail) ? detail : '等待你确认这项受控操作';
  if (eventType.startsWith('tool_')) {
    if (detail && !pawRoomRawDetail(detail)) return pawRoomCompactText(detail);
    return activity.status === 'running' ? `${tool} 正在执行` : activity.status === 'failed' ? `${tool} 执行失败` : activity.status === 'aborted' ? `${tool} 已停止` : `${tool} 已完成`;
  }
  return detail && !pawRoomRawDetail(detail) ? pawRoomCompactText(detail) : '公开进展已更新';
}

function pawRoomActivityKindLabel(eventType: string, approvalId: string): string {
  if (approvalId) return '审批';
  if (eventType.startsWith('tool_')) return '工具';
  if (eventType.includes('reasoning') || eventType.includes('thinking')) return '思考摘要';
  if (eventType.includes('route') || eventType.includes('dispatch')) return '分派';
  return '进展';
}

function pawRoomRawDetail(value: string): boolean {
  return value.includes('\n')
    || /```|(?:^|\s)[{[]\s*["']/u.test(value)
    || /\/(?:Users|Volumes|home|private|tmp|var)\//u.test(value)
    || /\b[a-f\d]{48,}\b/iu.test(value)
    || value.length > 180;
}

function pawRoomCompactText(value: string): string {
  const compact = value.replace(/\s+/gu, ' ').trim();
  return compact.length > 180 ? `${compact.slice(0, 177).trimEnd()}…` : compact;
}

function pawRoomClock(timestamp: number): string {
  return timestamp ? new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(new Date(timestamp)) : '';
}

function roomText(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
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
  const [executionMode, setExecutionMode] = useState<RoomExecutionMode>(room.executionMode ?? 'per_action');
  const activeParticipants = room.participants.filter((item) => item.status === 'active');
  const availablePersonas = personas.filter((persona) => !activeParticipants.some((item) => item.roleId === persona.roleId && item.roleVersion === persona.version));

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
      <header><span><Users size={15} /><strong>伙伴与分工</strong></span><small>{activeParticipants.length}/4</small></header>
      <div className="paw-room-governance__members">{activeParticipants.map((participant) => <article key={participant.id}>
        <span aria-hidden="true" className="paw-room-governance__member-mark"><Users size={14} /></span>
        <span><strong>{participant.displayName}</strong><small>{roomCollaborationRoleLabel(participant.collaborationRole)}</small></span>
        {room.roomKind !== 'roleplay' ? <select aria-label={`${participant.displayName} 的分工`} disabled={Boolean(busyKey)} onChange={(event) => void mutate(`role:${participant.id}`, { pathId: 'agent.room.participant.update', params: { roomId: room.id }, body: { participantId: participant.id, collaborationRole: event.target.value } })} value={participant.collaborationRole ?? 'implementer'}><option value="coordinator">主持</option><option value="researcher">研究</option><option value="implementer">实现</option><option value="reviewer">复核</option><option value="specialist">专家</option></select> : null}
        <button aria-label={`移出 ${participant.displayName}`} disabled={Boolean(busyKey) || activeParticipants.length <= 2 || participant.id === room.moderatorParticipantId} onClick={() => void mutate(`remove:${participant.id}`, { pathId: 'agent.room.participant.remove', params: { roomId: room.id }, body: { participantId: participant.id } })} type="button">{busyKey === `remove:${participant.id}` ? <LoaderCircle className="ui-spin" size={14} /> : <UserMinus size={14} />}</button>
      </article>)}</div>
      {availablePersonas.length && activeParticipants.length < 4 ? <label className="paw-room-governance__invite"><span><UserPlus size={14} />邀请伙伴</span><select defaultValue="" disabled={Boolean(busyKey)} onChange={(event) => { const persona = personas.find((item) => `${item.roleId}:${item.version}` === event.target.value); if (persona) void mutate(`add:${persona.roleId}`, { pathId: 'agent.room.participant.add', params: { roomId: room.id }, body: { roleId: persona.roleId, roleVersion: persona.version, collaborationRole: 'implementer' } }); event.target.value = ''; }}><option value="">选择伙伴…</option>{availablePersonas.map((persona) => <option key={`${persona.roleId}:${persona.version}`} value={`${persona.roleId}:${persona.version}`}>{persona.displayName}</option>)}</select></label> : null}
    </section>

    <section>
      <header><span><MessageCircle size={15} /><strong>话题</strong></span><small>{room.topics?.length ?? 0}</small></header>
      <div className="paw-room-governance__topics">{(room.topics ?? []).map((topic) => <article data-active={topic.id === room.activeTopicId || undefined} key={topic.id}><span><strong>{topic.title}</strong><small>{topic.summary || '暂无摘要'}</small></span>{topic.status === 'active' && topic.id !== room.activeTopicId ? <button onClick={() => void mutate(`topic:${topic.id}`, { pathId: 'agent.room.topic.update', params: { roomId: room.id }, body: { topicId: topic.id, activate: true } })} type="button">切换</button> : null}{topic.status === 'active' && topic.id !== room.activeTopicId ? <button aria-label={`归档 ${topic.title}`} onClick={() => void mutate(`archive-topic:${topic.id}`, { pathId: 'agent.room.topic.update', params: { roomId: room.id }, body: { topicId: topic.id, archived: true } })} type="button"><Archive size={13} /></button> : null}</article>)}</div>
      <div className="paw-room-governance__form"><input aria-label="新话题名称" maxLength={120} onChange={(event) => setTopicTitle(event.target.value)} placeholder="新话题" value={topicTitle} /><input aria-label="新话题摘要" maxLength={2000} onChange={(event) => setTopicSummary(event.target.value)} placeholder="摘要（可选）" value={topicSummary} /><button disabled={!topicTitle.trim() || Boolean(busyKey)} onClick={() => void createTopic()} type="button"><Plus size={14} />创建</button></div>
    </section>

    <section>
      <header><span><GitBranch size={15} /><strong>工作项</strong></span><small>{room.workItems?.length ?? 0}</small></header>
      <div className="paw-room-governance__work">{(room.workItems ?? []).map((work) => <article data-state={work.state} key={work.id}><span><strong>{work.objective}</strong><small>{roomWorkStateLabel(work.state)} · {participantName(room, work.currentOwnerParticipantId)}</small></span><select aria-label={`重新分配 ${work.objective}`} disabled={Boolean(busyKey) || ['done', 'failed', 'cancelled'].includes(work.state)} onChange={(event) => void mutate(`work:${work.id}`, { pathId: 'agent.room.workItem.reassign', params: { roomId: room.id, workItemId: work.id }, body: { actorParticipantId: room.moderatorParticipantId || activeParticipants[0]?.id, targetParticipantId: event.target.value, reason: '用户在 Room 治理面板重新分配' } })} value={work.currentOwnerParticipantId}>{activeParticipants.map((participant) => <option key={participant.id} value={participant.id}>{participant.displayName}</option>)}</select></article>)}</div>
      <div className="paw-room-governance__form"><input aria-label="工作项目标" maxLength={500} onChange={(event) => setWorkObjective(event.target.value)} placeholder="要完成什么" value={workObjective} /><input aria-label="工作项交付" maxLength={500} onChange={(event) => setWorkOutput(event.target.value)} placeholder="期望交付" value={workOutput} /><select aria-label="工作项负责人" onChange={(event) => setWorkOwner(event.target.value)} value={workOwner}><option value="">选择负责人</option>{activeParticipants.map((participant) => <option key={participant.id} value={participant.id}>{participant.displayName}</option>)}</select><button disabled={!workObjective.trim() || !workOutput.trim() || Boolean(busyKey)} onClick={() => void createWorkItem()} type="button"><Plus size={14} />创建</button></div>
    </section>

    <section>
      <header><span><Settings2 size={15} /><strong>空间设置</strong></span><small>{roomExecutionModeLabel(executionMode)}</small></header>
      <div className="paw-room-governance__form"><input aria-label="Room 名称" maxLength={120} onChange={(event) => setTitle(event.target.value)} value={title} /><input aria-label="Room 简介" maxLength={500} onChange={(event) => setDescription(event.target.value)} placeholder="简介" value={description} />{room.roomKind !== 'roleplay' ? <select aria-label="Room 执行权限" onChange={(event) => setExecutionMode(event.target.value as RoomExecutionMode)} value={executionMode}><option value="read_only">只读</option><option value="per_action">逐项确认</option><option value="workspace_managed">工作区托管</option><option value="full_trust">完全访问</option></select> : null}<button disabled={!title.trim() || Boolean(busyKey)} onClick={() => void mutate('settings', { pathId: 'agent.room.archive', params: { roomId: room.id }, body: { archived: false, title: title.trim(), description: description.trim(), executionMode, routingPolicy: room.routingPolicy, routingConfig: (room.routingConfig ?? null) as unknown as Record<string, unknown>, moderatorParticipantId: room.moderatorParticipantId, ...(executionMode === 'workspace_managed' ? { workspaceScopeConfirmation: 'APPROVE_WORKSPACE_SCOPE' } : {}), ...(executionMode === 'full_trust' ? { dangerousModeConfirmation: 'ENABLE_FULL_TRUST' } : {}) } as unknown as ControlRequest['body'] })} type="button">保存</button></div>
      <button className="paw-room-governance__archive" disabled={Boolean(busyKey)} onClick={() => void mutate('archive', { pathId: 'agent.room.archive', params: { roomId: room.id }, body: { archived: true } })} type="button"><Archive size={14} />收起 Room</button>
    </section>
  </div>;
}

function roomAttachment(file: PickedFile, roomId: string): RoomAttachmentReceipt {
  if (file.roomId !== roomId || !imageTypes.has(file.mimeType) || !file.sha256) throw new TypeError('Room 图片回执无效。');
  return { mediaId: file.id, roomId, fileName: file.name.slice(0, 160) || '图片', mimeType: file.mimeType as RoomAttachmentReceipt['mimeType'], byteSize: file.byteSize, sha256: file.sha256 };
}

function roomFromResponse(value: unknown): RoomSummary | undefined {
  const source = asRecord(value);
  return asRoom(source.room) ?? asRoom(value);
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

function participantName(room: RoomSummary | undefined, participantId: string): string {
  return room?.participants.find((item) => item.id === participantId)?.displayName ?? '未分配';
}
