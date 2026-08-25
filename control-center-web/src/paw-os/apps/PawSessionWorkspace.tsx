import {
  CircleAlert,
  FolderTree,
  GitBranch,
  ListChecks,
  LoaderCircle,
  MessageSquare,
  Network,
  Orbit,
  StopCircle,
  Wrench,
} from 'lucide-react';
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FocusEvent,
  type KeyboardEvent,
} from 'react';
import { useControlTransport } from '@/app/control-transport';
import type { AgentActivityProjection, AgentMessageProjection, AgentProjectionState } from '@/contracts/agent-reducer';
import { approvalNeedsHumanDecision } from '@/contracts/approval-decision';
import { createAgentDeltaBatcher } from '@/contracts/batching';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import type { UiAgentEvent } from '@/contracts/ui-events';
import {
  AgentComposer,
  type AgentMessageDelivery,
} from '@/features/agent/composer/AgentComposer';
import { SessionSubagentPanel } from '@/features/agent/delegation/SessionSubagentPanel';
import { PermissionMark, WorkspaceMark } from '@/features/agent/marks/ConversationMarks';
import { publicAgentErrorText } from '@/features/agent/public-error';
import { openPawOsRoute, usePawOsDesktop } from '@/features/paw-os/surface-context';
import { pulsePawCompositionForRuntimeEvent } from '../runtime/composition-pulse';
import {
  backgroundJobWindowRequest,
  createRuntimeToolWindowProjector,
  shouldAutoOpenRuntimeToolWindow,
} from '../runtime/runtime-tool-window';
import { PawWindowChromePortal, usePawWindowChromeTarget } from '../shell/PawWindowChrome';
import {
  ApprovalReviewDialog,
  GenericUserInputCard,
  MemoryReviewDialog,
} from '@/features/agent/review/AgentReviewDialogs';
import {
  ConversationForkDialog,
  resolveConversationEntryId,
  type ConversationNode,
} from '@/features/agent/sessions/ConversationForkDialog';
import { agentProjection, useAgentLiveStore } from '@/features/agent/state/live-store';
import { AgentStatusPanel } from '@/features/agent/status/AgentStatusPanel';
import { AgentTimeline } from '@/features/agent/timeline/AgentTimeline';
import { QueueTray, useConversationQueue } from '@/features/conversation-ui';
import { toolIntentPrompt } from '@/features/agent/tool-presentation';
import { AgentFilesPanel } from '@/features/agent/workspace/AgentFilesPanel';
import { PawContextTrace } from './PawContextTrace';
/* 星空按钮按下之前，星空代码不进入 Agent 主页/对话的 bundle 路径。 */
import { LazyPawSessionStarfield } from './PawStarfieldLazy';
import {
  commandItems,
  isModelCatalog,
  toolItems,
  type AgentCommand,
  type AgentPermissionSelection,
  type AgentProductCommandName,
  type ComposerAttachment,
  type ModelCatalog,
  type SessionSummary,
  type ThinkingLevel,
  type ToolManifest,
} from '@/features/agent/types';
import {
  capabilityScopeLabel,
  requireSessionCapabilityCatalog,
  type CapabilityCatalog,
  type CapabilityMutationOutcome,
  type CapabilityPreference,
} from '@/features/plugins/capability-policy';
import '@/features/agent/agent.css';

type WorkbenchPanel = 'none' | 'files' | 'subagents' | 'status';
type SessionWorkspaceView = 'conversation' | 'trace' | 'starfield';

