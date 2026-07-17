import { AlertCircle, GitBranch, PanelLeftClose, PanelLeftOpen, PanelRightOpen } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useControlTransport } from '@/app/control-transport';
import { IconButton } from '@/components/primitives';
import { createAgentDeltaBatcher } from '@/contracts/batching';
import type { AgentActivityProjection } from '@/contracts/agent-reducer';
import type { UiAgentEvent } from '@/contracts/ui-events';
import { AgentComposer, type AgentComposerEditState, type AgentMessageDelivery } from './composer/AgentComposer';
import { previewAgentEvents, previewAgentSnapshot, previewModelCatalog, previewPersonas, previewSessions } from '@/features/agent/preview-data';
import { SessionRail } from './sessions/SessionRail';
import {
  ConversationForkDialog,
  resolveConversationEntryId,
  type ConversationNode,
} from './sessions/ConversationForkDialog';
import { NewSessionDialog, type NewSessionInput } from './sessions/NewSessionDialog';
import { AgentStatusPanel } from './status/AgentStatusPanel';
import { useMediaQuery, useModalPanel } from './overlay-dialog';
import { agentProjection, useAgentLiveStore } from './state/live-store';
import { AgentTimeline } from './timeline/AgentTimeline';
import { publicAgentErrorText } from './public-error';
import { ApprovalReviewDialog, MemoryReviewDialog } from './review/AgentReviewDialogs';
import {
  activeSessionId,
  commandItems,
  isModelCatalog,
  roleItems,
  sessionPermissionLabel,
  sessionItems,
  toolItems,
  type AgentCommand,
  type AgentPermissionSelection,
  type AgentProductCommandName,
  type ComposerAttachment,
  type ModelCatalog,
  type SessionSummary,
  type ThinkingLevel,
  type ToolManifest,
} from './types';
import './agent.css';

export function AgentFeature() {
  const ready = useDeferredAgentWorkspace();
  if (!ready) {
    const mobileViewport = isMobileViewport();
    return (
      <main
        aria-busy="true"
        aria-label="正在准备 Agent 工作区"
        className="agent-feature agent-feature--pending"
        data-rail-open={!mobileViewport}
        data-route-id="agent"
        data-status-open={!mobileViewport && isWideStatusViewport()}
      >
        <span aria-hidden="true" />
        <span aria-hidden="true" />
        <span aria-hidden="true" />
      </main>
    );
  }
  return <AgentWorkspace />;
}

