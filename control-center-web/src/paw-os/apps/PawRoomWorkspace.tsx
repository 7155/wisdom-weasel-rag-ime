import {
  Archive,
  CircleAlert,
  ExternalLink,
  Focus,
  GitBranch,
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
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { useShallow } from 'zustand/react/shallow';
import { useControlTransport } from '@/app/control-transport';
import { isComposerAttachmentMimeType } from '@/contracts/attachment-policy';
import type { RoomActivityProjection, RoomAttachmentReceipt } from '@/contracts/room-reducer';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import type { ControlRequest, PickedFile } from '@/platform/transport';
import { GenericUserInputCard } from '@/features/agent/review/AgentReviewDialogs';
import { QueueTray, useConversationQueue } from '@/features/conversation-ui';
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
  shouldAutoOpenRuntimeToolWindow,
} from '../runtime/runtime-tool-window';
import { PawWindowChromePortal, usePawWindowChromeTarget } from '../shell/PawWindowChrome';
import { roomProjection, useRoomLiveStore } from '@/features/rooms/state/live-store';
import type { RoomExecutionMode, RoomSummary, RoomWorkItem } from '@/features/rooms/room-types';
import { PawRoomConversation, roomProcessWindowRequest } from './PawRoomConversation';
import { PawRoomFocusOverview } from './PawRoomFocusOverview';
/* 星空按钮按下之前，星空代码不进入 Room 默认对话的 bundle 路径。 */
import { LazyPawRoomStarfield } from './PawStarfieldLazy';
import { buildRoomFocusProjection, roomFocusHasCoordinator, roomFocusOriginLabel, type RoomFocusProjection } from './room-focus-projection';
import { roomAutoSatelliteRequests, roomPlanetWindowRequest } from './room-satellite-auto-open';
/* Shared conversation modules (tool result panels, diff reader) style the
 * Room's tool receipts too; the Room window must not depend on a Session
 * window having loaded them first. */
import '@/features/agent/agent.css';
import '@/features/rooms/rooms.css';

export { PawRoomConversation } from './PawRoomConversation';

type RoomToolPanel = 'focus' | 'governance';

const roomToolPanelLabels: Record<RoomToolPanel, string> = {
  focus: '态势',
  governance: '治理',
};