export function PawSessionWorkspace({
  persona,
  record,
  recordId,
  initialDraft = '',
  onNewWork,
  onSessionCreated,
  onSessionActivity,
  onSessionUpdated,
}: {
  persona?: AgentPersonaV1;
  record?: SessionSummary;
  recordId: string;
  initialDraft?: string;
  onNewWork: () => void;
  onSessionCreated: (session: SessionSummary, draft: string) => void;
  onSessionActivity?: () => void;
  onSessionUpdated: (session: SessionSummary) => void;
}) {
  const transport = useControlTransport();
  const desktop = usePawOsDesktop();
  const windowChromeTarget = usePawWindowChromeTarget();
  const projection = useAgentLiveStore((state) => state.projections[recordId]);
  const [catalog, setCatalog] = useState<ModelCatalog>();
  const [commands, setCommands] = useState<AgentCommand[]>([]);
  const [tools, setTools] = useState<ToolManifest[]>([]);
  const [toolCatalogStatus, setToolCatalogStatus] = useState<'loading' | 'ready' | 'failed'>('loading');
  const [capabilityCatalog, setCapabilityCatalog] = useState<CapabilityCatalog>();
  const [capabilityCatalogError, setCapabilityCatalogError] = useState('');
  const [capabilityMutation, setCapabilityMutation] = useState<CapabilityMutationOutcome>();
  const [draft, setDraft] = useState(initialDraft);
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [modelChanging, setModelChanging] = useState(false);
  const [panel, setPanel] = useState<WorkbenchPanel>('none');
  const [toolMenuOpen, setToolMenuOpen] = useState(false);
  const [workspaceView, setWorkspaceView] = useState<SessionWorkspaceView>('conversation');
  const [error, setError] = useState('');
  const [modelPickerRequest, setModelPickerRequest] = useState(0);
  const [permissionPickerRequest, setPermissionPickerRequest] = useState(0);
  const [toolPickerRequest, setToolPickerRequest] = useState(0);
  const [helpRequest, setHelpRequest] = useState(0);
  const [requestedApproval, setRequestedApproval] = useState<AgentActivityProjection>();
  const [conversationForkAvailable, setConversationForkAvailable] = useState(false);
  const [conversationRewriteAvailable, setConversationRewriteAvailable] = useState(false);
  const [forkDialogOpen, setForkDialogOpen] = useState(false);
  const [forkDialogNodes, setForkDialogNodes] = useState<ConversationNode[]>([]);
  const [forkDialogInitialEntryId, setForkDialogInitialEntryId] = useState('');
  const [editState, setEditState] = useState<{ entryId: string; messageId: string; resolving?: boolean }>();
  const [jumpRequest, setJumpRequest] = useState<{ messageId: string; requestId: number }>();
  const [timelineFollow, setTimelineFollow] = useState({ following: true, unseenUpdates: 0 });
  const [scrollToLatestRequest, setScrollToLatestRequest] = useState(0);
  const [contextSnapshotState, setContextSnapshotState] = useState<'restoring' | 'partial'>();
  const toolMenuContainerRef = useRef<HTMLDivElement>(null);
  const toolMenuButtonRef = useRef<HTMLButtonElement>(null);
  const toolMenuRef = useRef<HTMLElement>(null);
  const toolMenuInitialFocusRef = useRef<'first' | 'last'>('first');
  const runtimeToolWindow = useMemo(() => createRuntimeToolWindowProjector(), [recordId]);

  useEffect(() => {
    setWorkspaceView('conversation');
    setPanel('none');
    setToolMenuOpen(false);
  }, [recordId]);

  const busy = Boolean(latestActiveTurnId(projection));
  /* A held follow-up is the composer's own queue, not a Runtime delivery.
     干预/接续 hand the message to Pi immediately; a queued draft never leaves
     the client until this turn settles, which is what keeps it editable,
     reorderable, revocable, and restorable when the turn is stopped. */
  const queue = useConversationQueue({
    busy: busy || sending,
    conversationId: recordId,
    send: (text) => { void send('prompt', text); },
  });
  const pendingMemoryReview = latestWaitingActivity(
    projection,
    (activity) => activity.kind === 'user_input_required' && activity.payload.requestKind === 'memory_review',
  );
  const pendingGenericInput = latestWaitingActivity(
    projection,
    (activity) => activity.kind === 'user_input_required' && activity.payload.requestKind !== 'memory_review',
  );
  const pendingApproval = latestWaitingActivity(
    projection,
    (activity) => activity.kind === 'approval_required' && approvalNeedsHumanDecision(activity.payload),
  );
  const imageSupport = selectedModelImageSupport(catalog);

  const loadSnapshot = useCallback(async (quiet = false): Promise<boolean> => {
    if (!quiet) setLoading(true);
    try {
      if (quiet) {
        const value = await transport.request({
          pathId: 'agent.session.snapshot',
          params: { sessionId: recordId },
        });
        useAgentLiveStore.getState().hydrate(recordId, value);
        setContextSnapshotState(undefined);
        setError('');
        return true;
      }
      let recent: unknown;
      try {
        recent = await transport.request({
          pathId: 'agent.session.snapshot',
          params: { sessionId: recordId },
          query: { view: 'recent' },
        });
      } catch {
        recent = undefined;
      }
      if (isRecentAgentSnapshot(recent)) {
        if (recentAgentSnapshotIsPresentable(recent)) {
          useAgentLiveStore.getState().hydrate(recordId, recent);
        }
        setContextSnapshotState('restoring');
        try {
          const full = await transport.request({
            pathId: 'agent.session.snapshot',
            params: { sessionId: recordId },
          });
          useAgentLiveStore.getState().hydrate(recordId, full);
          setContextSnapshotState(undefined);
        } catch (reason) {
          if (!recentAgentSnapshotIsPresentable(recent)) throw reason;
          setContextSnapshotState('partial');
        }
      } else {
        const full = recent ?? await transport.request({
          pathId: 'agent.session.snapshot',
          params: { sessionId: recordId },
        });
        useAgentLiveStore.getState().hydrate(recordId, full);
        setContextSnapshotState(undefined);
      }
      setError('');
      return true;
    } catch (reason) {
      setError(errorText(reason));
      return false;
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [recordId, transport]);

  const loadControlCatalog = useCallback(async () => {
    setToolCatalogStatus('loading');
    const [modelsResult, commandsResult, toolsResult, runtimeResult] = await Promise.allSettled([
      transport.request({ pathId: 'agent.session.models', params: { sessionId: recordId } }),
      transport.request({ pathId: 'agent.session.commands', params: { sessionId: recordId } }),
      transport.request({ pathId: 'agent.tools.list', query: { sessionId: recordId } }),
      transport.request<Record<string, unknown>>({ pathId: 'agent.runtime.get' }),
    ]);
    if (modelsResult.status === 'fulfilled' && isModelCatalog(modelsResult.value)) setCatalog(modelsResult.value);
    if (commandsResult.status === 'fulfilled') setCommands(commandItems(commandsResult.value));
    if (toolsResult.status === 'fulfilled') {
      setTools(toolItems(toolsResult.value));
      try {
        setCapabilityCatalog(requireSessionCapabilityCatalog(toolsResult.value, recordId));
        setCapabilityCatalogError('');
        setToolCatalogStatus('ready');
      } catch (reason) {
        setCapabilityCatalog(undefined);
        setCapabilityCatalogError(errorText(reason));
        setToolCatalogStatus('failed');
      }
    } else {
      setTools([]);
      setCapabilityCatalog(undefined);
      setCapabilityCatalogError(toolsResult.status === 'rejected' ? errorText(toolsResult.reason) : '能力目录不可用。');
      setToolCatalogStatus('failed');
    }
    if (runtimeResult.status === 'fulfilled') {
      const capabilities = asRecord(runtimeResult.value.capabilities);
      setConversationForkAvailable(capabilities.conversationFork === true);
      setConversationRewriteAvailable(capabilities.conversationRewrite === true);
    } else {
      setConversationForkAvailable(false);
      setConversationRewriteAvailable(false);
    }
  }, [recordId, transport]);

  useEffect(() => {
    let active = true;
    let unsubscribe: () => void = () => {};
    useAgentLiveStore.getState().ensure(recordId);
    // Streaming text_delta bursts coalesce into one store commit per batching
    // interval (same contract as the standalone Agent feature). Every
    // non-delta event flushes pending deltas before its own commit, so the
    // visible timeline order never changes — only the per-token React render
    // and layout passes collapse to at most one per frame.
    const batcher = createAgentDeltaBatcher((events) => {
      if (!active) return;
      const needsSnapshot = useAgentLiveStore.getState().applyEvents(recordId, events);
      if (needsSnapshot) void loadSnapshot(true);
    });
    void loadControlCatalog();
    void (async () => {
      const loaded = await loadSnapshot();
      if (!active || !loaded) return;
      unsubscribe = transport.subscribe<UiAgentEvent>(
        {
          pathId: 'agent.session.events',
          params: { sessionId: recordId },
          lastEventId: agentProjection(recordId).resumeToken,
        },
        {
          next: (event) => {
            if (!active) return;
            pulsePawCompositionForRuntimeEvent('agent', event.eventType);
            if (event.eventType === 'snapshot_required') {
              batcher.flush();
              useAgentLiveStore.getState().applyEvents(recordId, [event]);
              void loadSnapshot(true);
              return;
            }
            batcher.push(event);
            const runtimeWindow = runtimeToolWindow(event);
            if (runtimeWindow && shouldAutoOpenRuntimeToolWindow(runtimeWindow)) {
              desktop?.openWindow(runtimeWindow);
            }
            if (event.eventType === 'turn_completed' || event.eventType === 'turn_failed') onSessionActivity?.();
          },
          error: (reason) => {
            if (!active) return;
            setContextSnapshotState('partial');
            setError(errorText(reason));
          },
        },
      );
    })();
    return () => {
      active = false;
      batcher.clear();
      unsubscribe();
    };
  }, [desktop, loadControlCatalog, loadSnapshot, onSessionActivity, recordId, runtimeToolWindow, transport]);

  async function send(delivery: AgentMessageDelivery, rawDraft: string): Promise<void> {
    if (!record || sending || modelChanging) return;
    const value = rawDraft.trim();
    if (editState) {
      if (editState.resolving || !editState.entryId) {
        setError('正在定位这条历史消息，请稍候。');
        return;
      }
      if (!value && !attachments.length) return;
      const message = value || '请查看附件。';
      const selectedAttachments = attachments;
      const target = editState;
      const clientMessageId = `paw-rewrite-${crypto.randomUUID()}`;
      setSending(true);
      setDraft('');
      setAttachments([]);
      setEditState(undefined);
      setError('');
      useAgentLiveStore.getState().rewriteOptimistic(recordId, target.messageId, {
        clientMessageId,
        text: message,
        attachments: selectedAttachments.map((item) => item.id),
        nowMs: Date.now(),
      });
      try {
        await transport.request({
          pathId: 'agent.session.rewrite',
          params: { sessionId: recordId },
          body: {
            entryId: target.entryId,
            message,
            attachments: selectedAttachments.map((item) => item.id),
            clientMessageId,
          },
        });
        await loadSnapshot(true);
      } catch (reason) {
        useAgentLiveStore.getState().discardOptimistic(recordId, clientMessageId);
        await loadSnapshot(true).catch(() => undefined);
        setDraft(value);
        setAttachments(selectedAttachments);
        setEditState(target);
        setError(errorText(reason));
      } finally {
        setSending(false);
      }
      return;
    }
    if (value === '/new') { setDraft(''); onNewWork(); return; }
    if (value === '/branch') { setDraft(''); openForkDialog(); return; }
    if (isCommand(value, '/name')) {
      const title = value.slice('/name'.length).trim().slice(0, 120);
      if (!title) { setError('请在 /name 后输入新的 Session 名称。'); return; }
      setSending(true);
      try {
        const response = await transport.request<Record<string, unknown>>({
          pathId: 'agent.session.rename',
          params: { sessionId: recordId },
          body: { title },
        });
        const updated = asSession(response.session) ?? { ...record, title, updatedAtMs: Date.now() };
        onSessionUpdated(updated);
        setDraft('');
      } catch (reason) { setError(errorText(reason)); }
      finally { setSending(false); }
      return;
    }
    if (isCommand(value, '/compact')) {
      setSending(true);
      try {
        await transport.request({
          pathId: 'agent.session.compact',
          params: { sessionId: recordId },
          body: { instructions: value.slice('/compact'.length).trim() },
        });
        setDraft('');
        await loadSnapshot(true);
      } catch (reason) { setError(errorText(reason)); }
      finally { setSending(false); }
      return;
    }
    if (!value && !attachments.length) return;
    const message = value || '请查看附件。';
    const selectedAttachments = attachments;
    const clientMessageId = `paw-${crypto.randomUUID()}`;
    const effectiveDelivery: AgentMessageDelivery = busy
      ? (delivery === 'followUp' ? 'followUp' : 'steer')
      : 'prompt';
    setSending(true);
    setDraft('');
    setAttachments([]);
    setError('');
    /* Submitting is a claim on the end of the transcript. Without this a reader
       who had scrolled up to check an earlier turn watched their own message
       land off-screen with no sign it was accepted. */
    setScrollToLatestRequest((value) => value + 1);
    useAgentLiveStore.getState().appendOptimistic(recordId, {
      clientMessageId,
      text: message,
      attachments: selectedAttachments.map((item) => item.id),
      nowMs: Date.now(),
      ...(effectiveDelivery === 'prompt'
        ? {}
        : { turnId: latestActiveTurnId(agentProjection(recordId)), delivery: effectiveDelivery }),
    });
    try {
      await transport.request({
        pathId: 'agent.session.prompt',
        params: { sessionId: recordId },
        body: {
          message,
          attachments: selectedAttachments.map((item) => item.id),
          clientMessageId,
          ...(effectiveDelivery === 'prompt' ? {} : { delivery: effectiveDelivery }),
        },
      });
      useAgentLiveStore.getState().acknowledgeOptimistic(recordId, clientMessageId, Date.now());
      await loadSnapshot(true);
    } catch (reason) {
      useAgentLiveStore.getState().failOptimistic(recordId, clientMessageId, errorText(reason), Date.now());
      setDraft(value);
      setAttachments(selectedAttachments);
      setError(errorText(reason));
    } finally {
      setSending(false);
    }
  }

  async function stop(): Promise<void> {
    if (!busy || stopping) return;
    setStopping(true);
    /* Stopping the turn cancels the intent behind everything held for it, so
       the drafts come back to the composer instead of firing into a Session
       the reader just interrupted. */
    if (queue.queue.length) setDraft((current) => queue.restoreToDraft(current));
    try {
      await transport.request({ pathId: 'agent.session.abort', params: { sessionId: recordId }, body: {} });
      await loadSnapshot(true);
      setError('');
    } catch (reason) { setError(errorText(reason)); }
    finally { setStopping(false); }
  }

  function retryTurn(turnId: string, onAdmissionRolledBack?: () => void): boolean {
    if (!record || sending || busy) return false;
    const current = agentProjection(recordId);
    const turn = current.turnsById[turnId];
    const userMessage = turn?.messageIds
      .map((id) => current.messagesById[id])
      .find((message): message is AgentMessageProjection => message?.role === 'user');
    if (!userMessage) {
      setError('找不到这轮的原始输入，无法安全重试。');
      return false;
    }
    if (userMessage.admissionState === 'pending' || userMessage.admissionState === 'unresolved') {
      setError('这条消息仍无法确认是否已执行；为避免重复执行，不能自动重试。请先重新同步 Session。');
      return false;
    }
    const message = userMessage.blocks
      .map((block) => typeof block.data.text === 'string' ? block.data.text : '')
      .filter(Boolean)
      .join('\n')
      .trim();
    if (!message && !userMessage.attachments.length) {
      setError('找不到这轮的原始输入，无法安全重试。');
      return false;
    }
    void replayTurnMessage(userMessage, message || '请查看附件。', onAdmissionRolledBack);
    return true;
  }

  async function replayTurnMessage(
    userMessage: AgentMessageProjection,
    message: string,
    onAdmissionRolledBack?: () => void,
  ): Promise<void> {
    const replayAmbiguousAdmission = userMessage.admissionState === 'ambiguous' && Boolean(userMessage.clientMessageId);
    const clientMessageId = replayAmbiguousAdmission
      ? userMessage.clientMessageId!
      : `paw-retry-${crypto.randomUUID()}`;
    const retryOfClientMessageId = replayAmbiguousAdmission ? '' : userMessage.clientMessageId ?? '';
    setSending(true);
    setError('');
    if (replayAmbiguousAdmission) {
      useAgentLiveStore.getState().requeueOptimistic(recordId, clientMessageId, Date.now());
    } else {
      useAgentLiveStore.getState().appendOptimistic(recordId, {
        clientMessageId,
        ...(retryOfClientMessageId ? { retryOfClientMessageId } : {}),
        text: message,
        attachments: userMessage.attachments,
        nowMs: Date.now(),
      });
    }
    try {
      await transport.request({
        pathId: 'agent.session.prompt',
        params: { sessionId: recordId },
        body: {
          message,
          attachments: userMessage.attachments,
          clientMessageId,
          ...(retryOfClientMessageId ? { retryOfClientMessageId } : {}),
        },
      });
      useAgentLiveStore.getState().acknowledgeOptimistic(recordId, clientMessageId, Date.now());
      await loadSnapshot(true);
    } catch (reason) {
      useAgentLiveStore.getState().failOptimistic(recordId, clientMessageId, errorText(reason), Date.now(), replayAmbiguousAdmission ? 'ambiguous' : undefined);
      onAdmissionRolledBack?.();
      setError(errorText(reason));
    } finally {
      setSending(false);
    }
  }

  function continueTurn(turnId: string): boolean {
    const current = agentProjection(recordId);
    if (current.turnOrder.at(-1) !== turnId || current.turnsById[turnId]?.status !== 'failed') return false;
    void send('prompt', '继续完成上一轮。请基于当前 Session 已保留的工具结果和文件生成最终回复，不要重复已经完成的操作。');
    return true;
  }

  function openForkDialog(initialEntryId = ''): void {
    setForkDialogNodes(conversationNodes(projection));
    setForkDialogInitialEntryId(initialEntryId);
    setForkDialogOpen(true);
  }

  async function beginEditMessage(messageId = ''): Promise<void> {
    if (!record || busy || sending || !conversationRewriteAvailable || record.roomParticipant) {
      setError(record?.roomParticipant
        ? '这段对话属于 Room 伙伴，历史修改由 Room 管理。'
        : conversationRewriteAvailable
          ? '请等待当前回复结束后再修改历史消息。'
          : '当前 Pi Runtime 尚未提供原位修改能力。');
      return;
    }
    const current = agentProjection(recordId);
    const message = messageId
      ? current.messagesById[messageId]
      : [...current.messageOrder].reverse().map((id) => current.messagesById[id])
        .find((item) => item?.role === 'user' && !item.id.startsWith('local:'));
    if (!message || message.role !== 'user' || message.id.startsWith('local:')) {
      setError('当前对话里没有可修改的上一条用户消息。');
      return;
    }
    const text = conversationText(message.blocks);
    if (!text && !message.attachments.length) {
      setError('这条消息没有可编辑的公开内容。');
      return;
    }
    const originalAttachments: ComposerAttachment[] = message.attachments.map((id, index) => ({
      id,
      name: `原附件 ${index + 1}`,
      mimeType: '',
      byteSize: 0,
      source: 'path',
    }));
    setDraft(text);
    setAttachments(originalAttachments);
    setEditState({ entryId: '', messageId: message.id, resolving: true });
    setJumpRequest({ messageId: message.id, requestId: Date.now() });
    setError('');
    try {
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.session.forks.list',
        params: { sessionId: recordId },
      });
      const entryId = resolveConversationEntryId(response, conversationNodes(current), message.id);
      if (!entryId) throw new Error('Pi 没有返回这条公开消息对应的可回溯锚点。');
      setEditState({ entryId, messageId: message.id });
    } catch (reason) {
      setEditState(undefined);
      setDraft('');
      setAttachments([]);
      setError(errorText(reason));
    }
  }

  function cancelEdit(): void {
    setEditState(undefined);
    setDraft('');
    setAttachments([]);
  }

  async function decideApproval(approvalId: string, decision: 'approved' | 'rejected', payloadSha256: string): Promise<void> {
    try {
      await transport.request({
        pathId: 'agent.approval.decide',
        params: { approvalId },
        body: { decision: decision === 'approved' ? 'approve' : 'reject', payloadSha256 },
      });
      setRequestedApproval(undefined);
      await loadSnapshot(true);
    } catch (reason) {
      setError(errorText(reason));
      throw reason;
    }
  }

  async function pickAttachments(): Promise<void> {
    if (!transport.pickFiles) { setError('当前环境不能选择附件。'); return; }
    try {
      const imported = await transport.pickFiles({
        multiple: true,
        purpose: 'attachment',
        sessionId: recordId,
        maxFiles: Math.max(1, 8 - attachments.length),
      });
      setAttachments((current) => mergeAttachments(current, imported.map((item) => ({ ...item, source: 'picker' as const }))));
    } catch (reason) { setError(errorText(reason)); }
  }

  async function pasteFiles(files?: File[]): Promise<void> {
    if (!transport.pasteImages) { setError('当前环境不能导入剪贴板文件。'); return; }
    try {
      const imported = await transport.pasteImages({ sessionId: recordId, ...(files?.length ? { files } : {}), maxFiles: Math.max(1, 8 - attachments.length) });
      // Browser transports echo the pasted bytes back as receipts; reusing the
      // local File gives image chips an instant thumbnail before upload settles.
      setAttachments((current) => mergeAttachments(current, imported.map((item, index) => {
        const file = files?.[index];
        const previewFile = file
          && file.name === item.name
          && file.size === item.byteSize
          && transport.kind !== 'native'
          ? { previewFile: file }
          : {};
        return { ...item, source: 'clipboard' as const, ...previewFile };
      })));
    } catch (reason) { setError(errorText(reason)); }
  }

  async function changePermission(selection: AgentPermissionSelection): Promise<void> {
    if (!record || busy) { setError('请先停止当前回合，再调整运行权限。'); return; }
    try {
      let workspaceRoots = selection.mode === 'coordinator' ? record.workspaceRoots : [];
      if (selection.mode === 'coordinator' && !workspaceRoots.length && transport.pickFiles) {
        const picked = await transport.pickFiles({ purpose: 'workspace-root', selection: 'directory', multiple: true, maxFiles: 4 });
        workspaceRoots = picked.map((item) => item.path).filter((path): path is string => Boolean(path));
      }
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.session.mode.update',
        params: { sessionId: recordId },
        body: {
          mode: selection.mode,
          executionMode: selection.executionMode,
          workspaceRoots,
          toolProfileVersion: selection.toolProfileVersion,
          toolAllowlistMode: 'profile',
          ...(selection.dangerousModeConfirmed ? { dangerousModeConfirmation: 'ENABLE_FULL_TRUST' } : {}),
          ...(selection.workspaceScopeConfirmed ? { workspaceScopeConfirmation: 'APPROVE_WORKSPACE_SCOPE' } : {}),
        },
      });
      const updated = asSession(response.session);
      if (updated) onSessionUpdated(updated);
      await loadControlCatalog();
      setError('');
    } catch (reason) { setError(errorText(reason)); }
  }

  async function manageWorkspaceRoots(): Promise<void> {
    if (!record || !transport.pickFiles) { setError('当前环境不能选择工作区。'); return; }
    try {
      const picked = await transport.pickFiles({ purpose: 'workspace-root', selection: 'directory', multiple: true, maxFiles: 4 });
      const workspaceRoots = picked.map((item) => item.path).filter((path): path is string => Boolean(path));
      if (!workspaceRoots.length) return;
      const executionMode = record.executionMode ?? 'per_action';
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.session.mode.update',
        params: { sessionId: recordId },
        body: {
          mode: 'coordinator',
          executionMode,
          workspaceRoots,
          toolProfileVersion: record.toolProfileVersion ?? 'control-center-v1',
          toolAllowlistMode: 'profile',
          ...(executionMode === 'workspace_managed' ? { workspaceScopeConfirmation: 'APPROVE_WORKSPACE_SCOPE' } : {}),
          ...(executionMode === 'full_trust' ? { dangerousModeConfirmation: 'ENABLE_FULL_TRUST' } : {}),
        },
      });
      const updated = asSession(response.session);
      if (updated) onSessionUpdated(updated);
      await loadControlCatalog();
    } catch (reason) { setError(errorText(reason)); }
  }

  async function changeModel(provider: string, modelId: string, level: ThinkingLevel): Promise<void> {
    setModelChanging(true);
    try {
      await transport.request({ pathId: 'agent.session.model.select', params: { sessionId: recordId }, body: { provider, modelId } });
      await transport.request({ pathId: 'agent.session.thinking.select', params: { sessionId: recordId }, body: { level } });
      const refreshed = await transport.request({ pathId: 'agent.session.models', params: { sessionId: recordId } });
      if (isModelCatalog(refreshed)) setCatalog(refreshed);
      setError('');
    } catch (reason) { setError(errorText(reason)); }
    finally { setModelChanging(false); }
  }

  async function changeCapabilityPreference(canonicalId: string, preference: CapabilityPreference): Promise<void> {
    if (!capabilityCatalog?.sessionPolicy) return;
    setCapabilityMutation({ canonicalId, preference, status: 'pending', message: '正在更新当前 Session 的能力披露。' });
    try {
      await transport.request({
        pathId: 'agent.session.capability-policy.update',
        params: { sessionId: recordId },
        body: {
          capabilityDisclosurePreferences: {
            ...capabilityCatalog.sessionPolicy.disclosurePreferences.session,
            [canonicalId]: preference,
          },
        },
      });
      const response = await transport.request({ pathId: 'agent.tools.list', query: { sessionId: recordId } });
      const next = requireSessionCapabilityCatalog(response, recordId);
      setCapabilityCatalog(next);
      setTools(toolItems(response));
      const updated = next.items.find((item) => item.canonicalId === canonicalId);
      setCapabilityMutation({
        canonicalId,
        preference,
        status: 'succeeded',
        message: `已按${capabilityScopeLabel(updated?.effectiveScope ?? 'session')}范围更新。`,
      });
    } catch (reason) {
      setCapabilityMutation({ canonicalId, preference, status: 'failed', message: errorText(reason) });
    }
  }

  function runProductCommand(command: AgentProductCommandName): void {
    setToolMenuOpen(false);
    if (command === 'new') onNewWork();
    else if (command === 'resume') setPanel('none');
    else if (command === 'branch') openForkDialog();
    else if (command === 'model' || command === 'thinking') setModelPickerRequest((value) => value + 1);
    else if (command === 'permissions') setPermissionPickerRequest((value) => value + 1);
    else if (command === 'tools') setToolPickerRequest((value) => value + 1);
    else if (command === 'status' || command === 'session') setPanel('status');
    else if (command === 'subagents') setPanel('subagents');
    else if (command === 'stop') void stop();
    else if (command === 'settings') openPawOsRoute(desktop, '/configuration');
    else if (command === 'help' || command === 'hotkeys') setHelpRequest((value) => value + 1);
  }

  const closeToolMenu = useCallback((restoreFocus = false): void => {
    if (restoreFocus) toolMenuButtonRef.current?.focus();
    setToolMenuOpen(false);
  }, []);

  const openToolMenu = useCallback((initialFocus: 'first' | 'last' = 'first'): void => {
    toolMenuInitialFocusRef.current = initialFocus;
    setToolMenuOpen(true);
  }, []);

  useEffect(() => {
    if (!toolMenuOpen) return;
    const items = Array.from(toolMenuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? []);
    if (!items.length) return;
    const index = toolMenuInitialFocusRef.current === 'last' ? items.length - 1 : 0;
    items[index]?.focus();
  }, [toolMenuOpen]);

  useEffect(() => {
    if (!toolMenuOpen) return;
    const handlePointerDown = (event: PointerEvent): void => {
      const target = event.target;
      if (!(target instanceof Node) || !toolMenuContainerRef.current?.contains(target)) {
        closeToolMenu(false);
      }
    };
    document.addEventListener('pointerdown', handlePointerDown);
    return () => document.removeEventListener('pointerdown', handlePointerDown);
  }, [closeToolMenu, toolMenuOpen]);

  function moveToolMenuFocus(direction: 'next' | 'previous' | 'first' | 'last'): void {
    const items = Array.from(toolMenuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? []);
    if (!items.length) return;
    const currentIndex = items.indexOf(document.activeElement as HTMLButtonElement);
    const index = direction === 'first'
      ? 0
      : direction === 'last'
        ? items.length - 1
        : direction === 'next'
          ? (currentIndex + 1 + items.length) % items.length
          : (currentIndex - 1 + items.length) % items.length;
    items[index]?.focus();
  }

  function handleToolMenuKeyDown(event: KeyboardEvent<HTMLElement>): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeToolMenu(true);
      return;
    }
    // Let the browser advance to the next focusable control. The menu closes
    // from blur, so Tab never becomes an accidental focus trap.
    if (event.key === 'Tab') return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      moveToolMenuFocus('next');
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      moveToolMenuFocus('previous');
    } else if (event.key === 'Home') {
      event.preventDefault();
      moveToolMenuFocus('first');
    } else if (event.key === 'End') {
      event.preventDefault();
      moveToolMenuFocus('last');
    }
  }

  function handleToolMenuBlur(event: FocusEvent<HTMLElement>): void {
    const nextTarget = event.relatedTarget;
    if (!(nextTarget instanceof Node) || !toolMenuContainerRef.current?.contains(nextTarget)) {
      closeToolMenu(false);
    }
  }

  function handleToolMenuButtonKeyDown(event: KeyboardEvent<HTMLButtonElement>): void {
    if (event.key === 'Escape' && toolMenuOpen) {
      event.preventDefault();
      closeToolMenu(true);
      return;
    }
    if (event.key === 'Tab' && toolMenuOpen) {
      // Do not cancel Tab; closing here lets the browser keep its normal tab
      // order even when Shift+Tab returned focus to the trigger first.
      closeToolMenu(false);
      return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (!toolMenuOpen) {
        openToolMenu(event.key === 'ArrowUp' ? 'last' : 'first');
      } else {
        moveToolMenuFocus(event.key === 'ArrowUp' ? 'previous' : 'next');
      }
    }
  }

  function openToolPanel(next: Exclude<WorkbenchPanel, 'none'>): void {
    setPanel(next);
    closeToolMenu(true);
  }

  const title = record?.title || '未命名 Session';
  /* Conversation lead-in: the two facts a reader needs before the first turn —
     which workspace this Session can touch and under which permission mode.
     Both come from the durable session record, never from prose. */
  /* Each chip leads with its mark so a narrow window can drop the words and
     still say which workspace and which permission mode this Session runs
     under; the text stays in the accessibility tree rather than unmounting. */
  const conversationLead = record ? (
    <div aria-label="Session 上下文" className="fx-context-chips" role="note">
      <span
        className="fx-context-chip"
        data-tone={record.workspaceRoots?.length ? 'bound' : 'neutral'}
        title={record.workspaceRoots?.length ? record.workspaceRoots.join('\n') : '未绑定工作区'}
      >
        <WorkspaceMark bound={Boolean(record.workspaceRoots?.length)} size={14} />
        <span className="fx-context-chip__text">
          {record.workspaceRoots?.length ? `${projectName(record.workspaceRoots)} · 工作区` : '未绑定工作区'}
        </span>
      </span>
      {record.executionMode ? (
        <span
          className="fx-context-chip"
          data-tone="permission"
          title={`权限 · ${executionModeLabel(record.executionMode)}`}
        >
          <PermissionMark mode={record.executionMode} size={14} />
          <span className="fx-context-chip__text">
            权限 · {executionModeLabel(record.executionMode)}
          </span>
        </span>
      ) : null}
    </div>
  ) : undefined;
  const sessionChrome = (
      <div className="paw-session-workspace__header" data-status={stopping ? 'stopping' : busy ? 'busy' : 'idle'}>
        {!windowChromeTarget ? <div className="paw-session-workspace__identity">
          <div>
            <span className="paw-session-workspace__breadcrumb"><small>Agent</small><i>/</i><strong>{title}</strong></span>
            <small>Session · {record?.mode === 'coordinator' ? '协调' : '单聊'}</small>
          </div>
        </div> : null}
        <nav aria-label="当前 Session 视图" className="paw-session-workspace__view-switch">
          <button aria-label="对话" aria-pressed={workspaceView === 'conversation'} onClick={() => { setWorkspaceView('conversation'); setPanel('none'); setToolMenuOpen(false); }} type="button"><MessageSquare size={15} /><span>对话</span></button>
          <button aria-label="Agent 轨迹" aria-pressed={workspaceView === 'trace'} onClick={() => { setWorkspaceView('trace'); setPanel('none'); setToolMenuOpen(false); }} type="button"><GitBranch size={15} /><span>Agent 轨迹</span></button>
          <button aria-label="星空" aria-pressed={workspaceView === 'starfield'} onClick={() => { setWorkspaceView('starfield'); setPanel('none'); setToolMenuOpen(false); }} type="button"><Orbit size={15} /><span>星空</span></button>
        </nav>
        <div className="paw-session-workspace__runtime">
          <span data-context={contextSnapshotState}><i />{stopping
            ? '正在停止'
            : busy
              ? '正在执行'
            : contextSnapshotState === 'restoring'
              ? '正在恢复完整上下文'
              : contextSnapshotState === 'partial'
                ? '仅显示最近上下文'
                : '已同步'}</span>
          {busy ? <button aria-label="停止当前回合" disabled={stopping} onClick={() => void stop()} type="button"><StopCircle size={16} /></button> : null}
        </div>
        <div className="paw-session-workspace__tools" data-open={toolMenuOpen || undefined} ref={toolMenuContainerRef}>
          <button
            aria-controls="paw-session-tools-menu"
            aria-expanded={toolMenuOpen}
            aria-haspopup="menu"
            aria-label="Session 工具"
            onClick={() => { if (toolMenuOpen) closeToolMenu(true); else openToolMenu(); }}
            onKeyDown={handleToolMenuButtonKeyDown}
            ref={toolMenuButtonRef}
            type="button"
          >
            <Wrench size={15} />
            <span>Session 工具</span>
            {pendingApproval || pendingGenericInput || pendingMemoryReview ? <small className="paw-session-workspace__attention">待处理</small> : null}
          </button>
          {toolMenuOpen ? <nav
            aria-label="Session 工具菜单"
            id="paw-session-tools-menu"
            onBlur={handleToolMenuBlur}
            onKeyDown={handleToolMenuKeyDown}
            ref={toolMenuRef}
            role="menu"
          >
            <button data-active={panel === 'status' || undefined} onClick={() => openToolPanel('status')} role="menuitem" type="button"><ListChecks size={15} /><span>任务与状态</span></button>
            <button data-active={panel === 'subagents' || undefined} onClick={() => openToolPanel('subagents')} role="menuitem" type="button"><Network size={15} /><span>子 Agent</span></button>
            <button data-active={panel === 'files' || undefined} onClick={() => openToolPanel('files')} role="menuitem" type="button"><FolderTree size={15} /><span>文件</span></button>
          </nav> : null}
        </div>
      </div>
  );
  return (
    <>
      {windowChromeTarget ? <PawWindowChromePortal>{sessionChrome}</PawWindowChromePortal> : null}
      <section
        className="paw-session-workspace paw-chatfx"
        data-chrome-in-window={windowChromeTarget ? true : undefined}
        data-panel={panel}
        data-status={stopping ? 'stopping' : busy ? 'busy' : 'idle'}
      >
      {windowChromeTarget ? null : sessionChrome}

      <div className="paw-session-workspace__body">
        <div className="paw-session-workspace__primary">
          <div className="paw-session-workspace__viewport">
            <main
              aria-hidden={workspaceView !== 'conversation'}
              className="paw-agent-next paw-session-workspace__conversation paw-chatfx"
              data-active={workspaceView === 'conversation' || undefined}
              data-agent-tree="projection"
              data-message-flow="separated"
              inert={workspaceView !== 'conversation'}
            >
              <div aria-hidden="true" className="agent-fx-fade agent-fx-fade--top" />
              <div aria-hidden="true" className="agent-fx-fade agent-fx-fade--bottom" />
              {loading && !projection?.turnOrder.length ? <div className="paw-session-workspace__loading"><LoaderCircle className="ui-spin" size={18} />正在恢复完整 Session</div> : null}
              <AgentTimeline
                activityPresentation="grouped"
                presentation="fx"
                showConversationNavigation={false}
                sessionId={recordId}
                persona={persona}
                loading={loading}
                modelSelectionAvailable={Boolean(catalog)}
                turnRecoveryDisabled={busy || sending || stopping || modelChanging}
                forkAvailable={conversationForkAvailable && !busy && !sending && !record?.roomParticipant}
                rewriteAvailable={conversationRewriteAvailable && !busy && !sending && !record?.roomParticipant}
                jumpRequest={jumpRequest}
                leadingContent={conversationLead}
                scrollToLatestRequest={scrollToLatestRequest}
                onFollowStateChange={setTimelineFollow}
                onForkFromMessage={openForkDialog}
                onEditMessage={(messageId) => void beginEditMessage(messageId)}
                onRetryTurn={retryTurn}
                onContinueTurn={continueTurn}
                onSwitchModel={() => setModelPickerRequest((value) => value + 1)}
                onApprovalDecision={(id, decision, hash) => void decideApproval(id, decision, hash)}
                onOpenApproval={setRequestedApproval}
                onRequestPermission={() => setPermissionPickerRequest((value) => value + 1)}
              />
            </main>

            <main
              aria-hidden={workspaceView !== 'trace'}
              className="paw-session-workspace__trace"
              data-active={workspaceView === 'trace' || undefined}
              inert={workspaceView !== 'trace'}
            >
              <PawContextTrace
                active={workspaceView === 'trace'}
                projection={projection}
                sessionId={recordId}
              />
            </main>

            <main
              aria-hidden={workspaceView !== 'starfield'}
              className="paw-session-workspace__starfield"
              data-active={workspaceView === 'starfield' || undefined}
              inert={workspaceView !== 'starfield'}
            >
              {/* The sky mounts only while watched: no hidden polling, and the
                  conversation/trace stacked views keep their own state. The
                  component renders an immersive fullscreen overlay; Esc or
                  its exit control returns to the conversation. */}
              {workspaceView === 'starfield' ? <LazyPawSessionStarfield
                active
                busy={busy}
                sessionId={recordId}
                sessionTitle={title}
                onExit={() => setWorkspaceView('conversation')}
                onOpenRun={(run) => desktop?.openWindow({
                  appId: 'agent',
                  target: {
                    kind: 'subagent',
                    id: run.id,
                    sessionId: recordId,
                    title: run.task || '子 Agent',
                    subtitle: `Session · ${record?.title || recordId}`,
                  },
                })}
                onOpenWorkbench={() => setPanel('subagents')}
              /> : null}
            </main>
          </div>

          <div className="paw-session-workspace__composer">
            {error ? <div className="paw-session-workspace__error" role="alert"><CircleAlert size={14} /><span>{error}</span><button onClick={() => { setError(''); void loadSnapshot(); }} type="button">重新同步</button></div> : null}
            {record ? <QueueTray busy={busy || sending} controller={queue} /> : null}
            {pendingGenericInput && !pendingApproval && !pendingMemoryReview ? (
              <GenericUserInputCard activity={pendingGenericInput} sessionId={recordId} onError={setError} />
            ) : record ? (
              <AgentComposer
                attachments={attachments}
                busy={busy}
                capabilityCatalog={capabilityCatalog}
                capabilityPolicyPending={capabilityMutation?.status === 'pending'}
                catalog={catalog}
                commands={commands}
                contextUsage={projection?.telemetry?.context ?? null}
                draft={draft}
                helpRequest={helpRequest}
                imageSupport={imageSupport}
                editState={editState}
                modelChanging={modelChanging}
                modelPickerRequest={modelPickerRequest}
                permissionPickerRequest={permissionPickerRequest}
                persona={persona}
                sending={sending}
                session={record}
                stopping={stopping}
                toolCatalogStatus={toolCatalogStatus}
                toolPickerRequest={toolPickerRequest}
                tools={tools}
                onAttachmentsChange={setAttachments}
                onCapabilityPreferenceChange={(id, preference) => void changeCapabilityPreference(id, preference)}
                onDraftChange={setDraft}
                onCancelEdit={cancelEdit}
                onEditPrevious={() => void beginEditMessage()}
                onModelChange={(provider, modelId, level) => void changeModel(provider, modelId, level)}
                onPasteFromClipboard={() => void pasteFiles()}
                onPasteImages={(files) => void pasteFiles(files)}
                onPickAttachments={() => void pickAttachments()}
                onProductCommand={runProductCommand}
                onSend={(delivery, value) => void send(delivery, value)}
                onStop={() => void stop()}
                showJumpLatest={!timelineFollow.following}
                unseenUpdates={timelineFollow.unseenUpdates}
                onJumpLatest={() => setScrollToLatestRequest((value) => value + 1)}
                onToolSelect={(tool) => setDraft((current) => `${current.trimEnd()}${current.trim() ? '\n' : ''}${toolIntentPrompt(tool.id, tool.displayName)}：`)}
                onPermissionChange={(selection) => void changePermission(selection)}
                onWorkspaceRootsChange={() => void manageWorkspaceRoots()}
                queueDepth={queue.queue.length}
                onQueue={queue.enqueue}
              />
            ) : null}
          </div>
        </div>

        {/* 工具侧栏是一层浮卡：只覆盖在消息流之上，绝不挤压对话列。
            在浮层内按 Esc 关闭并把焦点还给“Session 工具”触发钮。 */}
        {panel !== 'none' ? <aside
          className="paw-session-workspace__side"
          aria-label="Session 工具侧栏"
          data-tool={panel}
          onKeyDown={(event) => {
            if (event.key !== 'Escape') return;
            event.stopPropagation();
            setPanel('none');
            toolMenuButtonRef.current?.focus();
          }}
        >
          {panel === 'files' ? (
            <AgentFilesPanel
              sessionId={recordId}
              workspaceRoots={record?.workspaceRoots ?? []}
              open
              onClose={() => setPanel('none')}
              onManageRoots={() => void manageWorkspaceRoots()}
            />
          ) : panel === 'subagents' ? (
            <SessionSubagentPanel
              sessionId={recordId}
              session={record}
              tools={tools}
              compactEmpty
              open
              onClose={() => setPanel('none')}
              onOpenRun={(run) => desktop?.openWindow({
                appId: 'agent',
                target: {
                  kind: 'subagent',
                  id: run.id,
                  sessionId: recordId,
                  title: run.task || '子 Agent',
                  subtitle: `Session · ${record?.title || recordId}`,
                },
              })}
            />
          ) : (
            <AgentStatusPanel
              sessionId={recordId}
              session={record}
              open
              minimal
              commands={commands}
              tools={tools}
              toolCatalogStatus={toolCatalogStatus}
              capabilityCatalog={capabilityCatalog}
              capabilityCatalogError={capabilityCatalogError}
              capabilityPolicyMutation={capabilityMutation}
              contextSnapshotState={contextSnapshotState}
              busy={busy}
              onCapabilityPreferenceChange={(id, preference) => void changeCapabilityPreference(id, preference)}
              onCapabilityPolicyRetry={() => capabilityMutation && void changeCapabilityPreference(capabilityMutation.canonicalId, capabilityMutation.preference)}
              onCapabilityCatalogRetry={() => void loadControlCatalog()}
              onOpenBackgroundJob={(job) => desktop?.openWindow(backgroundJobWindowRequest(job))}
              onClose={() => setPanel('none')}
            />
          )}
        </aside> : null}
      </div>

      <MemoryReviewDialog activity={pendingApproval ? undefined : pendingMemoryReview} sessionId={recordId} onError={setError} />
      <ApprovalReviewDialog activity={pendingApproval ?? requestedApproval} onDecision={decideApproval} />
      <ConversationForkDialog
        assistantName={persona?.displayName ?? 'Agent'}
        open={forkDialogOpen}
        sessionId={recordId}
        sessionTitle={title}
        nodes={forkDialogNodes}
        initialEntryId={forkDialogInitialEntryId}
        branchAvailable={conversationForkAvailable && !record?.roomParticipant}
        branchBlocked={busy || sending}
        branchUnavailableReason={record?.roomParticipant ? '这段对话属于 Room 伙伴，历史分支由 Room 管理。' : undefined}
        onOpenChange={setForkDialogOpen}
        onJump={(messageId) => setJumpRequest({ messageId, requestId: Date.now() })}
        onCreated={onSessionCreated}
      />
      </section>
    </>
  );
}