function AgentWorkspace() {
  const transport = useControlTransport();
  const mobileViewport = useMediaQuery('(max-width: 760px)');
  const statusOverlayViewport = useMediaQuery('(max-width: 1100px)');
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedSessionId = searchParams.get('session')?.trim() ?? '';
  const requestedDraft = searchParams.get('draft')?.trim().slice(0, 4_000) ?? '';
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [personas, setPersonas] = useState(() => __CONTROL_PREVIEW__ && transport.kind === 'mock' ? previewPersonas : []);
  const [selectedId, setSelectedId] = useState('');
  const [catalog, setCatalog] = useState<ModelCatalog>();
  const [commands, setCommands] = useState<AgentCommand[]>([]);
  const [tools, setTools] = useState<ToolManifest[]>([]);
  const [toolCatalogStatus, setToolCatalogStatus] = useState<'loading' | 'ready' | 'failed'>('loading');
  const [conversationForkAvailable, setConversationForkAvailable] = useState(false);
  const [conversationRewriteAvailable, setConversationRewriteAvailable] = useState(false);
  const [editTarget, setEditTarget] = useState<AgentComposerEditState>();
  const [rewriteResolving, setRewriteResolving] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [draft, setDraft] = useState('');
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [modelChanging, setModelChanging] = useState(false);
  const [modelPickerRequest, setModelPickerRequest] = useState(0);
  const [permissionPickerRequest, setPermissionPickerRequest] = useState(0);
  const [toolPickerRequest, setToolPickerRequest] = useState(0);
  const [helpRequest, setHelpRequest] = useState(0);
  const [requestedApproval, setRequestedApproval] = useState<AgentActivityProjection>();
  const [newSessionOpen, setNewSessionOpen] = useState(false);
  const [forkDialogOpen, setForkDialogOpen] = useState(false);
  const [forkDialogInitialEntryId, setForkDialogInitialEntryId] = useState('');
  const [timelineJumpRequest, setTimelineJumpRequest] = useState<{ messageId: string; requestId: number }>();
  const [railOpen, setRailOpen] = useState(() => !isMobileViewport());
  const [statusOpen, setStatusOpen] = useState(() => isWideStatusViewport());
  const [error, setError] = useState('');
  const railToggleRef = useRef<HTMLButtonElement>(null);
  const railRef = useRef<HTMLElement>(null);
  const statusToggleRef = useRef<HTMLButtonElement>(null);
  const statusRef = useRef<HTMLElement>(null);
  const selectedIdRef = useRef(selectedId);
  selectedIdRef.current = selectedId;
  const ensure = useAgentLiveStore((state) => state.ensure);
  const activeTurnId = useAgentLiveStore((state) => {
    const projection = state.projections[selectedId];
    if (!projection) return '';
    // Only the newest visible turn owns the composer stop action. Older
    // streaming flags can survive a reconnect, but must not turn a later
    // failed/completed turn back into a stoppable request.
    for (let index = projection.turnOrder.length - 1; index >= 0; index -= 1) {
      const turnId = projection.turnOrder[index];
      const turn = turnId ? projection.turnsById[turnId] : undefined;
      if (!turn || (turn.messageIds.length === 0 && turn.activityIds.length === 0)) continue;
      return turn.status === 'queued' || turn.status === 'running' || turn.status === 'waiting'
        ? turnId
        : '';
    }
    return '';
  });
  const pendingMemoryReview = useAgentLiveStore((state) => latestWaitingActivity(
    state.projections[selectedId],
    (activity) => activity.kind === 'user_input_required' && activity.payload.requestKind === 'memory_review',
  ));
  const pendingApproval = useAgentLiveStore((state) => latestWaitingActivity(
    state.projections[selectedId],
    (activity) => activity.kind === 'approval_required',
  ));
  const selectedProjection = useAgentLiveStore((state) => state.projections[selectedId]);
  const conversationNodes = useMemo((): ConversationNode[] => {
    const projection = selectedProjection;
    if (!projection) return [];
    return projection.messageOrder
      .map((messageId) => projection.messagesById[messageId])
      .filter((message) => message && (message.role === 'user' || message.role === 'assistant'))
      .map((message) => ({
        entryId: message!.id,
        role: message!.role as ConversationNode['role'],
        text: conversationNodeText(message!.blocks),
        createdAtMs: message!.createdAtMs,
      }))
      .filter((node) => node.text.length > 0);
  }, [selectedProjection]);
  const projectPaths = useMemo(() => sessions
    .flatMap((item) => item.workspaceRoots ?? [])
    .filter((path, index, values) => path.startsWith('/') && values.indexOf(path) === index), [sessions]);
  const approvalForReview = pendingApproval ?? requestedApproval;
  const railModal = mobileViewport && railOpen;
  const statusModal = statusOverlayViewport && statusOpen;
  useModalPanel({
    active: railModal,
    panelRef: railRef,
    returnFocusRef: railToggleRef,
    onClose: closeMobileRail,
    initialFocusSelector: '[data-drawer-autofocus]',
  });
  useModalPanel({
    active: statusModal,
    panelRef: statusRef,
    returnFocusRef: statusToggleRef,
    onClose: closeStatusPanel,
  });

  const loadSessions = useCallback(async (preferredId = '') => {
    setLoading(true);
    try {
      const [sessionResponse, roleResponse] = await Promise.all([
        transport.request({ pathId: 'agent.sessions.list', query: { limit: 100, includeArchived: showArchived } }),
        transport.request({ pathId: 'agent.roles.list' }),
      ]);
      const nextSessions = sessionItems(sessionResponse);
      const nextRoles = roleItems(roleResponse);
      const usableSessions = __CONTROL_PREVIEW__ && transport.kind === 'mock' && nextSessions.length === 0 ? previewSessions : nextSessions;
      setSessions(usableSessions);
      if (nextRoles.length) setPersonas(nextRoles);
      const preferredSessionId = usableSessions.some((item) => item.id === preferredId) ? preferredId : '';
      const backendActiveId = activeSessionId(sessionResponse);
      const activeId = usableSessions.some((item) => item.id === backendActiveId) ? backendActiveId : '';
      const meaningful = (item: SessionSummary): boolean => (
        (item.messageCount ?? 0) > 0 || Boolean(item.lastMessagePreview?.trim())
      );
      const meaningfulId = usableSessions.find(meaningful)?.id ?? '';
      const activeMeaningfulId = usableSessions.find((item) => item.id === activeId && meaningful(item))?.id ?? '';
      setSelectedId((current) => {
        const currentId = usableSessions.some((item) => item.id === current) ? current : '';
        return preferredSessionId || currentId || activeMeaningfulId || meaningfulId || activeId || usableSessions[0]?.id || '';
      });
      setError('');
    } catch (loadError) {
      if (__CONTROL_PREVIEW__ && transport.kind === 'mock') {
        setSessions(previewSessions);
        const preferredSessionId = previewSessions.some((item) => item.id === preferredId) ? preferredId : '';
        setSelectedId((current) => preferredSessionId || current || previewSessions[0]?.id || '');
      } else {
        setError(errorText(loadError));
      }
    } finally {
      setLoading(false);
    }
  }, [showArchived, transport]);

  useEffect(() => { void loadSessions(requestedSessionId); }, [loadSessions, requestedSessionId]);
  useEffect(() => {
    setAttachments([]);
    setCatalog(undefined);
    setCommands([]);
    setConversationForkAvailable(false);
    setConversationRewriteAvailable(false);
    setEditTarget(undefined);
    setForkDialogInitialEntryId('');
    setTimelineJumpRequest(undefined);
  }, [selectedId]);
  useEffect(() => {
    if (!requestedDraft) return;
    setDraft((current) => current.trim() ? current : requestedDraft);
    const next = new URLSearchParams(searchParams);
    next.delete('draft');
    setSearchParams(next, { replace: true });
  }, [requestedDraft, searchParams, setSearchParams]);

  useEffect(() => {
    if (!selectedId) return;
    ensure(selectedId);
    let active = true;
    let unsubscribe = () => {};
    const batcher = createAgentDeltaBatcher((events) => {
      const needsSnapshot = useAgentLiveStore.getState().applyEvents(selectedId, events);
      if (needsSnapshot) void loadSnapshot();
    });
    async function loadSnapshot(): Promise<boolean> {
      try {
        const snapshotResponse = await transport.request({
          pathId: 'agent.session.snapshot',
          params: { sessionId: selectedId },
        });
        if (!active) return false;
        if (__CONTROL_PREVIEW__ && transport.kind === 'mock') {
          useAgentLiveStore.getState().hydrateSnapshot(selectedId, previewAgentSnapshot(selectedId));
          useAgentLiveStore.getState().applyEvents(selectedId, previewAgentEvents(selectedId));
        } else {
          useAgentLiveStore.getState().hydrate(selectedId, snapshotResponse);
        }
        const cursor = agentProjection(selectedId).resumeToken;
        unsubscribe();
        unsubscribe = transport.subscribe<UiAgentEvent>(
          { pathId: 'agent.session.events', params: { sessionId: selectedId }, lastEventId: cursor },
          {
            next: (event) => {
              batcher.push(event);
              if (event.eventType === 'session_configuration_changed') {
                void loadSessionCatalogs();
              }
            },
            error: (streamError) => active && setError(errorText(streamError)),
            snapshotRequired: () => void loadSnapshot(),
          },
        );
        return true;
      } catch (loadError) {
        if (active) setError(`对话记录暂时无法恢复。${errorText(loadError)}`);
        return false;
      }
    }
    async function loadSessionCatalogs(): Promise<void> {
      setToolCatalogStatus('loading');
      const runtimeRequest = transport.request({ pathId: 'agent.runtime.get' });
      void runtimeRequest.then(
        (value) => {
          if (!active) return;
          const runtimePayload = isRecord(value) ? value : {};
          const runtimeCapabilities = isRecord(runtimePayload.capabilities)
            ? runtimePayload.capabilities
            : {};
          setConversationForkAvailable(runtimeCapabilities.conversationFork === true);
          setConversationRewriteAvailable(runtimeCapabilities.conversationRewrite === true);
        },
        () => {
          if (active) {
            setConversationForkAvailable(false);
            setConversationRewriteAvailable(false);
          }
        },
      );
      const [modelResult, commandResult, toolResult] = await Promise.allSettled([
        transport.request({ pathId: 'agent.session.models', params: { sessionId: selectedId } }),
        transport.request({ pathId: 'agent.session.commands', params: { sessionId: selectedId } }),
        transport.request({ pathId: 'agent.tools.list', query: { sessionId: selectedId } }),
        runtimeRequest,
      ]);
      if (!active) return;
      const notices: string[] = [];
      if (modelResult.status === 'fulfilled' && isModelCatalog(modelResult.value)) {
        setCatalog(modelResult.value);
      } else if (__CONTROL_PREVIEW__ && transport.kind === 'mock') {
        setCatalog(previewModelCatalog(selectedId));
      } else {
        setCatalog(undefined);
        notices.push('模型目录暂时不可用，对话记录仍可查看。');
      }
      if (commandResult.status === 'fulfilled') {
        setCommands(commandItems(commandResult.value));
      } else {
        setCommands([]);
        notices.push('Pi 命令暂时不可用，仍可直接发送消息。');
      }
      if (toolResult.status === 'fulfilled') {
        setTools(toolItems(toolResult.value));
        setToolCatalogStatus('ready');
      } else {
        setTools([]);
        setToolCatalogStatus('failed');
        notices.push('工具目录暂时不可用，模型不会获得工具能力。');
      }
      if (notices.length) setError(notices.join(' '));
    }
    void (async () => {
      if (await loadSnapshot()) await loadSessionCatalogs();
    })();
    return () => { active = false; batcher.clear(); unsubscribe(); };
  }, [ensure, selectedId, transport]);

  const session = sessions.find((item) => item.id === selectedId);
  const defaultPersona = personas.find((item) => item.roleId === 'zhiyou-v1')
    ?? personas.find((item) => item.visualProfile.avatarAssetId.includes('timeline-present'))
    ?? personas[0];
  const persona = personas.find((item) => item.roleId === session?.roleId) ?? defaultPersona;
  const busy = Boolean(activeTurnId);
  const branchBlocked = busy || sending;
  const rewriteBlocked = branchBlocked || rewriteResolving || !conversationRewriteAvailable;
  const imageSupport = useMemo(() => selectedModelImageSupport(catalog), [catalog]);
  useEffect(() => {
    if (!busy) setStopping(false);
  }, [busy]);
  useEffect(() => setStopping(false), [selectedId]);
  function closeMobileRail(): void {
    setRailOpen(false);
  }

  function closeStatusPanel(): void {
    setStatusOpen(false);
  }

  function toggleRail(): void {
    setRailOpen((value) => {
      const next = !value;
      if (next && mobileViewport) setStatusOpen(false);
      return next;
    });
  }

  function toggleStatus(): void {
    setStatusOpen((value) => {
      const next = !value;
      if (next && mobileViewport) setRailOpen(false);
      return next;
    });
  }

  function selectSession(sessionId: string): void {
    setSelectedId(sessionId);
    if (mobileViewport) setRailOpen(false);
  }

  async function archiveSession(sessionId: string, archived: boolean): Promise<void> {
    try {
      await transport.request({
        pathId: 'agent.session.archive',
        params: { sessionId },
        body: { archived },
      });
      await loadSessions(selectedId === sessionId && archived && !showArchived ? '' : selectedId);
      setError('');
    } catch (requestError) {
      setError(errorText(requestError));
    }
  }

  async function deleteSession(sessionId: string): Promise<void> {
    try {
      await transport.request({ pathId: 'agent.session.delete', params: { sessionId } });
      useAgentLiveStore.getState().clear(sessionId);
      await loadSessions(selectedId === sessionId ? '' : selectedId);
      setError('');
    } catch (requestError) {
      setError(errorText(requestError));
    }
  }

  async function createSession(input: NewSessionInput): Promise<boolean> {
    const creationPersona = defaultPersona;
    if (!creationPersona) {
      setError('角色目录尚未加载，暂时不能创建对话。');
      return false;
    }
    try {
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.sessions.create',
        body: { title: input.title, mode: 'coordinator', roleId: creationPersona.roleId, roleVersion: creationPersona.version, toolProfileVersion: creationPersona.defaults.toolProfileVersion, workspaceRoots: input.workspaceRoots },
      });
      const created = isRecord(response.session) ? response.session as unknown as SessionSummary : undefined;
      if (created?.id) await loadSessions(created.id);
      else if (__CONTROL_PREVIEW__ && transport.kind === 'mock') {
        const mockSession = { ...previewSessions[0], id: `session-${Date.now()}`, title: input.title, mode: 'coordinator' as const, workspaceRoots: input.workspaceRoots, updatedAtMs: Date.now(), messageCount: 0, lastMessagePreview: '' };
        setSessions((current) => [mockSession, ...current]);
        setSelectedId(mockSession.id);
      }
      setError('');
      return true;
    } catch (requestError) {
      setError(errorText(requestError));
      return false;
    }
  }

  async function send(requestedDelivery: AgentMessageDelivery = busy ? 'steer' : 'prompt'): Promise<void> {
    if (!session || sending) return;
    const delivery: AgentMessageDelivery = busy
      ? (requestedDelivery === 'followUp' ? 'followUp' : 'steer')
      : 'prompt';
    const value = draft.trim();
    if (editTarget) {
      if (!value && attachments.length === 0) return;
      if (attachments.length && imageSupport !== 'supported') {
        setError(imageSupport === 'unsupported'
          ? '当前模型不支持图片，请移除图片或切换到支持图片的模型。'
          : '尚未确认当前模型的图片能力，请稍后再发送。');
        return;
      }
      const message = value || '请查看附件。';
      const selectedAttachments = attachments;
      const target = editTarget;
      setDraft('');
      setAttachments([]);
      setSending(true);
      setError('');
      try {
        await transport.request({
          pathId: 'agent.session.rewrite',
          params: { sessionId: session.id },
          body: {
            entryId: target.entryId,
            message,
            attachments: selectedAttachments.map((item) => item.id),
            clientMessageId: `web-rewrite-${crypto.randomUUID()}`,
          },
        });
        setEditTarget(undefined);
      } catch (requestError) {
        setDraft(value);
        setAttachments(selectedAttachments);
        setError(errorText(requestError));
      } finally {
        setSending(false);
      }
      return;
    }
    if (value === '/new') { setDraft(''); setNewSessionOpen(true); return; }
    if (value === '/resume') { setDraft(''); setRailOpen(true); return; }
    if (value === '/branch') { setDraft(''); openForkDialog(); return; }
    if (isCommand(value, '/name')) {
      const title = normalizedSessionTitle(commandArgument(value, '/name'));
      if (!title) {
        setError('请在 /name 后输入新的对话名称。');
        return;
      }
      setSending(true);
      try {
        await transport.request({ pathId: 'agent.session.rename', params: { sessionId: session.id }, body: { title } });
        setSessions((current) => current.map((item) => item.id === session.id ? { ...item, title, updatedAtMs: Date.now() } : item));
        setDraft('');
        setError('');
      } catch (requestError) { setError(errorText(requestError)); }
      finally { setSending(false); }
      return;
    }
    if (isCommand(value, '/compact')) {
      setSending(true);
      try { await transport.request({ pathId: 'agent.session.compact', params: { sessionId: session.id }, body: { instructions: commandArgument(value, '/compact') } }); setDraft(''); }
      catch (requestError) { setError(errorText(requestError)); }
      finally { setSending(false); }
      return;
    }
    if (value === '/model' || value === '/thinking') { setDraft(''); openModelPicker(); return; }
    if (value === '/permissions') { setDraft(''); setPermissionPickerRequest((current) => current + 1); return; }
    if (value === '/tools') { setDraft(''); openToolPicker(); return; }
    if (value === '/status' || value === '/session') { setDraft(''); setStatusOpen(true); return; }
    if (value === '/settings') { setDraft(''); window.location.hash = '/configuration'; return; }
    if (value === '/help' || value === '/hotkeys') { setDraft(''); setHelpRequest((current) => current + 1); return; }
    if (value === '/stop') { setDraft(''); await stop(); return; }
    if (!value && attachments.length === 0) return;
    if (value.startsWith('/') && !isAdvertisedPiCommand(value, commands)) {
      setError('这个命令不在当前对话的控制中心或 Pi RPC 命令目录中，未发送给模型。');
      return;
    }
    if (attachments.length && imageSupport !== 'supported') {
      setError(imageSupport === 'unsupported'
        ? '当前模型不支持图片，请移除图片或切换到支持图片的模型。'
        : '尚未确认当前模型的图片能力，请稍后再发送。');
      return;
    }
    const message = value || '请查看附件。';
    const selectedAttachments = attachments;
    setDraft(''); setAttachments([]); setError('');
    await promptSession(session.id, message, selectedAttachments.map((item) => item.id), delivery, () => {
      setDraft(value);
      setAttachments(selectedAttachments);
    });
  }

  async function promptSession(
    sessionId: string,
    message: string,
    attachmentIds: string[],
    delivery: AgentMessageDelivery = 'prompt',
    restoreInput?: () => void,
  ): Promise<void> {
    const clientMessageId = `web-${crypto.randomUUID()}`;
    useAgentLiveStore.getState().appendOptimistic(sessionId, {
      clientMessageId,
      text: message,
      attachments: attachmentIds,
      nowMs: Date.now(),
      ...(delivery === 'prompt' ? {} : { turnId: activeTurnId, delivery }),
    });
    setSending(true);
    setError('');
    try {
      await transport.request({
        pathId: 'agent.session.prompt',
        params: { sessionId },
        body: { message, attachments: attachmentIds, clientMessageId, delivery },
      });
    } catch (requestError) {
      const failure = publicAgentErrorText(requestError);
      const projection = agentProjection(sessionId);
      const hasOptimisticTurn = Boolean(projection.optimisticByClientMessageId[clientMessageId]);
      useAgentLiveStore.getState().failOptimistic(sessionId, clientMessageId, failure, Date.now());
      restoreInput?.();
      setError(hasOptimisticTurn ? '' : failure);
    } finally {
      setSending(false);
    }
  }

  async function retryTurn(turnId: string): Promise<void> {
    if (!session || sending) return;
    const projection = agentProjection(session.id);
    const turn = projection.turnsById[turnId];
    const userMessage = turn?.messageIds
      .map((messageId) => projection.messagesById[messageId])
      .find((message) => message?.role === 'user');
    const message = userMessage?.blocks
      .map((block) => typeof block.data.text === 'string' ? block.data.text : '')
      .filter(Boolean)
      .join('\n')
      .trim() ?? '';
    if (!message && !userMessage?.attachments.length) {
      setError('找不到这轮的原始输入，无法安全重试。');
      return;
    }
    await promptSession(session.id, message || '请查看附件。', userMessage?.attachments ?? []);
  }

  function openModelPicker(): void {
    if (!catalog) {
      setError('模型目录暂时不可用，无法切换模型。');
      return;
    }
    setModelPickerRequest((current) => current + 1);
  }

  function openToolPicker(): void {
    if (toolCatalogStatus !== 'ready') {
      setError('工具目录暂时不可用。');
      return;
    }
    const hasAvailableTool = tools.some((tool) => (
      tool.availability === 'online'
      && session
      && tool.sessionModes.includes(session.mode)
      && tool.enabled !== false
    ));
    if (!hasAvailableTool) {
      setError('当前权限模式没有可用工具。');
      return;
    }
    setToolPickerRequest((current) => current + 1);
  }

  function runProductCommand(command: AgentProductCommandName): void {
    if ((busy || sending) && command !== 'resume' && command !== 'session' && command !== 'status' && command !== 'stop') return;
    switch (command) {
      case 'new':
        setDraft('');
        setNewSessionOpen(true);
        break;
      case 'resume':
        setDraft('');
        setRailOpen(true);
        break;
      case 'branch':
        setDraft('');
        openForkDialog();
        break;
      case 'model':
      case 'thinking':
        openModelPicker();
        break;
      case 'tools':
        openToolPicker();
        break;
      case 'permissions':
        setPermissionPickerRequest((current) => current + 1);
        break;
      case 'session':
      case 'status':
        setStatusOpen(true);
        break;
      case 'settings':
        setDraft('');
        window.location.hash = '/configuration';
        break;
      case 'stop':
        if (busy) void stop();
        break;
      case 'help':
      case 'hotkeys':
        setHelpRequest((current) => current + 1);
        break;
      case 'name':
      case 'compact':
        // These commands are inserted into the composer so their optional or
        // required argument stays editable before the API call.
        break;
    }
  }

  function openForkDialog(initialEntryId = ''): void {
    if (!session) return;
    setForkDialogInitialEntryId(initialEntryId);
    setForkDialogOpen(true);
  }

  async function beginEditMessage(messageId = ''): Promise<void> {
    if (!session || rewriteBlocked) {
      setError(conversationRewriteAvailable
        ? '请等待当前回复结束后再修改历史消息。'
        : '当前 Pi Runtime 尚未提供原位修改能力。');
      return;
    }
    const projection = agentProjection(session.id);
    const message = messageId
      ? projection.messagesById[messageId]
      : [...projection.messageOrder]
        .reverse()
        .map((id) => projection.messagesById[id])
        .find((item) => item?.role === 'user' && !item.id.startsWith('local:'));
    if (!message || message.role !== 'user' || message.id.startsWith('local:')) {
      setError('当前对话里没有可修改的上一条用户消息。');
      return;
    }
    const text = message.blocks
      .map((block) => typeof block.data.text === 'string' ? block.data.text : '')
      .filter(Boolean)
      .join('\n')
      .trim();
    if (!text && message.attachments.length === 0) {
      setError('这条消息没有可编辑的公开内容。');
      return;
    }
    setRewriteResolving(true);
    try {
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.session.forks.list',
        params: { sessionId: session.id },
      });
      if (selectedIdRef.current !== session.id) return;
      const entryId = resolveConversationEntryId(response, conversationNodes, message.id);
      if (!entryId) throw new Error('Pi 没有返回这条公开消息对应的可回溯锚点。');
      setEditTarget({ entryId, messageId: message.id });
      setDraft(text);
      setAttachments(message.attachments.map((id, index) => ({
        id,
        name: `原附件 ${index + 1}`,
        mimeType: '',
        byteSize: 0,
        source: 'path',
      })));
      setError('');
    } catch (requestError) {
      setError(publicAgentErrorText(requestError, '暂时无法定位这条历史消息。'));
    } finally {
      setRewriteResolving(false);
    }
  }

  function cancelEdit(): void {
    setEditTarget(undefined);
    setDraft('');
    setAttachments([]);
  }

  function jumpToMessage(messageId: string): void {
    setTimelineJumpRequest({ messageId, requestId: Date.now() });
  }

  async function acceptFork(created: SessionSummary, selectedText: string): Promise<void> {
    setSessions((current) => [created, ...current.filter((item) => item.id !== created.id)]);
    setSelectedId(created.id);
    setDraft(selectedText);
    setAttachments([]);
    setError('');
    if (mobileViewport) setRailOpen(false);
  }

  async function stop(): Promise<void> {
    if (!session || stopping) return;
    setStopping(true);
    try {
      await transport.request({ pathId: 'agent.session.abort', params: { sessionId: session.id } });
      // Abort acknowledgement only means Pi accepted the request. Reconcile
      // once with the authoritative Session row so a stale client-side busy
      // marker can recover; a genuinely active turn remains locked until its
      // terminal SSE event arrives.
      const snapshot = await transport.request({
        pathId: 'agent.session.snapshot',
        params: { sessionId: session.id },
      });
      useAgentLiveStore.getState().hydrate(session.id, snapshot);
      setError('');
    } catch (requestError) {
      setStopping(false);
      setError(errorText(requestError));
    }
  }

  async function pasteImages(files?: File[]): Promise<void> {
    if (!session) { setError('请先选择一个对话。'); return; }
    if (imageSupport !== 'supported') {
      setError(imageSupport === 'unsupported' ? '当前模型不支持图片，请先切换模型。' : '正在确认当前模型的图片能力。');
      return;
    }
    if (!transport.pasteImages) { setError('当前平台暂不支持从剪贴板导入图片。'); return; }
    const remaining = 8 - attachments.length;
    if (remaining <= 0) { setError('单次消息最多支持 8 张图片。'); return; }
    if (files && files.length > remaining) { setError(`当前消息还可以粘贴 ${remaining} 张图片。`); return; }
    const unsupported = files?.find((file) => !PASTED_IMAGE_MIME_TYPES.has(file.type.toLowerCase()));
    if (unsupported) { setError(`不支持粘贴 ${unsupported.type || unsupported.name}；仅支持 PNG、JPEG、GIF 和 WebP。`); return; }
    const oversized = files?.find((file) => file.size <= 0 || file.size > MAX_AGENT_IMAGE_BYTES);
    if (oversized) { setError(`${oversized.name || '图片'} 必须小于 20 MiB 且不能为空。`); return; }
    try {
      const maxFiles = files?.length || remaining;
      const imported = await transport.pasteImages({
        sessionId: session.id,
        ...(files?.length ? { files } : {}),
        maxFiles,
      });
      if (selectedIdRef.current !== session.id) {
        setError('对话已切换，刚粘贴的图片未加入当前消息。');
        return;
      }
      if (!imported.length) {
        setError('剪贴板里没有可导入的 PNG、JPEG、GIF 或 WebP 图片。');
        return;
      }
      mergeAttachments(imported, 'clipboard');
      setError('');
    } catch (pasteError) { setError(errorText(pasteError)); }
  }

  async function pickAttachments(): Promise<void> {
    if (!session) { setError('请先选择一个对话。'); return; }
    if (imageSupport !== 'supported') {
      setError(imageSupport === 'unsupported' ? '当前模型不支持图片，请先切换模型。' : '正在确认当前模型的图片能力。');
      return;
    }
    if (!transport.pickFiles) { setError('当前平台暂不支持选择图片。'); return; }
    const remaining = 8 - attachments.length;
    if (remaining <= 0) { setError('单次消息最多支持 8 张图片。'); return; }
    try {
      const imported = await transport.pickFiles({
        accepts: [...PASTED_IMAGE_MIME_TYPES],
        multiple: true,
        purpose: 'attachment',
        sessionId: session.id,
        maxFiles: remaining,
      });
      if (selectedIdRef.current !== session.id) {
        setError('对话已切换，刚选择的图片未加入当前消息。');
        return;
      }
      if (!imported.length) return;
      mergeAttachments(imported, 'picker');
      setError('');
    } catch (pickError) { setError(errorText(pickError)); }
  }

  function mergeAttachments(files: Omit<ComposerAttachment, 'source'>[], source: ComposerAttachment['source']): void {
    setAttachments((current) => {
      const byId = new Map(current.map((item) => [item.id, item]));
      for (const file of files) byId.set(file.id, { ...file, source });
      return [...byId.values()].slice(0, 8);
    });
  }

  function chooseTool(tool: ToolManifest): void {
    const intent = `请使用“${tool.displayName}”`;
    setDraft((current) => current.trim() ? `${current.trimEnd()}\n${intent}：` : `${intent}：`);
  }

  async function changePermission(selection: AgentPermissionSelection): Promise<void> {
    if (!session) return;
    const currentProfile = session.toolProfileVersion ?? 'control-center-v1';
    if (
      selection.mode === session.mode
      && selection.toolProfileVersion === currentProfile
      && session.toolAllowlistMode !== 'explicit'
    ) return;
    try {
      let workspaceRoots = selection.mode === 'coordinator' ? session.workspaceRoots : [];
      if (selection.mode === 'coordinator' && workspaceRoots.length === 0) {
        const selectedRoots = await pickWorkspaceRoots();
        if (selectedRoots === null) return;
        workspaceRoots = selectedRoots;
      }
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.session.mode.update',
        params: { sessionId: session.id },
        body: {
          mode: selection.mode,
          workspaceRoots,
          toolProfileVersion: selection.toolProfileVersion,
          toolAllowlistMode: 'profile',
          ...(selection.dangerousModeConfirmed
            ? { dangerousModeConfirmation: 'AUTO_APPROVE_ALL' }
            : {}),
        },
      });
      const updated = isRecord(response.session)
        ? response.session as unknown as SessionSummary
        : {
          ...session,
          mode: selection.mode,
          toolProfileVersion: selection.toolProfileVersion,
          toolAllowlistMode: 'profile' as const,
          allowedTools: [],
          workspaceRoots,
        };
      setSessions((current) => current.map((item) => item.id === session.id ? updated : item));
      setToolCatalogStatus('loading');
      try {
        const toolResponse = await transport.request({ pathId: 'agent.tools.list', query: { sessionId: session.id } });
        setTools(toolItems(toolResponse));
        setToolCatalogStatus('ready');
        setError('');
      } catch (catalogError) {
        setTools([]);
        setToolCatalogStatus('failed');
        setError(`权限已更新，但工具目录刷新失败。${errorText(catalogError)}`);
      }
    } catch (requestError) { setError(errorText(requestError)); }
  }

  async function pickWorkspaceRoots(single = false): Promise<string[] | null> {
    if (!transport.pickFiles) {
      setError('当前平台不能选择本地工作区；请在桌面控制中心中配置运行协调权限。');
      return null;
    }
    try {
      const picked = await transport.pickFiles({
        purpose: 'workspace-root',
        selection: 'directory',
        multiple: !single,
        maxFiles: single ? 1 : 4,
      });
      const roots = picked
        .map((item) => item.path?.trim() ?? '')
        .filter((path, index, values) => path.startsWith('/') && values.indexOf(path) === index);
      if (!roots.length) return null;
      return roots;
    } catch (pickError) {
      setError(`工作区选择失败。${errorText(pickError)}`);
      return null;
    }
  }

  async function manageWorkspaceRoots(): Promise<void> {
    if (!session || session.mode !== 'coordinator') return;
    const workspaceRoots = await pickWorkspaceRoots();
    if (workspaceRoots === null) return;
    try {
      const explicit = session.toolAllowlistMode === 'explicit';
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.session.mode.update',
        params: { sessionId: session.id },
        body: {
          mode: session.mode,
          workspaceRoots,
          toolProfileVersion: session.toolProfileVersion ?? 'control-center-v1',
          toolAllowlistMode: explicit ? 'explicit' : 'profile',
          ...(explicit ? { allowedTools: session.allowedTools ?? [] } : {}),
        },
      });
      const updated = isRecord(response.session)
        ? response.session as unknown as SessionSummary
        : { ...session, workspaceRoots };
      setSessions((current) => current.map((item) => item.id === session.id ? updated : item));
      const toolResponse = await transport.request({ pathId: 'agent.tools.list', query: { sessionId: session.id } });
      setTools(toolItems(toolResponse));
      setToolCatalogStatus('ready');
      setError('');
    } catch (requestError) {
      setError(`工作区权限没有更新。${errorText(requestError)}`);
    }
  }

  async function changeModel(provider: string, modelId: string, level: ThinkingLevel): Promise<void> {
    if (!session || !catalog) return;
    const targetModel = catalog.providers.find((item) => item.id === provider)?.models.find((item) => item.id === modelId);
    if (!targetModel) { setError('Pi 模型目录中没有这个模型。'); return; }
    if (attachments.length && !targetModel.supportsImages) {
      setError('当前消息含有图片，请先移除图片再切换到不支持图片的模型。');
      return;
    }
    const selected = isRecord(catalog.selected) ? catalog.selected : {};
    const selectedModelId = typeof selected.id === 'string' && selected.id
      ? selected.id
      : selected.modelId;
    const modelChanged = selected.provider !== provider || selectedModelId !== modelId;
    const thinkingChanged = catalog.thinkingLevel !== level;
    if (!modelChanged && !thinkingChanged) return;
    setModelChanging(true);
    try {
      if (modelChanged) {
        const response = await transport.request<Record<string, unknown>>({ pathId: 'agent.session.model.select', params: { sessionId: session.id }, body: { provider, modelId } });
        if (isRecord(response.session)) {
          const updated = response.session as unknown as SessionSummary;
          setSessions((current) => current.map((item) => item.id === session.id ? updated : item));
        }
      }
      if (modelChanged || thinkingChanged) await transport.request({ pathId: 'agent.session.thinking.select', params: { sessionId: session.id }, body: { level } });
      const refreshed = await transport.request({ pathId: 'agent.session.models', params: { sessionId: session.id } });
      if (!isModelCatalog(refreshed)) throw new Error('Pi 没有返回有效的模型目录。');
      setCatalog(refreshed);
      setError('');
    } catch (requestError) {
      setError(errorText(requestError));
      try {
        const refreshed = await transport.request({ pathId: 'agent.session.models', params: { sessionId: session.id } });
        if (isModelCatalog(refreshed)) setCatalog(refreshed);
      } catch {
        // Keep the last confirmed Pi catalog when recovery also fails.
      }
    } finally {
      setModelChanging(false);
    }
  }

  async function decideApproval(approvalId: string, decision: 'approved' | 'rejected', payloadSha256: string): Promise<void> {
    try {
      await transport.request({
        pathId: 'agent.approval.decide',
        params: { approvalId },
        body: { decision: decision === 'approved' ? 'approve' : 'reject', payloadSha256 },
      });
      setRequestedApproval(undefined);
      setError('');
    }
    catch (requestError) {
      setError(errorText(requestError));
      throw requestError;
    }
  }

  return (
    <main className="agent-feature" data-route-id="agent" data-rail-open={railOpen} data-status-open={statusOpen}>
      <SessionRail ref={railRef} sessions={sessions} selectedId={selectedId} loading={loading} open={railOpen} modal={railModal} blocked={statusModal || newSessionOpen} showArchived={showArchived} onSelect={selectSession} onCreate={() => setNewSessionOpen(true)} onShowArchivedChange={setShowArchived} onArchive={(sessionId, archived) => void archiveSession(sessionId, archived)} onDelete={(sessionId) => void deleteSession(sessionId)} onClose={closeMobileRail} />
      <button className="agent-rail-backdrop" aria-hidden="true" disabled={!railModal} tabIndex={-1} onClick={closeMobileRail} type="button" />
      <section className="agent-conversation" aria-hidden={railModal || statusModal || undefined} inert={railModal || statusModal ? true : undefined}>
        <header className="agent-conversation__header">
          <IconButton ref={railToggleRef} className="agent-rail-toggle" label={railOpen ? '收起任务列表' : '展开任务列表'} icon={railOpen ? <PanelLeftClose size={17} /> : <PanelLeftOpen size={17} />} onClick={toggleRail} tooltip />
          <span><strong>{session?.title ?? '智鼬'}</strong><small>{session ? `${sessionProjectName(session)} · 本地 · ${sessionPermissionLabel(session)}` : '选择一个任务'}</small></span>
          {error ? <p role="alert" title={error}><AlertCircle size={14} /><span>{error}</span></p> : null}
          <div className="agent-conversation__actions">
            <IconButton label="查看对话路径与分支" icon={<GitBranch size={17} />} onClick={() => openForkDialog()} disabled={!session} tooltip />
            <IconButton ref={statusToggleRef} className="agent-status-toggle" label={statusOpen ? '收起状态面板' : '展开状态面板'} icon={<PanelRightOpen size={17} />} onClick={toggleStatus} tooltip />
          </div>
        </header>
        {selectedId ? <AgentTimeline sessionId={selectedId} persona={persona} modelSelectionAvailable={Boolean(catalog)} forkAvailable={conversationForkAvailable && !branchBlocked} rewriteAvailable={!rewriteBlocked} jumpRequest={timelineJumpRequest} onForkFromMessage={openForkDialog} onEditMessage={(messageId) => void beginEditMessage(messageId)} onSuggestion={setDraft} onRetryTurn={(turnId) => void retryTurn(turnId)} onSwitchModel={openModelPicker} onApprovalDecision={(id, decision, hash) => { void decideApproval(id, decision, hash).catch(() => {}); }} onOpenApproval={setRequestedApproval} onRequestPermission={() => setPermissionPickerRequest((current) => current + 1)} /> : null}
        {session ? (
          <AgentComposer draft={draft} attachments={attachments} session={session} persona={persona} catalog={catalog} commands={commands} tools={tools} toolCatalogStatus={toolCatalogStatus} busy={busy} stopping={stopping} sending={sending || modelChanging || rewriteResolving} editState={editTarget} modelPickerRequest={modelPickerRequest} permissionPickerRequest={permissionPickerRequest} toolPickerRequest={toolPickerRequest} helpRequest={helpRequest} imageSupport={imageSupport} onDraftChange={setDraft} onAttachmentsChange={setAttachments} onPickAttachments={() => void pickAttachments()} onPasteFromClipboard={() => void pasteImages()} onPasteImages={(files) => void pasteImages(files)} onToolSelect={chooseTool} onProductCommand={runProductCommand} onSend={(delivery) => void send(delivery)} onStop={() => void stop()} onEditPrevious={() => void beginEditMessage()} onCancelEdit={cancelEdit} onPermissionChange={(selection) => void changePermission(selection)} onWorkspaceRootsChange={() => void manageWorkspaceRoots()} onModelChange={(provider, modelId, level) => void changeModel(provider, modelId, level)} />
        ) : <AgentComposerPending />}
      </section>
      <button className="agent-status-backdrop" aria-hidden="true" disabled={!statusModal} tabIndex={-1} onClick={closeStatusPanel} type="button" />
      <AgentStatusPanel ref={statusRef} sessionId={selectedId} open={statusOpen} modal={statusModal} onClose={closeStatusPanel} />
      <MemoryReviewDialog activity={pendingApproval ? undefined : pendingMemoryReview} sessionId={selectedId} onError={setError} />
      <ApprovalReviewDialog activity={approvalForReview} onDecision={decideApproval} />
      <NewSessionDialog
        open={newSessionOpen}
        projects={projectPaths}
        defaultRoots={session?.workspaceRoots?.length ? session.workspaceRoots : projectPaths.slice(0, 1)}
        onOpenChange={setNewSessionOpen}
        onPickRoots={() => pickWorkspaceRoots(true)}
        onCreate={createSession}
      />
      <ConversationForkDialog
        open={forkDialogOpen}
        sessionId={session?.id ?? ''}
        sessionTitle={session?.title ?? '新对话'}
        nodes={conversationNodes}
        initialEntryId={forkDialogInitialEntryId}
        branchAvailable={conversationForkAvailable}
        branchBlocked={branchBlocked}
        onOpenChange={setForkDialogOpen}
        onJump={jumpToMessage}
        onCreated={(created, selectedText) => { void acceptFork(created, selectedText); }}
      />
    </main>
  );
}