const roomToolPanelIcons: Record<RoomToolPanel, LucideIcon> = {
  focus: Focus,
  governance: Settings2,
};

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
  const [view, setView] = useState<'conversation' | 'starfield'>('conversation');
  const [abortingTurnIds, setAbortingTurnIds] = useState<Set<string>>(() => new Set());
  const [recoveryState, setRecoveryState] = useState<'recovering' | 'failed' | 'synced'>('recovering');
  const runtimeToolWindow = useMemo(() => createRuntimeToolWindowProjector(), [recordId]);

  useEffect(() => {
    if (initialDraft !== undefined) setDraft(initialDraft);
    if (initialError) setError(initialError);
  }, [initialDraft, initialError]);

  useEffect(() => {
    setView('conversation');
  }, [recordId]);

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

  const title = record?.title || '未命名 Room';
  const activeParticipants = record?.participants.filter((participant) => participant.status === 'active') ?? [];
  const activeTopic = record?.topics?.find((topic) => topic.id === record.activeTopicId)
    ?? record?.topics?.find((topic) => topic.status === 'active');
  const activeRootId = activeTurn?.rootId ?? activeTurn?.id ?? '';
  const abortingActiveTurn = Boolean(activeRootId && abortingTurnIds.has(activeRootId));
  /* planet 窗口统一铭牌：从任何入口打开同一伙伴都走 roomPlanetWindowRequest。 */
  const openParticipant = useCallback((participant: RoomSummary['participants'][number], background = false) => desktop?.openWindow(
    roomPlanetWindowRequest(participant, recordId, background),
  ), [desktop, recordId]);
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
  /* PF-CM-013：协作态势可以弹出成一扇卫星窗，主 Room 留给公开对话。 */
  const openFocusSatellite = useCallback(() => {
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
    for (const request of roomAutoSatelliteRequests(record, autoExpandedParticipantIds.current)) {
      if (request.target.kind === 'participant') autoExpandedParticipantIds.current.add(request.target.id);
      desktop.openWindow(request);
    }
  }, [desktop, record, recordId]);
  /* status overlay 克制：为 0 的计数是噪音，状态行只亮出真实存在的工作。 */
  const signalChips = ([
    ['active', focusProjection?.counts.active ?? 0, '进行'],
    ['review', focusProjection?.counts.review ?? 0, '复核'],
    ['blocked', focusProjection?.counts.blocked ?? 0, '受阻'],
    ['complete', focusProjection?.counts.completed ?? 0, '完成'],
  ] as const).filter(([, count]) => count > 0);
  /* 没有主持就没有 Sol：signal chrome 只有在真的有伙伴担任 coordinator 时
     才用 Sol 命名这个 Room 的原点，否则统一叫「主 Room」。 */
  const coordinatorActive = focusProjection ? roomFocusHasCoordinator(focusProjection.partners) : false;
  const originLabel = roomFocusOriginLabel(coordinatorActive);
  const roomChromeControls = <div aria-label="Room 窗口控制" className="paw-room-window-chrome" data-coordinator={coordinatorActive || undefined} data-status={abortingActiveTurn ? 'stopping' : activeTurn ? 'busy' : recoveryState}>
    {coordinatorActive ? <span aria-label="Agent 中的 Sol 协作模式" className="paw-room-workspace__mode">Sol</span> : null}
    <nav aria-label="Room 工作台视图">
      <button aria-pressed={panel === 'none' && view === 'conversation'} onClick={() => { setView('conversation'); setPanel('none'); }} type="button"><MessageCircle size={14} /><span>公开对话</span></button>
      <button aria-pressed={panel !== 'none'} onClick={() => { setView('conversation'); setPanel((current) => current === 'none' ? 'focus' : current); }} type="button"><Focus size={14} /><span>协作态势</span></button>
      <button aria-pressed={view === 'starfield'} onClick={() => { setView('starfield'); setPanel('none'); }} type="button"><Orbit size={14} /><span>星空</span></button>
    </nav>
    <div className="paw-room-workspace__runtime"><span><i />{abortingActiveTurn ? '正在停止' : sending && activeTurn ? '正在干预' : activeTurn ? '协作中' : recoveryState === 'synced' ? '已同步' : '连接中'}</span>{activeTurn ? <button aria-label="停止整轮协作" disabled={abortingActiveTurn} onClick={() => void abortTurn(activeRootId)} type="button"><StopCircle size={16} /></button> : null}</div>
  </div>;
  return (
    <section
      className="paw-room-workspace paw-room-workspace--migrated-v1"
      data-agent-mode="room"
      data-panel={panel}
      data-view={view}
      data-window-chrome={windowChromeTarget ? 'portal' : 'fallback'}
      data-room-id={recordId}
      data-status={abortingActiveTurn ? 'stopping' : activeTurn ? 'busy' : recoveryState}
    >
      {windowChromeTarget ? <PawWindowChromePortal>{roomChromeControls}</PawWindowChromePortal> : <header className="paw-room-workspace__header">{roomChromeControls}</header>}

      <section aria-label="Room 当前协作" className="paw-room-workspace__signal">
        <div className="paw-room-workspace__objective">
          <div><small>目标</small><strong>{focusProjection?.goal.title || activeTopic?.title || activeWork?.objective || record?.description || '当前协作'}</strong></div>
          <span>{activeParticipants.length} 颗行星 · {focusProjection?.workItems.length ?? 0} 项任务</span>
        </div>
        {signalChips.length ? <div aria-label={`${originLabel} 当前状态`} className="paw-room-workspace__signal-status">
          {signalChips.map(([tone, count, label]) => <span data-tone={tone} key={tone}><i />{count} {label}</span>)}
        </div> : null}
      </section>

      <div className="paw-room-workspace__body">
        <main aria-label={`${title} 主 Room`} className="paw-room-workspace__main">
          {view === 'starfield' && focusProjection ? (
            <LazyPawRoomStarfield
              focus={focusProjection}
              roomId={recordId}
              onExit={() => setView('conversation')}
              onOpenParticipant={openParticipantById}
            />
          ) : <div className="paw-room-timeline" ref={timelineRef}>
              {projection && record ? <PawRoomConversation
                empty={loading
                  ? <div className="paw-room-workspace__loading"><LoaderCircle className="ui-spin" size={18} />正在恢复 Room 协作现场</div>
                  : <div className="paw-room-workspace__empty"><Users size={24} /><strong>Room 已准备好</strong><p>发送目标，伙伴会分工、执行并汇合结果。</p></div>}
                onApprovalDecision={decideApproval}
                onOpenProcessActivity={openProcessActivity}
                onRetryTurn={(message, retryOfRootId) => void send(message, { retryOfRootId, preserveDraft: true })}
                projection={projection}
                retryingTurn={sending}
                room={record}
              /> : null}
          </div>}

          <div className="paw-room-workspace__composer">
              {error ? <div className="paw-room-workspace__error" role="alert"><CircleAlert size={14} /><span>{error}</span><button onClick={() => { setError(''); retrySnapshot(); }} type="button">重新同步</button></div> : null}
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
                    onSend={(value) => void send(value, { question: pendingQuestion?.roomId === recordId ? pendingQuestion : undefined })}
                    onAttachmentsChange={setAttachments}
                    onPasteImages={(files) => void pasteFiles(files)}
                    onPasteFromClipboard={() => void pasteFiles()}
                    onPickAttachments={() => void pickAttachments()}
                  />
                </>
              )}
          </div>
        </main>
        {panel !== 'none' && record ? <PawRoomToolWorkspace
          onClose={() => setPanel('none')}
          onError={setError}
          onOpenParticipant={openParticipantById}
          onPanelChange={setPanel}
          {...(desktop ? { onPopout: openFocusSatellite } : {})}
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
  onPopout,
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
  onPopout?: () => void;
  onRefresh: () => Promise<void>;
  onRoomUpdated: (room: RoomSummary) => void;
  panel: RoomToolPanel;
  personas: AgentPersonaV1[];
  focusProjection?: RoomFocusProjection;
  room: RoomSummary;
}) {
  const tabId = useId();
  /* 空间指向：协作态势键在标题栏尾端，面板也必须从尾端展开。data-side 把这个
     朝向写成契约而不是 DOM 顺序的副作用，CSS 用同名网格区落位。 */
  return <aside aria-label="Room 协作态势" className="paw-room-tools" data-side="trailing">
    <header className="paw-room-tools__header">
      <span><Focus aria-hidden="true" size={15} /><strong>协作态势</strong></span>
      <div className="paw-room-tools__actions">
        {onPopout ? <button aria-label="在卫星窗中打开协作态势" onClick={onPopout} type="button"><ExternalLink aria-hidden="true" size={14} /></button> : null}
        <button aria-label="关闭协作态势" onClick={onClose} type="button"><X aria-hidden="true" size={15} /></button>
      </div>
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
  if (file.roomId !== roomId || !isComposerAttachmentMimeType(file.mimeType) || !file.sha256) throw new TypeError('Room 附件回执无效。');
  return { mediaId: file.id, roomId, fileName: file.name.slice(0, 160) || '附件', mimeType: file.mimeType.toLowerCase(), byteSize: file.byteSize, sha256: file.sha256 };
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