function conversationNodes(projection?: AgentProjectionState): ConversationNode[] {
  if (!projection) return [];
  return projection.messageOrder
    .map((messageId) => projection.messagesById[messageId])
    .filter((message) => message && (message.role === 'user' || message.role === 'assistant'))
    .map((message) => ({
      entryId: message!.id,
      role: message!.role as ConversationNode['role'],
      text: conversationText(message!.blocks),
      createdAtMs: message!.createdAtMs,
    }))
    .filter((node) => node.text.length > 0);
}

function conversationText(blocks: Array<{ type: string; data: Record<string, unknown> }>): string {
  return blocks.map((block) => {
    const candidates = [block.data.text, block.data.markdown, block.data.code, block.data.message, block.data.summary];
    return candidates.find((item): item is string => typeof item === 'string' && item.trim().length > 0) ?? '';
  }).filter(Boolean).join('\n').replace(/\s+/gu, ' ').trim().slice(0, 480);
}

function latestActiveTurnId(projection?: AgentProjectionState): string {
  if (!projection) return '';
  for (let index = projection.turnOrder.length - 1; index >= 0; index -= 1) {
    const turnId = projection.turnOrder[index] ?? '';
    if (['queued', 'running', 'waiting'].includes(projection.turnsById[turnId]?.status)) return turnId;
  }
  return '';
}