function useDeferredAgentWorkspace(): boolean {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let secondFrame = 0;
    const firstFrame = window.requestAnimationFrame(() => {
      secondFrame = window.requestAnimationFrame(() => setReady(true));
    });
    return () => {
      window.cancelAnimationFrame(firstFrame);
      if (secondFrame) window.cancelAnimationFrame(secondFrame);
    };
  }, []);
  return ready;
}

function AgentComposerPending() {
  return (
    <div aria-label="正在准备对话" className="agent-composer-wrap" role="status">
      <div className="agent-composer agent-composer--pending">
        <span>正在准备对话</span>
      </div>
    </div>
  );
}

function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value); }
function conversationNodeText(blocks: Array<{ type: string; data: Record<string, unknown> }>): string {
  const value = blocks.map((block) => {
    const candidates = [block.data.text, block.data.markdown, block.data.code, block.data.message, block.data.summary];
    return candidates.find((item): item is string => typeof item === 'string' && item.trim().length > 0) ?? '';
  }).filter(Boolean).join('\n').replace(/\s+/gu, ' ').trim();
  return value.slice(0, 480) || '非文本消息';
}
function sessionProjectName(session: SessionSummary): string {
  const root = session.workspaceRoots?.[0] ?? '';
  return root.split('/').filter(Boolean).at(-1) ?? '未指定项目';
}
function isCommand(value: string, invocation: string): boolean {
  return value === invocation || value.startsWith(`${invocation} `);
}
function commandArgument(value: string, invocation: string): string {
  return value.slice(invocation.length).trim();
}
function normalizedSessionTitle(value: string): string {
  return value.split(/\s+/u).filter(Boolean).join(' ').slice(0, 120);
}
function isAdvertisedPiCommand(value: string, commands: AgentCommand[]): boolean {
  return commands.some((command) => isCommand(value, command.invocation));
}
function errorText(value: unknown): string {
  const message = value instanceof Error ? value.message : String(value);
  if (/invalid route parameter:\s*limit/i.test(message)) return '对话列表暂时无法加载，请刷新后重试。';
  return publicAgentErrorText(value, '操作未完成，请刷新状态后重试。');
}
function isMobileViewport(): boolean { return window.matchMedia?.('(max-width: 760px)').matches === true; }
function isWideStatusViewport(): boolean { return window.matchMedia?.('(min-width: 1180px)').matches === true; }

const PASTED_IMAGE_MIME_TYPES = new Set(['image/png', 'image/jpeg', 'image/gif', 'image/webp']);
const MAX_AGENT_IMAGE_BYTES = 20 * 1024 * 1024;

function latestWaitingActivity(
  projection: ReturnType<typeof agentProjection> | undefined,
  predicate: (activity: ReturnType<typeof agentProjection>['activitiesById'][string]) => boolean,
) {
  if (!projection) return undefined;
  for (let index = projection.activityOrder.length - 1; index >= 0; index -= 1) {
    const activity = projection.activitiesById[projection.activityOrder[index] ?? ''];
    if (activity?.status === 'waiting' && predicate(activity)) return activity;
  }
  return undefined;
}

function selectedModelImageSupport(catalog?: ModelCatalog): 'supported' | 'unsupported' | 'unknown' {
  if (!catalog) return 'unknown';
  const selected = isRecord(catalog.selected) ? catalog.selected : {};
  const providerId = typeof selected.provider === 'string' ? selected.provider : '';
  const modelId = typeof selected.id === 'string' && selected.id
    ? selected.id
    : typeof selected.modelId === 'string'
      ? selected.modelId
      : '';
  const model = catalog.providers.find((provider) => provider.id === providerId)?.models.find((item) => item.id === modelId);
  if (!model && typeof selected.supportsImages === 'boolean') {
    return selected.supportsImages ? 'supported' : 'unsupported';
  }
  if (!model) return 'unknown';
  return model.supportsImages ? 'supported' : 'unsupported';
}