function latestWaitingActivity(
  projection: AgentProjectionState | undefined,
  predicate: (activity: AgentActivityProjection) => boolean,
): AgentActivityProjection | undefined {
  if (!projection) return undefined;
  for (let index = projection.activityOrder.length - 1; index >= 0; index -= 1) {
    const activity = projection.activitiesById[projection.activityOrder[index] ?? ''];
    if (activity?.status === 'waiting' && predicate(activity)) return activity;
  }
  return undefined;
}

function selectedModelImageSupport(catalog?: ModelCatalog): 'supported' | 'unsupported' | 'unknown' {
  if (!catalog) return 'unknown';
  const selected = asRecord(catalog.selected);
  const providerId = typeof selected.provider === 'string' ? selected.provider : '';
  const modelId = typeof selected.id === 'string'
    ? selected.id
    : typeof selected.modelId === 'string'
      ? selected.modelId
      : '';
  const model = catalog.providers.find((provider) => provider.id === providerId)?.models.find((item) => item.id === modelId);
  if (model) return model.supportsImages ? 'supported' : 'unsupported';
  return typeof selected.supportsImages === 'boolean' ? (selected.supportsImages ? 'supported' : 'unsupported') : 'unknown';
}

function mergeAttachments(current: ComposerAttachment[], next: ComposerAttachment[]): ComposerAttachment[] {
  const byId = new Map(current.map((item) => [item.id, item]));
  next.forEach((item) => byId.set(item.id, item));
  return [...byId.values()].slice(0, 8);
}

function asSession(value: unknown): SessionSummary | undefined {
  const item = asRecord(value);
  return typeof item.id === 'string' && typeof item.title === 'string' && typeof item.updatedAtMs === 'number'
    ? item as unknown as SessionSummary
    : undefined;
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isRecentAgentSnapshot(value: unknown): boolean {
  return isRecord(value)
    && value.snapshotScope === 'recent'
    && value.partial === true;
}

function recentAgentSnapshotIsPresentable(value: unknown): boolean {
  if (!isRecord(value)) return false;
  const status = typeof value.status === 'string' ? value.status : '';
  if (status === 'active' || status === 'busy') return true;
  const items = Array.isArray(value.items)
    ? value.items
    : Array.isArray(value.messages)
      ? value.messages
      : [];
  const last = items.at(-1);
  return !(isRecord(last) && last.role === 'user');
}

function isCommand(value: string, command: string): boolean {
  return value === command || value.startsWith(`${command} `);
}

function projectName(roots: readonly string[] | undefined): string {
  const root = roots?.[0] ?? '';
  return root.split('/').filter(Boolean).at(-1) ?? '未绑定项目';
}

function executionModeLabel(mode: string): string {
  if (mode === 'read_only') return '只读';
  if (mode === 'workspace_managed') return '工作区托管';
  if (mode === 'full_trust') return '全自动';
  return '按风险确认';
}

function errorText(reason: unknown): string {
  return publicAgentErrorText(reason, 'Session 操作没有完成，请重新同步后重试。');
}
