import { AlertCircle, GitBranch, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useControlTransport } from '@/app/control-transport';
import { useComposerClearance } from '@/components/layout/use-composer-clearance';
import { IconButton } from '@/components/primitives';
import { createAgentDeltaBatcher } from '@/contracts/batching';
import type { AgentActivityProjection, AgentProjectionState } from '@/contracts/agent-reducer';
import type { UiAgentEvent } from '@/contracts/ui-events';
import { approvalNeedsHumanDecision } from '@/contracts/approval-decision';
import { AgentComposer, type AgentComposerEditState, type AgentMessageDelivery } from './composer/AgentComposer';
import { previewAgentEvents, previewAgentSnapshot, previewModelCatalog, previewPersonas, previewSessions } from '@/features/agent/preview-data';
import { AgentPaneResizer } from './layout/AgentPaneResizer';
import { SessionRail } from './sessions/SessionRail';
import { AgentConversationState } from './sessions/AgentConversationState';
import {
  ConversationForkDialog,
  resolveConversationEntryId,
  type ConversationNode,
} from './sessions/ConversationForkDialog';
import { NewSessionDialog, type NewSessionInput } from './sessions/NewSessionDialog';
import { AgentStatusPanel } from './status/AgentStatusPanel';
import { useMediaQuery, useModalPanel } from './overlay-dialog';
import { agentProjection, useAgentLiveStore } from './state/live-store';
import { useContextResourceController } from './state/use-context-resource-controller';
import { useModelSelectionController } from './state/use-model-selection-controller';
import { useSessionComposerInputs } from './state/use-session-composer-inputs';
import { AgentTimeline } from './timeline/AgentTimeline';
import { AgentSendTimingTracker, monotonicNow } from './send-stage-timing';
import { toolIntentPrompt } from './tool-presentation';
import { useProductIdentity } from '@/features/identity/product-identity';
import {
  capabilityScopeLabel,
  requireSessionCapabilityCatalog,
  type CapabilityCatalog,
  type CapabilityMutationOutcome,
  type CapabilityPreference,
} from '@/features/plugins/capability-policy';
import {
  isAgentCommandPending,
  isAgentTurnConflict,
  isAmbiguousAgentPromptFailure,
  isUnresolvedAgentCommandPending,
  publicAgentErrorText,
} from './public-error';
import { ApprovalReviewDialog, GenericUserInputCard, MemoryReviewDialog } from './review/AgentReviewDialogs';
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
  type ModelCatalog,
  type SessionSummary,
  type ThinkingLevel,
  type ToolManifest,
} from './types';
import './agent.css';

export function AgentFeature() {
  return <AgentWorkspace />;
}

type AgentHistoryState = 'loading' | 'ready' | 'failed';

type AgentHistoryPage = {
  hasOlderLiveEvents: boolean;
  olderBeforeEventId: string;
  hasOlderMessages: boolean;
  olderBeforeMessageId: string;
  totalLiveEvents: number;
  totalMessages: number;
};

type AgentHistoryCache = {
  snapshot: Record<string, unknown>;
  liveEvents: unknown[];
  page?: AgentHistoryPage;
};

const AGENT_HISTORY_EVENT_LIMIT = 80;
const AGENT_HISTORY_TURN_LIMIT = 100;

function AgentWorkspace() {
  const transport = useControlTransport();
  const identity = useProductIdentity();
  const mobileViewport = useMediaQuery('(max-width: 760px)');
  const statusOverlayViewport = useMediaQuery('(max-width: 1360px)');
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
  const [capabilityCatalog, setCapabilityCatalog] = useState<CapabilityCatalog>();
  const [capabilityCatalogError, setCapabilityCatalogError] = useState('');
  const [capabilityPolicyMutations, setCapabilityPolicyMutations] = useState<Map<string, CapabilityMutationOutcome>>(() => new Map());
  const [conversationForkAvailable, setConversationForkAvailable] = useState(false);
  const [conversationRewriteAvailable, setConversationRewriteAvailable] = useState(false);
  const [editTarget, setEditTarget] = useState<AgentComposerEditState>();
  const [rewriteResolvingSessionIds, setRewriteResolvingSessionIds] = useState<Set<string>>(() => new Set());
  const [showArchived, setShowArchived] = useState(false);
  const [loading, setLoading] = useState(true);
  const [historyStates, setHistoryStates] = useState<Map<string, AgentHistoryState>>(
    () => new Map(),
  );
  const [historyPages, setHistoryPages] = useState<Map<string, AgentHistoryPage>>(
    () => new Map(),
  );
  const [olderHistoryLoadingIds, setOlderHistoryLoadingIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [sessionLoadError, setSessionLoadError] = useState('');
  const [sendingSessionIds, setSendingSessionIds] = useState<Set<string>>(() => new Set());
  const [stoppingSessionIds, setStoppingSessionIds] = useState<Set<string>>(() => new Set());
  const [modelPickerRequest, setModelPickerRequest] = useState(0);
  const [permissionPickerRequest, setPermissionPickerRequest] = useState(0);
  const [toolPickerRequest, setToolPickerRequest] = useState(0);
  const [helpRequest, setHelpRequest] = useState(0);
  const [requestedApproval, setRequestedApproval] = useState<AgentActivityProjection>();
  const [newSessionOpen, setNewSessionOpen] = useState(false);
  const [forkDialogOpen, setForkDialogOpen] = useState(false);
  const [forkDialogNodes, setForkDialogNodes] = useState<ConversationNode[]>([]);
  const [forkDialogInitialEntryId, setForkDialogInitialEntryId] = useState('');
  const [timelineJumpRequest, setTimelineJumpRequest] = useState<{ messageId: string; requestId: number }>();
  const [timelineAtBottom, setTimelineAtBottom] = useState(true);
  const [scrollToLatestRequest, setScrollToLatestRequest] = useState(0);
  const [railOpen, setRailOpen] = useState(() => !isMobileViewport());
  const [statusOpen, setStatusOpen] = useState(shouldOpenTaskCenterByDefault);
  const [error, setVisibleError] = useState('');
  const [sendTimings] = useState(() => new AgentSendTimingTracker());
  const session = sessions.find((item) => item.id === selectedId);
  const historyState = historyStates.get(selectedId) ?? 'loading';
  const isRoomParticipant = Boolean(session?.roomParticipant);
  const railToggleRef = useRef<HTMLButtonElement>(null);
  const railRef = useRef<HTMLElement>(null);
  const statusToggleRef = useRef<HTMLButtonElement>(null);
  const statusRef = useRef<HTMLElement>(null);
  const conversationRef = useRef<HTMLElement>(null);
  useComposerClearance(conversationRef);
  const selectedIdRef = useRef(selectedId);
  const sessionErrorsRef = useRef(new Map<string, string>());
  const catalogNoticesRef = useRef(new Map<string, Map<string, string>>());
  const sessionSendLocksRef = useRef(new Set<string>());
  const modelCatalogCacheRef = useRef(new Map<string, ModelCatalog>());
  const forkCatalogCacheRef = useRef(new Map<string, Record<string, unknown>>());
  const historyStatesRef = useRef(historyStates);
  const historyCacheRef = useRef(new Map<string, AgentHistoryCache>());
  const olderHistoryLoadingRef = useRef(new Set<string>());
  const rewriteResolveGenerationRef = useRef(0);
  const editTargetSessionIdRef = useRef('');
  selectedIdRef.current = selectedId;
  const {
    draft,
    attachments,
    setSessionDraft,
    setSessionAttachments,
    setSelectedDraft,
    persistSelectedDraft,
    setSelectedAttachments,
    restoreSessionInputIfUntouched,
    mergeSessionAttachments,
    seedSessionInput,
    deleteSessionInput,
  } = useSessionComposerInputs({
    selectedSessionId: selectedId,
    getSelectedSessionId: () => selectedIdRef.current,
  });
  const sending = sendingSessionIds.has(selectedId);
  const modelSelection = useModelSelectionController({
    transport,
    selectedSessionId: selectedId,
    setCatalog,
    updateSession: (updated) => {
      setSessions((current) => current.map((item) => (
        item.id === updated.id
          ? { ...item, ...updated, roomParticipant: updated.roomParticipant ?? item.roomParticipant }
          : item
      )));
    },
    setSessionError,
    errorText,
  });
  const modelChanging = modelSelection.changingSessionIds.has(selectedId);
  const contextResources = useContextResourceController({
    transport,
    updateSession: (updated) => {
      setSessions((current) => current.map((item) => (
        item.id === updated.id
          ? { ...item, ...updated, roomParticipant: updated.roomParticipant ?? item.roomParticipant }
          : item
      )));
    },
    setSessionError,
    errorText,
  });
  const stopping = stoppingSessionIds.has(selectedId);
  const rewriteResolving = rewriteResolvingSessionIds.has(selectedId);
  const contextResourcesChanging = contextResources.changingSessionIds.has(selectedId);
  const capabilityPolicyMutation = capabilityPolicyMutations.get(selectedId);
  const capabilityPolicyPending = capabilityPolicyMutation?.status === 'pending';

  function selectSessionId(sessionId: string): void {
    selectedIdRef.current = sessionId;
    setSelectedId(sessionId);
  }

  const updateSessionHistoryState = useCallback((
    sessionId: string,
    state?: AgentHistoryState,
  ): void => {
    const current = historyStatesRef.current;
    if (current.get(sessionId) === state) return;
    const next = new Map(current);
    if (state) next.set(sessionId, state);
    else next.delete(sessionId);
    historyStatesRef.current = next;
    setHistoryStates(next);
  }, []);

  const loadOlderHistory = useCallback(async (): Promise<void> => {
    const sessionId = selectedIdRef.current;
    const page = historyCacheRef.current.get(sessionId)?.page;
    if (
      !sessionId
      || !page
      || (!page.hasOlderLiveEvents && !page.hasOlderMessages)
      || olderHistoryLoadingRef.current.has(sessionId)
    ) return;
    olderHistoryLoadingRef.current.add(sessionId);
    setOlderHistoryLoadingIds((current) => new Set(current).add(sessionId));
    try {
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.session.snapshot',
        params: { sessionId },
        query: {
          eventLimit: AGENT_HISTORY_EVENT_LIMIT,
          turnLimit: AGENT_HISTORY_TURN_LIMIT,
          ...(page.olderBeforeEventId ? { beforeEventId: page.olderBeforeEventId } : {}),
          ...(page.olderBeforeMessageId ? { beforeMessageId: page.olderBeforeMessageId } : {}),
        },
      });
      const olderSnapshot = isRecord(response) ? response : {};
      const current = historyCacheRef.current.get(sessionId);
      if (!current) return;
      const liveEvents = mergeAgentHistoryEvents(
        arrayField(olderSnapshot, 'liveEvents'),
        current.liveEvents,
      );
      const messages = mergeAgentHistoryMessages(
        snapshotMessages(olderSnapshot),
        snapshotMessages(current.snapshot),
      );
      const combined = {
        ...current.snapshot,
        ...olderSnapshot,
        messages,
        items: messages,
        liveEvents,
      };
      const nextPage = agentHistoryPage(olderSnapshot);
      historyCacheRef.current.set(sessionId, {
        snapshot: combined,
        liveEvents,
        page: nextPage,
      });
      useAgentLiveStore.getState().hydrate(sessionId, combined);
      setHistoryPages((pages) => {
        const next = new Map(pages);
        if (nextPage) next.set(sessionId, nextPage);
        else next.delete(sessionId);
        return next;
      });
    } catch (loadError) {
      setSessionError(
        sessionId,
        `更早的对话记录暂时没有读取出来。${errorText(loadError)}`,
      );
    } finally {
      olderHistoryLoadingRef.current.delete(sessionId);
      setOlderHistoryLoadingIds((current) => {
        const next = new Set(current);
        next.delete(sessionId);
        return next;
      });
    }
  }, [transport]);

  function visibleSessionError(sessionId: string): string {
    const operationError = sessionErrorsRef.current.get(sessionId) ?? '';
    const notices = [
      ...(catalogNoticesRef.current.get(sessionId)?.values() ?? []),
    ].filter(Boolean).join(' ');
    return [operationError, notices].filter(Boolean).join(' ');
  }

  function refreshVisibleSessionError(sessionId: string): void {
    if (selectedIdRef.current === sessionId) {
      setVisibleError(visibleSessionError(sessionId));
    }
  }

  function setSessionError(sessionId: string, value: string): void {
    if (!sessionId) return;
    if (value) sessionErrorsRef.current.set(sessionId, value);
    else sessionErrorsRef.current.delete(sessionId);
    refreshVisibleSessionError(sessionId);
  }

  function setCatalogNotice(sessionId: string, key: string, value = ''): void {
    if (!sessionId) return;
    const notices = new Map(catalogNoticesRef.current.get(sessionId) ?? []);
    if (value) notices.set(key, value);
    else notices.delete(key);
    if (notices.size > 0) catalogNoticesRef.current.set(sessionId, notices);
    else catalogNoticesRef.current.delete(sessionId);
    refreshVisibleSessionError(sessionId);
  }

  function setError(value: string): void {
    const sessionId = selectedIdRef.current;
    if (sessionId) {
      setSessionError(sessionId, value);
      return;
    }
    setVisibleError(value);
  }

  function beginSessionSend(sessionId: string): boolean {
    if (sessionSendLocksRef.current.has(sessionId)) return false;
    sessionSendLocksRef.current.add(sessionId);
    setSendingSessionIds((current) => new Set(current).add(sessionId));
    return true;
  }

  function endSessionSend(sessionId: string): void {
    sessionSendLocksRef.current.delete(sessionId);
    setSendingSessionIds((current) => {
      const next = new Set(current);
      next.delete(sessionId);
      return next;
    });
  }

  function updatePendingSession(
    setter: (value: (current: Set<string>) => Set<string>) => void,
    sessionId: string,
    pending: boolean,
  ): void {
    setter((current) => {
      const next = new Set(current);
      if (pending) next.add(sessionId);
      else next.delete(sessionId);
      return next;
    });
  }

  function setSessionStopping(sessionId: string, pending: boolean): void {
    updatePendingSession(setStoppingSessionIds, sessionId, pending);
  }

  function setSessionRewriteResolving(sessionId: string, pending: boolean): void {
    updatePendingSession(setRewriteResolvingSessionIds, sessionId, pending);
  }

  const ensure = useAgentLiveStore((state) => state.ensure);
  const activeTurnId = useAgentLiveStore((state) => latestActiveTurnId(
    state.projections[selectedId],
  ));
  const pendingMemoryReview = useAgentLiveStore((state) => latestWaitingActivity(
    state.projections[selectedId],
    (activity) => activity.kind === 'user_input_required' && activity.payload.requestKind === 'memory_review',
  ));
  const pendingGenericInput = useAgentLiveStore((state) => latestWaitingActivity(
    state.projections[selectedId],
    (activity) => activity.kind === 'user_input_required' && activity.payload.requestKind !== 'memory_review',
  ));
  const pendingApproval = useAgentLiveStore((state) => latestWaitingActivity(
    state.projections[selectedId],
    (activity) => activity.kind === 'approval_required' && approvalNeedsHumanDecision(activity.payload),
  ));
  const projectPaths = useMemo(() => sessions
    .flatMap((item) => item.workspaceRoots ?? [])
    .filter((path, index, values) => path.startsWith('/') && values.indexOf(path) === index), [sessions]);
  const approvalForReview = pendingApproval ?? requestedApproval;
  const railModal = mobileViewport && railOpen;
  const statusModal = statusOverlayViewport && statusOpen;

  useEffect(() => {
    if (mobileViewport) setRailOpen(false);
  }, [mobileViewport]);

  useEffect(() => {
    if (statusOverlayViewport) setStatusOpen(false);
  }, [statusOverlayViewport]);

  useEffect(() => {
    setTimelineAtBottom(true);
  }, [selectedId]);

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
    setSessionLoadError('');
    try {
      // Session history is the primary page payload. Persona defaults may need
      // Pi Provider discovery, so do not hold the conversation rail behind
      // that independent catalog request.
      const sessionResponse = await transport.request({
        pathId: 'agent.sessions.list',
        query: { limit: 100, includeArchived: showArchived },
      });
      const nextSessions = sessionItems(sessionResponse);
      const usableSessions = __CONTROL_PREVIEW__ && transport.kind === 'mock' && nextSessions.length === 0 ? previewSessions : nextSessions;
      setSessions(usableSessions);
      setSessionLoadError('');
      void transport.request({ pathId: 'agent.roles.list' }).then(
        (roleResponse) => {
          const nextRoles = roleItems(roleResponse);
          if (nextRoles.length) setPersonas(nextRoles);
        },
        () => undefined,
      );
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
        const next = preferredSessionId || currentId || activeMeaningfulId || meaningfulId || activeId || usableSessions[0]?.id || '';
        selectedIdRef.current = next;
        return next;
      });
      setError('');
    } catch (loadError) {
      if (__CONTROL_PREVIEW__ && transport.kind === 'mock') {
        setSessions(previewSessions);
        const preferredSessionId = previewSessions.some((item) => item.id === preferredId) ? preferredId : '';
        setSelectedId((current) => {
          const next = preferredSessionId || current || previewSessions[0]?.id || '';
          selectedIdRef.current = next;
          return next;
        });
        setSessionLoadError('');
      } else {
        setSessionLoadError(errorText(loadError));
      }
    } finally {
      setLoading(false);
    }
  }, [showArchived, transport]);

  useEffect(() => { void loadSessions(requestedSessionId); }, [loadSessions, requestedSessionId]);
  useEffect(() => {
    setVisibleError(visibleSessionError(selectedId));
    // A Session's last Pi-confirmed catalog is safe to render while the
    // background refresh runs. Clearing it here caused a visible dead window
    // every time the user returned to a conversation.
    setCatalog(modelCatalogCacheRef.current.get(selectedId));
    setCommands([]);
    setCapabilityCatalog(undefined);
    setCapabilityCatalogError('');
    setToolCatalogStatus('loading');
    setConversationForkAvailable(false);
    setConversationRewriteAvailable(false);
    if (editTargetSessionIdRef.current !== selectedId) {
      rewriteResolveGenerationRef.current += 1;
      editTargetSessionIdRef.current = '';
      setEditTarget(undefined);
    }
    setRequestedApproval(undefined);
    setForkDialogNodes([]);
    setForkDialogInitialEntryId('');
    setTimelineJumpRequest(undefined);
  }, [selectedId]);
  useEffect(() => {
    if (catalog) modelCatalogCacheRef.current.set(catalog.sessionId, catalog);
  }, [catalog]);
  useEffect(() => {
    if (!requestedDraft || !selectedId) return;
    setSessionDraft(selectedId, (current) => current.trim() ? current : requestedDraft);
    const next = new URLSearchParams(searchParams);
    next.delete('draft');
    setSearchParams(next, { replace: true });
  }, [requestedDraft, searchParams, selectedId, setSearchParams]);

  useEffect(() => {
    if (!selectedId) return;
    ensure(selectedId);
    // A cached, already hydrated transcript remains useful while its stream
    // cursor refreshes. A Session without confirmed history must not be
    // presented as an empty conversation while the snapshot is in flight.
    if (historyStatesRef.current.get(selectedId) !== 'ready') {
      updateSessionHistoryState(selectedId, 'loading');
    }
    let active = true;
    let unsubscribe = () => {};
    let snapshotRequestId = 0;
    let snapshotAbort: AbortController | undefined;
    const batcher = createAgentDeltaBatcher((events) => {
      const historyCache = historyCacheRef.current.get(selectedId);
      if (historyCache) {
        historyCache.liveEvents = mergeAgentHistoryEvents(
          historyCache.liveEvents,
          events.filter((event) => event.eventType !== 'snapshot_required'),
        );
      }
      const needsSnapshot = useAgentLiveStore.getState().applyEvents(selectedId, events);
      if (needsSnapshot) void loadSnapshot();
    });
    async function loadSnapshot(): Promise<boolean> {
      const requestId = snapshotRequestId + 1;
      snapshotRequestId = requestId;
      snapshotAbort?.abort();
      const abort = new AbortController();
      snapshotAbort = abort;
      try {
        const snapshotResponse = await transport.request({
          pathId: 'agent.session.snapshot',
          params: { sessionId: selectedId },
          query: {
            eventLimit: AGENT_HISTORY_EVENT_LIMIT,
            turnLimit: AGENT_HISTORY_TURN_LIMIT,
          },
          signal: abort.signal,
        });
        if (!active || requestId !== snapshotRequestId) return false;
        if (__CONTROL_PREVIEW__ && transport.kind === 'mock') {
          useAgentLiveStore.getState().hydrateSnapshot(selectedId, previewAgentSnapshot(selectedId));
          useAgentLiveStore.getState().applyEvents(selectedId, previewAgentEvents(selectedId));
        } else {
          useAgentLiveStore.getState().hydrate(selectedId, snapshotResponse);
        }
        const snapshot = isRecord(snapshotResponse) ? snapshotResponse : {};
        const liveEvents = arrayField(snapshot, 'liveEvents');
        const page = agentHistoryPage(snapshot);
        historyCacheRef.current.set(selectedId, { snapshot, liveEvents, page });
        setHistoryPages((pages) => {
          const next = new Map(pages);
          if (page) next.set(selectedId, page);
          else next.delete(selectedId);
          return next;
        });
        updateSessionHistoryState(selectedId, 'ready');
        const cursor = agentProjection(selectedId).resumeToken;
        unsubscribe();
        unsubscribe = transport.subscribe<UiAgentEvent>(
          { pathId: 'agent.session.events', params: { sessionId: selectedId }, lastEventId: cursor },
          {
            next: (event) => {
              sendTimings.observe(event);
              // Every transport reports snapshot_required through `next` and
              // the optional callback. Owning recovery here avoids launching
              // two snapshots for one gap while still recovering gaps found
              // locally by the reducer's batched sequence check.
              if (event.eventType === 'snapshot_required') {
                const needsSnapshot = useAgentLiveStore.getState().applyEvents(
                  selectedId,
                  [event],
                );
                if (needsSnapshot) void loadSnapshot();
                return;
              }
              batcher.push(event);
              if (event.eventType === 'session_configuration_changed') {
                modelSelection.applyConfigurationEvent(selectedId, event.payload);
              }
            },
            error: (streamError) => active && setError(errorText(streamError)),
          },
        );
        return true;
      } catch (loadError) {
        if (active && requestId === snapshotRequestId && !abort.signal.aborted) {
          if (historyStatesRef.current.get(selectedId) !== 'ready') {
            updateSessionHistoryState(selectedId, 'failed');
          }
          setError(`对话记录暂时无法恢复。${errorText(loadError)}`);
        }
        return false;
      } finally {
        if (requestId === snapshotRequestId) snapshotAbort = undefined;
      }
    }
    async function warmForkCatalog(): Promise<void> {
      if (isRoomParticipant) return;
      try {
        const response = await transport.request<Record<string, unknown>>({
          pathId: 'agent.session.forks.list',
          params: { sessionId: selectedId },
        });
        if (active) forkCatalogCacheRef.current.set(selectedId, response);
      } catch {
        // Fork discovery is an idle optimization. The explicit edit/branch
        // action still retries and owns any user-visible error.
      }
    }
    async function loadSessionCatalogs(): Promise<void> {
      setToolCatalogStatus('loading');
      setCapabilityCatalogError('');
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
      const publishNotice = (key: string, value = '') => {
        if (!active) return;
        // Catalog warnings have their own Session-local owner. A successful
        // retry clears only its source; it cannot erase a newer Stop, send,
        // approval, permission, or memory-review error (and vice versa).
        setCatalogNotice(selectedId, key, value);
      };
      const modelTask = transport.request({
        pathId: 'agent.session.models',
        params: { sessionId: selectedId },
      }).then((value) => {
        if (!active) return;
        if (!isModelCatalog(value)) {
          throw new Error('model catalog response is invalid');
        }
        modelSelection.acceptConfirmedCatalog(selectedId, value);
        publishNotice('model');
      }).catch((reason: unknown) => {
        if (!active) return;
        if (__CONTROL_PREVIEW__ && transport.kind === 'mock') {
          modelSelection.acceptConfirmedCatalog(
            selectedId,
            previewModelCatalog(selectedId),
          );
          publishNotice('model');
          return;
        }
        const cachedCatalog = modelCatalogCacheRef.current.get(selectedId);
        if (cachedCatalog) {
          modelSelection.acceptConfirmedCatalog(selectedId, cachedCatalog);
        } else {
          setCatalog(undefined);
        }
        publishNotice(
          'model',
          modelCatalogNotice(reason, Boolean(cachedCatalog)),
        );
      });
      // Provider discovery owns Host startup. Start the Session-specific
      // command inspection only after that independent catalog settles, so a
      // large transcript/context open cannot push the model picker behind the
      // native bridge timeout.
      const commandTask = modelTask.then(() => transport.request({
        pathId: 'agent.session.commands',
        params: { sessionId: selectedId },
      })).then(
        (value) => {
          if (!active) return;
          setCommands(commandItems(value));
          publishNotice('commands');
        },
        () => {
          if (!active) return;
          setCommands([]);
          publishNotice(
            'commands',
            'Pi 命令暂时不可用，仍可直接发送消息。',
          );
        },
      );
      const toolTask = transport.request({
        pathId: 'agent.tools.list',
        query: { sessionId: selectedId },
      }).then((value) => {
        if (!active) return;
        const nextCapabilityCatalog = requireSessionCapabilityCatalog(value, selectedId);
        setCapabilityCatalog(nextCapabilityCatalog);
        setTools(toolItems(value));
        setToolCatalogStatus('ready');
        publishNotice('tools');
      }).catch((reason: unknown) => {
        if (!active) return;
        const message = errorText(reason);
        setCapabilityCatalog(undefined);
        setCapabilityCatalogError(message);
        setTools([]);
        setToolCatalogStatus('failed');
        publishNotice('tools', `${message} 模型不会获得未核对的工具能力。`);
      });
      await Promise.allSettled([modelTask, commandTask, toolTask]);
    }
    // History recovery owns the stream cursor; model, command and tool
    // catalogs are independent and should become interactive immediately.
    void loadSnapshot().then((loaded) => {
      if (loaded) void warmForkCatalog();
    });
    void loadSessionCatalogs();
    return () => {
      active = false;
      snapshotAbort?.abort();
      batcher.clear();
      unsubscribe();
      sendTimings.clearSession(selectedId);
    };
  }, [ensure, isRoomParticipant, selectedId, sendTimings, transport, updateSessionHistoryState]);

  const defaultPersona = personas.find((item) => item.runtimeCharacteristics.isDefault)
    ?? personas.find((item) => item.roleId === 'companion-future-v1')
    ?? personas[0];
  const persona = personas.find((item) => item.roleId === session?.roleId) ?? defaultPersona;
  const busy = Boolean(activeTurnId);
  const branchBlocked = busy || sending;
  const rewriteBlocked = (
    branchBlocked
    || rewriteResolving
    || !conversationRewriteAvailable
    || isRoomParticipant
  );
  const imageSupport = useMemo(() => selectedModelImageSupport(catalog), [catalog]);
  useEffect(() => {
    if (!busy && selectedId) setSessionStopping(selectedId, false);
  }, [busy, selectedId]);
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
    selectSessionId(sessionId);
    if (mobileViewport) setRailOpen(false);
  }

  async function archiveSession(sessionId: string, archived: boolean): Promise<void> {
    try {
      await transport.request({
        pathId: 'agent.session.archive',
        params: { sessionId },
        body: { archived },
      });
      const currentSelectedId = selectedIdRef.current;
      await loadSessions(currentSelectedId === sessionId && archived && !showArchived ? '' : currentSelectedId);
      setError('');
    } catch (requestError) {
      setError(errorText(requestError));
    }
  }

  async function deleteSession(sessionId: string): Promise<void> {
    try {
      await transport.request({ pathId: 'agent.session.delete', params: { sessionId } });
      useAgentLiveStore.getState().clear(sessionId);
      deleteSessionInput(sessionId);
      sessionErrorsRef.current.delete(sessionId);
      catalogNoticesRef.current.delete(sessionId);
      sessionSendLocksRef.current.delete(sessionId);
      forkCatalogCacheRef.current.delete(sessionId);
      updateSessionHistoryState(sessionId);
      setSessions((current) => current.filter((item) => item.id !== sessionId));
      const currentSelectedId = selectedIdRef.current;
      if (currentSelectedId === sessionId) selectSessionId('');
      await loadSessions(currentSelectedId === sessionId ? '' : currentSelectedId);
      setError('');
    } catch (requestError) {
      const message = errorText(requestError);
      setError(message);
      throw new Error(message, { cause: requestError });
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
        selectSessionId(mockSession.id);
      }
      setError('');
      return true;
    } catch (requestError) {
      setError(errorText(requestError));
      return false;
    }
  }

  async function send(
    requestedDelivery: AgentMessageDelivery = busy ? 'steer' : 'prompt',
    composerDraft = draft,
  ): Promise<void> {
    if (!session || sending || modelChanging || contextResourcesChanging) return;
    const sendStartedAt = monotonicNow();
    const delivery: AgentMessageDelivery = busy
      ? (requestedDelivery === 'followUp' ? 'followUp' : 'steer')
      : 'prompt';
    const value = composerDraft.trim();
    if (editTarget) {
      if (!value && attachments.length === 0) return;
      if (editTarget.resolving || !editTarget.entryId) {
        setSessionError(session.id, '正在定位这条历史消息，请稍候。');
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
      const target = editTarget;
      const clientMessageId = `web-rewrite-${crypto.randomUUID()}`;
      if (!beginSessionSend(session.id)) return;
      sendTimings.begin(session.id, clientMessageId, sendStartedAt);
      useAgentLiveStore.getState().rewriteOptimistic(session.id, target.messageId, {
        clientMessageId,
        text: message,
        attachments: selectedAttachments.map((item) => item.id),
        nowMs: Date.now(),
      });
      sendTimings.optimistic(clientMessageId);
      rewriteResolveGenerationRef.current += 1;
      editTargetSessionIdRef.current = '';
      forkCatalogCacheRef.current.delete(session.id);
      setSessionDraft(session.id, '');
      setSessionAttachments(session.id, []);
      setSessionError(session.id, '');
      setEditTarget(undefined);
      setScrollToLatestRequest((current) => current + 1);

      // Rewind and Provider admission can restore a cold Pi Session. The
      // branch change is already visible above; reconcile the authoritative
      // response in the background instead of freezing the composer for it.
      void (async () => {
        try {
          const response = await transport.request<Record<string, unknown>>({
            pathId: 'agent.session.rewrite',
            params: { sessionId: session.id },
            body: {
              entryId: target.entryId,
              message,
              attachments: selectedAttachments.map((item) => item.id),
              clientMessageId,
            },
          });
          sendTimings.accepted(clientMessageId, response);
        } catch (requestError) {
          sendTimings.failed(clientMessageId);
          try {
            const snapshot = await transport.request({
              pathId: 'agent.session.snapshot',
              params: { sessionId: session.id },
            });
            useAgentLiveStore.getState().discardOptimistic(session.id, clientMessageId);
            useAgentLiveStore.getState().hydrate(session.id, snapshot);
            const accepted = Object.values(agentProjection(session.id).messagesById)
              .some((item) => item.clientMessageId === clientMessageId);
            if (!accepted) {
              const restored = restoreSessionInputIfUntouched(session.id, value, selectedAttachments);
              if (restored && selectedIdRef.current === session.id) {
                editTargetSessionIdRef.current = session.id;
                setEditTarget(target);
              }
              setSessionError(session.id, errorText(requestError));
            }
          } catch {
            useAgentLiveStore.getState().failOptimistic(
              session.id,
              clientMessageId,
              errorText(requestError),
              Date.now(),
              'ambiguous',
            );
            restoreSessionInputIfUntouched(session.id, value, selectedAttachments);
            setSessionError(session.id, '暂时无法确认修改后的消息是否已接收；已保留输入，请刷新对话核对。');
          }
        } finally {
          endSessionSend(session.id);
        }
      })();
      return;
    }
    if (value === '/new') { setSelectedDraft(''); setNewSessionOpen(true); return; }
    if (value === '/resume') { setSelectedDraft(''); setRailOpen(true); return; }
    if (value === '/branch') { setSelectedDraft(''); openForkDialog(); return; }
    if (isCommand(value, '/name')) {
      const title = normalizedSessionTitle(commandArgument(value, '/name'));
      if (!title) {
        setError('请在 /name 后输入新的对话名称。');
        return;
      }
      if (!beginSessionSend(session.id)) return;
      try {
        await transport.request({ pathId: 'agent.session.rename', params: { sessionId: session.id }, body: { title } });
        setSessions((current) => current.map((item) => item.id === session.id ? { ...item, title, updatedAtMs: Date.now() } : item));
        setSessionDraft(session.id, '');
        setSessionError(session.id, '');
      } catch (requestError) { setSessionError(session.id, errorText(requestError)); }
      finally { endSessionSend(session.id); }
      return;
    }
    if (isCommand(value, '/compact')) {
      if (!beginSessionSend(session.id)) return;
      try { await transport.request({ pathId: 'agent.session.compact', params: { sessionId: session.id }, body: { instructions: commandArgument(value, '/compact') } }); setSessionDraft(session.id, ''); }
      catch (requestError) { setSessionError(session.id, errorText(requestError)); }
      finally { endSessionSend(session.id); }
      return;
    }
    if (value === '/model' || value === '/thinking') { setSelectedDraft(''); openModelPicker(); return; }
    if (value === '/permissions') { setSelectedDraft(''); setPermissionPickerRequest((current) => current + 1); return; }
    if (value === '/tools') { setSelectedDraft(''); openToolPicker(); return; }
    if (value === '/status' || value === '/session') { setSelectedDraft(''); setStatusOpen(true); return; }
    if (value === '/settings') { setSelectedDraft(''); window.location.hash = '/configuration'; return; }
    if (value === '/help' || value === '/hotkeys') { setSelectedDraft(''); setHelpRequest((current) => current + 1); return; }
    if (value === '/stop') { setSelectedDraft(''); await stop(); return; }
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
    setSessionDraft(session.id, '');
    setSessionAttachments(session.id, []);
    setSessionError(session.id, '');
    promptSession(
      session.id,
      message,
      selectedAttachments.map((item) => item.id),
      delivery,
      () => {
        restoreSessionInputIfUntouched(session.id, value, selectedAttachments);
      },
      undefined,
      sendStartedAt,
    );
  }

  function promptSession(
    sessionId: string,
    message: string,
    attachmentIds: string[],
    delivery: AgentMessageDelivery = 'prompt',
    restoreInput?: () => void,
    onAdmissionRolledBack?: () => void,
    startedAt = monotonicNow(),
    requestedClientMessageId = '',
    retryOfClientMessageId = '',
    reuseOptimistic = false,
  ): boolean {
    if (!beginSessionSend(sessionId)) return false;
    const clientMessageId = (
      requestedClientMessageId
      || `web-${crypto.randomUUID()}`
    );
    sendTimings.begin(sessionId, clientMessageId, startedAt);
    if (reuseOptimistic) {
      useAgentLiveStore.getState().requeueOptimistic(
        sessionId,
        clientMessageId,
        Date.now(),
      );
    } else {
      useAgentLiveStore.getState().appendOptimistic(sessionId, {
        clientMessageId,
        ...(retryOfClientMessageId
          ? { retryOfClientMessageId }
          : {}),
        text: message,
        attachments: attachmentIds,
        nowMs: Date.now(),
        ...(delivery === 'prompt' ? {} : { turnId: activeTurnId, delivery }),
      });
    }
    sendTimings.optimistic(clientMessageId);
    setSessionError(sessionId, '');
    const requestBody = {
      message,
      attachments: attachmentIds,
      clientMessageId,
      ...(retryOfClientMessageId
        ? { retryOfClientMessageId }
        : {}),
      ...(delivery === 'prompt' ? {} : { delivery }),
    };
    const requestAdmission = () => (
      transport.request<Record<string, unknown>>({
        pathId: 'agent.session.prompt',
        params: { sessionId },
        body: requestBody,
      })
    );
    const handlePendingAdmission = (requestError: unknown): boolean => {
      if (!isAgentCommandPending(requestError)) return false;
      if (
        !agentProjection(sessionId)
          .optimisticByClientMessageId[clientMessageId]
      ) {
        return true;
      }
      sendTimings.failed(clientMessageId);
      useAgentLiveStore.getState().failOptimistic(
        sessionId,
        clientMessageId,
        publicAgentErrorText(requestError),
        Date.now(),
        isUnresolvedAgentCommandPending(requestError)
          ? 'unresolved'
          : 'pending',
      );
      setSessionError(sessionId, '');
      return true;
    };
    // Admission and the optimistic turn are synchronous. Restoring a Pi
    // Session, refreshing context, or starting a Provider can still make the
    // HTTP receipt slow, but must not make the click itself feel stalled.
    void (async () => {
      try {
        const response = await requestAdmission();
        sendTimings.accepted(clientMessageId, response);
      } catch (requestError) {
        if (handlePendingAdmission(requestError)) return;
        sendTimings.failed(clientMessageId);
        if (isAmbiguousAgentPromptFailure(requestError)) {
          useAgentLiveStore.getState().failOptimistic(
            sessionId,
            clientMessageId,
            '暂时无法确认是否已接收。系统不会自动重试；手动重试会核对同一条消息。',
            Date.now(),
            'ambiguous',
          );
          return;
        }
        if (isAgentTurnConflict(requestError)) {
          useAgentLiveStore.getState().discardOptimistic(sessionId, clientMessageId);
          restoreInput?.();
          onAdmissionRolledBack?.();
          setSessionError(sessionId, '上一轮仍在处理，输入已保留；可以继续补充或先停止当前轮。');
          return;
        }
        const failure = publicAgentErrorText(requestError);
        const projection = agentProjection(sessionId);
        const hasOptimisticTurn = Boolean(projection.optimisticByClientMessageId[clientMessageId]);
        useAgentLiveStore.getState().failOptimistic(sessionId, clientMessageId, failure, Date.now());
        restoreInput?.();
        setSessionError(sessionId, hasOptimisticTurn ? '' : failure);
      } finally {
        endSessionSend(sessionId);
      }
    })();
    return true;
  }

  function retryTurn(
    turnId: string,
    onAdmissionRolledBack?: () => void,
  ): boolean {
    if (!session || sending || latestActiveTurnId(agentProjection(session.id))) return false;
    const sendStartedAt = monotonicNow();
    const projection = agentProjection(session.id);
    const turn = projection.turnsById[turnId];
    const userMessage = turn?.messageIds
      .map((messageId) => projection.messagesById[messageId])
      .find((message) => message?.role === 'user');
    if (
      userMessage?.admissionState === 'pending'
      || userMessage?.admissionState === 'unresolved'
    ) {
      setError(
        '这条消息仍无法确认是否已执行；为避免重复执行，不能自动重试。'
        + '请刷新对话检查结果后，再决定是否发送新的请求。',
      );
      return false;
    }
    const message = userMessage?.blocks
      .map((block) => typeof block.data.text === 'string' ? block.data.text : '')
      .filter(Boolean)
      .join('\n')
      .trim() ?? '';
    if (!message && !userMessage?.attachments.length) {
      setError('找不到这轮的原始输入，无法安全重试。');
      return false;
    }
    const replayAmbiguousAdmission = (
      userMessage?.admissionState === 'ambiguous'
      && Boolean(userMessage.clientMessageId)
    );
    return promptSession(
      session.id,
      message || '请查看附件。',
      userMessage?.attachments ?? [],
      'prompt',
      undefined,
      onAdmissionRolledBack,
      sendStartedAt,
      replayAmbiguousAdmission
        ? userMessage?.clientMessageId
        : '',
      replayAmbiguousAdmission
        ? ''
        : userMessage?.clientMessageId ?? '',
      replayAmbiguousAdmission,
    );
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
        setSelectedDraft('');
        setNewSessionOpen(true);
        break;
      case 'resume':
        setSelectedDraft('');
        setRailOpen(true);
        break;
      case 'branch':
        setSelectedDraft('');
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
        setSelectedDraft('');
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
    setForkDialogNodes(conversationNodesForSession(session.id));
    setForkDialogInitialEntryId(initialEntryId);
    setForkDialogOpen(true);
  }

  async function beginEditMessage(messageId = ''): Promise<void> {
    if (!session || rewriteBlocked) {
      setError(isRoomParticipant
        ? '这段对话属于 Room participant，历史修改由 Room 管理。'
        : conversationRewriteAvailable
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
    const nodes = conversationNodesForSession(session.id);
    const attachments = message.attachments.map((id, index) => ({
      id,
      name: `原附件 ${index + 1}`,
      mimeType: '',
      byteSize: 0,
      source: 'path' as const,
    }));
    const generation = rewriteResolveGenerationRef.current + 1;
    rewriteResolveGenerationRef.current = generation;
    editTargetSessionIdRef.current = session.id;
    setEditTarget({ entryId: '', messageId: message.id, resolving: true });
    setSessionDraft(session.id, text);
    setSessionAttachments(session.id, attachments);
    setTimelineJumpRequest({ messageId: message.id, requestId: Date.now() });
    setError('');

    const cached = forkCatalogCacheRef.current.get(session.id);
    const cachedEntryId = cached
      ? resolveConversationEntryId(cached, nodes, message.id)
      : '';
    if (cachedEntryId) {
      setEditTarget({ entryId: cachedEntryId, messageId: message.id });
      return;
    }

    setSessionRewriteResolving(session.id, true);
    try {
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.session.forks.list',
        params: { sessionId: session.id },
      });
      if (
        selectedIdRef.current !== session.id
        || rewriteResolveGenerationRef.current !== generation
      ) return;
      forkCatalogCacheRef.current.set(session.id, response);
      const entryId = resolveConversationEntryId(response, nodes, message.id);
      if (!entryId) throw new Error('Pi 没有返回这条公开消息对应的可回溯锚点。');
      setEditTarget({ entryId, messageId: message.id });
    } catch (requestError) {
      if (rewriteResolveGenerationRef.current !== generation) return;
      editTargetSessionIdRef.current = '';
      setEditTarget(undefined);
      setSessionError(session.id, publicAgentErrorText(requestError, '暂时无法定位这条历史消息。'));
    } finally {
      if (rewriteResolveGenerationRef.current === generation) {
        setSessionRewriteResolving(session.id, false);
      }
    }
  }

  function cancelEdit(): void {
    rewriteResolveGenerationRef.current += 1;
    editTargetSessionIdRef.current = '';
    if (session) setSessionRewriteResolving(session.id, false);
    setEditTarget(undefined);
    setSelectedDraft('');
    setSelectedAttachments([]);
  }

  function jumpToMessage(messageId: string): void {
    setTimelineJumpRequest({ messageId, requestId: Date.now() });
  }

  async function acceptFork(created: SessionSummary, selectedText: string): Promise<void> {
    setSessions((current) => [created, ...current.filter((item) => item.id !== created.id)]);
    seedSessionInput(created.id, selectedText, []);
    sessionErrorsRef.current.set(created.id, '');
    selectSessionId(created.id);
    if (mobileViewport) setRailOpen(false);
  }

  async function stop(): Promise<void> {
    if (!session || stopping) return;
    setSessionStopping(session.id, true);
    try {
      await transport.request({
        pathId: 'agent.session.abort',
        params: { sessionId: session.id },
        body: {},
      });
      // Abort acknowledgement only means Pi accepted the request. Reconcile
      // once with the authoritative Session row so a stale client-side busy
      // marker can recover; a genuinely active turn remains locked until its
      // terminal SSE event arrives.
      const snapshot = await transport.request({
        pathId: 'agent.session.snapshot',
        params: { sessionId: session.id },
      });
      useAgentLiveStore.getState().hydrate(session.id, snapshot);
      setSessionError(session.id, '');
    } catch (requestError) {
      setSessionStopping(session.id, false);
      setSessionError(session.id, errorText(requestError));
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
      if (!imported.length) {
        setSessionError(session.id, '剪贴板里没有可导入的 PNG、JPEG、GIF 或 WebP 图片。');
        return;
      }
      const attachmentsWithPreviews = files && transport.kind !== 'native'
        ? imported.map((attachment, index) => {
          const file = files[index];
          return file
            && file.name === attachment.name
            && file.type.toLowerCase() === attachment.mimeType.toLowerCase()
            && file.size === attachment.byteSize
            ? { ...attachment, previewFile: file }
            : attachment;
        })
        : imported;
      mergeSessionAttachments(session.id, attachmentsWithPreviews, 'clipboard');
      setSessionError(session.id, '');
    } catch (pasteError) { setSessionError(session.id, errorText(pasteError)); }
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
      if (!imported.length) return;
      mergeSessionAttachments(session.id, imported, 'picker');
      setSessionError(session.id, '');
    } catch (pickError) { setSessionError(session.id, errorText(pickError)); }
  }

  function chooseTool(tool: ToolManifest): void {
    const intent = toolIntentPrompt(tool.id, tool.displayName);
    setSelectedDraft((current) => current.trim() ? `${current.trimEnd()}\n${intent}：` : `${intent}：`);
  }

  async function changeCapabilityPreference(
    canonicalId: string,
    preference: CapabilityPreference,
    catalogSnapshot: CapabilityCatalog | undefined = capabilityCatalog,
  ): Promise<void> {
    if (!session || !catalogSnapshot?.sessionPolicy) return;
    const ownerSessionId = session.id;
    const setMutation = (outcome: CapabilityMutationOutcome) => {
      setCapabilityPolicyMutations((current) => {
        const next = new Map(current);
        next.set(ownerSessionId, outcome);
        return next;
      });
    };
    if (busy || stopping) {
      setMutation({
        canonicalId,
        preference,
        status: 'failed',
        message: '当前任务仍在运行；只有空闲对话才能修改这项策略。运行中的任务不会被停止或隐藏。',
      });
      return;
    }
    const currentSessionPreferences = catalogSnapshot.sessionPolicy.disclosurePreferences.session;
    setMutation({
      canonicalId,
      preference,
      status: 'pending',
      message: '正在等待后端确认并重新读取有效能力。',
    });
    try {
      await transport.request({
        pathId: 'agent.session.capability-policy.update',
        params: { sessionId: ownerSessionId },
        body: {
          capabilityDisclosurePreferences: {
            ...currentSessionPreferences,
            [canonicalId]: preference,
          },
        },
      });
      const refreshed = await transport.request({
        pathId: 'agent.tools.list',
        query: { sessionId: ownerSessionId },
      });
      const nextCapabilityCatalog = requireSessionCapabilityCatalog(refreshed, ownerSessionId);
      const updatedItem = nextCapabilityCatalog.items.find((item) => item.canonicalId === canonicalId);
      if (!updatedItem) {
        throw new Error('能力设置已提交，但后端目录不再包含这项能力。');
      }
      if (selectedIdRef.current === ownerSessionId) {
        setCapabilityCatalog(nextCapabilityCatalog);
        setTools(toolItems(refreshed));
        setToolCatalogStatus('ready');
        setCapabilityCatalogError('');
      }
      setMutation({
        canonicalId,
        preference,
        status: 'succeeded',
        message: `后端已确认${updatedItem.disclosure.effective === 'enabled' ? '披露' : '隐藏'}；生效来源为${capabilityScopeLabel(updatedItem.effectiveScope)}。执行授权未由这次设置更改。`,
      });
    } catch (requestError) {
      setMutation({
        canonicalId,
        preference,
        status: 'failed',
        message: `当前对话的能力没有更新。${errorText(requestError)}`,
      });
    }
  }

  async function retryCapabilityPreference(): Promise<void> {
    if (!capabilityPolicyMutation) return;
    const ownerSessionId = selectedIdRef.current;
    const retryMutation = capabilityPolicyMutation;
    setCapabilityPolicyMutations((current) => {
      const next = new Map(current);
      next.set(ownerSessionId, {
        ...retryMutation,
        status: 'pending',
        message: '正在重新读取当前对话策略，再重试这项调整。',
      });
      return next;
    });
    try {
      const response = await transport.request({
        pathId: 'agent.tools.list',
        query: { sessionId: ownerSessionId },
      });
      const refreshedCatalog = requireSessionCapabilityCatalog(response, ownerSessionId);
      if (selectedIdRef.current !== ownerSessionId) {
        setCapabilityPolicyMutations((current) => {
          const next = new Map(current);
          next.set(ownerSessionId, {
            ...retryMutation,
            status: 'failed',
            message: '重试期间切换了当前对话；未向新对话发送原来的设置。',
          });
          return next;
        });
        return;
      }
      setCapabilityCatalog(refreshedCatalog);
      setTools(toolItems(response));
      setToolCatalogStatus('ready');
      setCapabilityCatalogError('');
      await changeCapabilityPreference(
        retryMutation.canonicalId,
        retryMutation.preference,
        refreshedCatalog,
      );
    } catch (retryError) {
      setCapabilityPolicyMutations((current) => {
        const next = new Map(current);
        next.set(ownerSessionId, {
          ...retryMutation,
          status: 'failed',
          message: `当前对话的能力没有更新。${errorText(retryError)}`,
        });
        return next;
      });
    }
  }

  async function retryCapabilityCatalog(): Promise<void> {
    const ownerSessionId = selectedIdRef.current;
    if (!ownerSessionId) return;
    setToolCatalogStatus('loading');
    try {
      const response = await transport.request({
        pathId: 'agent.tools.list',
        query: { sessionId: ownerSessionId },
      });
      const nextCapabilityCatalog = requireSessionCapabilityCatalog(response, ownerSessionId);
      if (selectedIdRef.current !== ownerSessionId) return;
      setCapabilityCatalog(nextCapabilityCatalog);
      setTools(toolItems(response));
      setToolCatalogStatus('ready');
      setCapabilityCatalogError('');
      setCatalogNotice(ownerSessionId, 'tools');
    } catch (catalogError) {
      if (selectedIdRef.current !== ownerSessionId) return;
      const message = errorText(catalogError);
      setCapabilityCatalog(undefined);
      setCapabilityCatalogError(message);
      setTools([]);
      setToolCatalogStatus('failed');
      setCatalogNotice(ownerSessionId, 'tools', `${message} 模型不会获得未核对的工具能力。`);
    }
  }

  async function changePermission(selection: AgentPermissionSelection): Promise<void> {
    if (!session) return;
    if (busy || stopping) {
      setSessionError(session.id, '请先结束或停止当前任务，再调整运行权限。');
      return;
    }
    const currentProfile = session.toolProfileVersion ?? 'control-center-v1';
    const currentExecutionMode = session.executionMode
      ?? (currentProfile === 'control-center-auto-approve-v1'
        ? 'full_trust'
        : currentProfile === 'subagent-readonly-v1'
          ? 'read_only'
          : 'per_action');
    if (
      selection.mode === session.mode
      && selection.toolProfileVersion === currentProfile
      && selection.executionMode === currentExecutionMode
      && session.toolAllowlistMode !== 'explicit'
    ) return;
    try {
      let workspaceRoots = selection.mode === 'coordinator' ? session.workspaceRoots : [];
      if (selection.mode === 'coordinator' && workspaceRoots.length === 0) {
        const selectedRoots = await pickWorkspaceRoots(false, session.id);
        if (selectedRoots === null) return;
        workspaceRoots = selectedRoots;
      }
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.session.mode.update',
        params: { sessionId: session.id },
        body: {
          mode: selection.mode,
          executionMode: selection.executionMode,
          workspaceRoots,
          toolProfileVersion: selection.toolProfileVersion,
          toolAllowlistMode: 'profile',
          ...(selection.dangerousModeConfirmed
            ? { dangerousModeConfirmation: 'ENABLE_FULL_TRUST' }
            : {}),
          ...(selection.workspaceScopeConfirmed
            ? { workspaceScopeConfirmation: 'APPROVE_WORKSPACE_SCOPE' }
            : {}),
        },
      });
      const updated = isRecord(response.session)
        ? response.session as unknown as SessionSummary
        : {
          ...session,
          mode: selection.mode,
          toolProfileVersion: selection.toolProfileVersion,
          executionMode: selection.executionMode,
          workspaceScopeGranted: selection.executionMode === 'workspace_managed'
            || selection.executionMode === 'full_trust',
          toolAllowlistMode: 'profile' as const,
          allowedTools: [],
          workspaceRoots,
        };
      setSessions((current) => current.map((item) => item.id === session.id ? updated : item));
      if (selectedIdRef.current !== session.id) return;
      setToolCatalogStatus('loading');
      try {
        const toolResponse = await transport.request({ pathId: 'agent.tools.list', query: { sessionId: session.id } });
        const nextCapabilityCatalog = requireSessionCapabilityCatalog(toolResponse, session.id);
        if (selectedIdRef.current !== session.id) return;
        setCapabilityCatalog(nextCapabilityCatalog);
        setTools(toolItems(toolResponse));
        setToolCatalogStatus('ready');
        setCapabilityCatalogError('');
        setSessionError(session.id, '');
      } catch (catalogError) {
        if (selectedIdRef.current !== session.id) return;
        setTools([]);
        setCapabilityCatalog(undefined);
        setToolCatalogStatus('failed');
        setCapabilityCatalogError(errorText(catalogError));
        setSessionError(session.id, `权限已更新，但工具目录刷新失败。${errorText(catalogError)}`);
      }
    } catch (requestError) { setSessionError(session.id, errorText(requestError)); }
  }

  async function pickWorkspaceRoots(
    single = false,
    ownerSessionId = selectedIdRef.current,
  ): Promise<string[] | null> {
    if (!transport.pickFiles) {
      setSessionError(ownerSessionId, '当前平台不能选择本地工作区；请在桌面控制中心中配置运行协调权限。');
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
      setSessionError(ownerSessionId, `工作区选择失败。${errorText(pickError)}`);
      return null;
    }
  }

  async function manageWorkspaceRoots(): Promise<void> {
    if (!session) return;
    const workspaceRoots = await pickWorkspaceRoots(false, session.id);
    if (workspaceRoots === null) return;
    try {
      const explicit = session.toolAllowlistMode === 'explicit';
      const executionMode = session.executionMode ?? 'per_action';
      const response = await transport.request<Record<string, unknown>>({
        pathId: 'agent.session.mode.update',
        params: { sessionId: session.id },
        body: {
          mode: 'coordinator',
          executionMode,
          workspaceRoots,
          toolProfileVersion: session.toolProfileVersion ?? 'control-center-v1',
          toolAllowlistMode: explicit ? 'explicit' : 'profile',
          ...(explicit ? { allowedTools: session.allowedTools ?? [] } : {}),
          ...(executionMode === 'workspace_managed'
            ? { workspaceScopeConfirmation: 'APPROVE_WORKSPACE_SCOPE' }
            : {}),
          ...(executionMode === 'full_trust'
            ? { dangerousModeConfirmation: 'ENABLE_FULL_TRUST' }
            : {}),
        },
      });
      const updated = isRecord(response.session)
        ? response.session as unknown as SessionSummary
        : { ...session, mode: 'coordinator' as const, workspaceRoots };
      setSessions((current) => current.map((item) => item.id === session.id ? updated : item));
      if (selectedIdRef.current !== session.id) return;
      const toolResponse = await transport.request({ pathId: 'agent.tools.list', query: { sessionId: session.id } });
      if (selectedIdRef.current !== session.id) return;
      const nextCapabilityCatalog = requireSessionCapabilityCatalog(toolResponse, session.id);
      setCapabilityCatalog(nextCapabilityCatalog);
      setTools(toolItems(toolResponse));
      setToolCatalogStatus('ready');
      setCapabilityCatalogError('');
      setSessionError(session.id, '');
    } catch (requestError) {
      setSessionError(session.id, `工作区权限没有更新。${errorText(requestError)}`);
    }
  }

  function changeModel(provider: string, modelId: string, level: ThinkingLevel): void {
    if (!session || !catalog) return;
    const targetModel = catalog.providers.find((item) => item.id === provider)?.models.find((item) => item.id === modelId);
    if (!targetModel) { setError('Pi 模型目录中没有这个模型。'); return; }
    if (attachments.length && !targetModel.supportsImages) {
      setError('当前消息含有图片，请先移除图片再切换到不支持图片的模型。');
      return;
    }
    modelSelection.select(session.id, catalog, { provider, modelId, level });
  }

  async function decideApproval(approvalId: string, decision: 'approved' | 'rejected', payloadSha256: string): Promise<void> {
    const ownerSessionId = selectedIdRef.current;
    if (!ownerSessionId) throw new Error('请先选择审批所属的对话。');
    try {
      await transport.request({
        pathId: 'agent.approval.decide',
        params: { approvalId },
        body: { decision: decision === 'approved' ? 'approve' : 'reject', payloadSha256 },
      });
      if (selectedIdRef.current === ownerSessionId) setRequestedApproval(undefined);
      setSessionError(ownerSessionId, '');
    }
    catch (requestError) {
      setSessionError(ownerSessionId, errorText(requestError));
      throw requestError;
    }
  }

  return (
    <main className="agent-feature" data-route-id="agent" data-rail-open={railOpen} data-status-open={statusOpen}>
      <h1 className="agent-feature__title">Agent 任务中心</h1>
      <SessionRail ref={railRef} sessions={sessions} selectedId={selectedId} loading={loading} error={sessionLoadError} open={railOpen} modal={railModal} blocked={statusModal || newSessionOpen} showArchived={showArchived} onSelect={selectSession} onCreate={() => { if (mobileViewport) setRailOpen(false); setNewSessionOpen(true); }} onShowArchivedChange={setShowArchived} onArchive={(sessionId, archived) => void archiveSession(sessionId, archived)} onDelete={deleteSession} onRetry={() => void loadSessions(selectedIdRef.current || requestedSessionId)} onClose={closeMobileRail} />
      <AgentPaneResizer side="rail" />
      <button className="agent-rail-backdrop" aria-hidden="true" disabled={!railModal} tabIndex={-1} onClick={closeMobileRail} type="button" />
      <section
        ref={conversationRef}
        className="agent-conversation"
        aria-hidden={railModal || statusModal || undefined}
        inert={railModal || statusModal ? true : undefined}
      >
        <header className="agent-conversation__header">
          <IconButton ref={railToggleRef} className="agent-rail-toggle" label={railOpen ? '收起对话列表' : '展开对话列表'} icon={railOpen ? <PanelLeftClose size={17} /> : <PanelLeftOpen size={17} />} onClick={toggleRail} tooltip />
          <span><strong>{session?.title ?? identity.assistantName}</strong><small>{session ? `${sessionProjectName(session)} · 本地 · ${sessionPermissionLabel(session)}` : '选择一段对话'}</small></span>
          {error ? <p role="alert" title={error}><AlertCircle size={14} /><span>{error}</span></p> : null}
          <div className="agent-conversation__actions">
            <IconButton label="查看对话路径与分支" icon={<GitBranch size={17} />} onClick={() => openForkDialog()} disabled={!session} tooltip />
            <IconButton ref={statusToggleRef} className="agent-status-toggle" aria-controls="agent-status-panel" aria-expanded={statusOpen} label={statusOpen ? '收起任务中心' : '展开任务中心'} icon={statusOpen ? <PanelRightClose size={17} /> : <PanelRightOpen size={17} />} disabled={!session} onClick={toggleStatus} tooltip />
          </div>
        </header>
        {selectedId ? <AgentTimeline assistantName={identity.assistantName} sessionId={selectedId} persona={persona} modelSelectionAvailable={Boolean(catalog)} historyStatus={historyState} expectedMessageCount={session?.messageCount ?? 0} hasOlderHistory={Boolean(historyPages.get(selectedId)?.hasOlderLiveEvents || historyPages.get(selectedId)?.hasOlderMessages)} loadingOlderHistory={olderHistoryLoadingIds.has(selectedId)} onLoadOlderHistory={loadOlderHistory} turnRecoveryDisabled={busy || sending || stopping || modelChanging} forkAvailable={conversationForkAvailable && !branchBlocked && !isRoomParticipant} rewriteAvailable={!rewriteBlocked} jumpRequest={timelineJumpRequest} scrollToLatestRequest={scrollToLatestRequest} onAtBottomChange={setTimelineAtBottom} onForkFromMessage={openForkDialog} onEditMessage={(messageId) => void beginEditMessage(messageId)} onSuggestion={setSelectedDraft} onRetryTurn={retryTurn} onSwitchModel={openModelPicker} onApprovalDecision={(id, decision, hash) => { void decideApproval(id, decision, hash).catch(() => {}); }} onOpenApproval={setRequestedApproval} onRequestPermission={() => setPermissionPickerRequest((current) => current + 1)} /> : null}
        {session ? (
          <div className="agent-composer-dock">
            {pendingGenericInput && !pendingApproval && !pendingMemoryReview ? (
              <GenericUserInputCard
                activity={pendingGenericInput}
                sessionId={selectedId}
                onError={(message) => setSessionError(selectedId, message)}
              />
            ) : (
          <AgentComposer
            assistantName={identity.assistantName}
            attachments={attachments}
            busy={busy}
            capabilityCatalog={capabilityCatalog}
            capabilityPolicyPending={capabilityPolicyPending}
            catalog={catalog}
            commands={commands}
            contextResourcesChanging={contextResourcesChanging}
            draft={draft}
            editState={editTarget}
            helpRequest={helpRequest}
            imageSupport={imageSupport}
            modelChanging={modelChanging}
            modelPickerRequest={modelPickerRequest}
            permissionPickerRequest={permissionPickerRequest}
            persona={persona}
            sending={sending || rewriteResolving}
            session={session}
            showJumpLatest={!timelineAtBottom}
            stopping={stopping}
            toolCatalogStatus={toolCatalogStatus}
            toolPickerRequest={toolPickerRequest}
            tools={tools}
            onAttachmentsChange={setSelectedAttachments}
            onCancelEdit={cancelEdit}
            onCapabilityPreferenceChange={(canonicalId, preference) => void changeCapabilityPreference(canonicalId, preference)}
            onContextResourcesChange={(selection) => contextResources.select(session, selection)}
            onDraftChange={persistSelectedDraft}
            onEditPrevious={() => void beginEditMessage()}
            onJumpLatest={() => setScrollToLatestRequest((current) => current + 1)}
            onModelChange={changeModel}
            onPasteFromClipboard={() => void pasteImages()}
            onPasteImages={(files) => void pasteImages(files)}
            onPermissionChange={(selection) => void changePermission(selection)}
            onPickAttachments={() => void pickAttachments()}
            onProductCommand={runProductCommand}
            onSend={(delivery, value) => void send(delivery, value)}
            onStop={() => void stop()}
            onToolSelect={chooseTool}
            onWorkspaceRootsChange={() => void manageWorkspaceRoots()}
          />
            )}
          </div>
        ) : (
          <AgentConversationState
            loading={loading}
            error={sessionLoadError}
            onCreate={() => setNewSessionOpen(true)}
            onOpenRail={() => setRailOpen(true)}
          />
        )}
      </section>
      <button className="agent-status-backdrop" aria-hidden="true" disabled={!statusModal} tabIndex={-1} onClick={closeStatusPanel} type="button" />
      <AgentPaneResizer side="status" />
      <AgentStatusPanel
        ref={statusRef}
        sessionId={selectedId}
        open={statusOpen}
        capabilityCatalogError={capabilityCatalogError}
        modal={statusModal}
        tools={tools}
        toolCatalogStatus={toolCatalogStatus}
        capabilityCatalog={capabilityCatalog}
        capabilityPolicyMutation={capabilityPolicyMutation}
        busy={busy}
        onCapabilityCatalogRetry={() => void retryCapabilityCatalog()}
        onCapabilityPolicyRetry={retryCapabilityPreference}
        onCapabilityPreferenceChange={(canonicalId, preference) => void changeCapabilityPreference(canonicalId, preference)}
        onClose={closeStatusPanel}
      />
      <MemoryReviewDialog
        activity={pendingApproval ? undefined : pendingMemoryReview}
        sessionId={selectedId}
        onError={(message) => setSessionError(selectedId, message)}
      />
      <ApprovalReviewDialog activity={approvalForReview} onDecision={decideApproval} />
      <NewSessionDialog
        open={newSessionOpen}
        projects={projectPaths}
        defaultRoots={[]}
        onOpenChange={setNewSessionOpen}
        onPickRoots={() => pickWorkspaceRoots(true)}
        onCreate={createSession}
      />
      <ConversationForkDialog
        assistantName={identity.assistantName}
        open={forkDialogOpen}
        sessionId={session?.id ?? ''}
        sessionTitle={session?.title ?? '新对话'}
        nodes={forkDialogNodes}
        initialEntryId={forkDialogInitialEntryId}
        branchAvailable={conversationForkAvailable && !isRoomParticipant}
        branchBlocked={branchBlocked}
        branchUnavailableReason={isRoomParticipant
          ? '这段对话属于 Room participant，历史分支与修改由 Room 管理。'
          : undefined}
        onOpenChange={setForkDialogOpen}
        onJump={jumpToMessage}
        onCreated={(created, selectedText) => { void acceptFork(created, selectedText); }}
      />
    </main>
  );
}

function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value); }
function arrayField(value: Record<string, unknown>, key: string): unknown[] {
  return Array.isArray(value[key]) ? value[key] : [];
}
function snapshotMessages(value: Record<string, unknown>): unknown[] {
  return Array.isArray(value.messages)
    ? value.messages
    : arrayField(value, 'items');
}
function agentHistoryPage(value: Record<string, unknown>): AgentHistoryPage | undefined {
  const page = value.historyPage;
  if (!isRecord(page)) return undefined;
  return {
    hasOlderLiveEvents: page.hasOlderLiveEvents === true,
    olderBeforeEventId: typeof page.olderBeforeEventId === 'string'
      ? page.olderBeforeEventId
      : '',
    hasOlderMessages: page.hasOlderMessages === true,
    olderBeforeMessageId: typeof page.olderBeforeMessageId === 'string'
      ? page.olderBeforeMessageId
      : '',
    totalLiveEvents: typeof page.totalLiveEvents === 'number'
      ? page.totalLiveEvents
      : 0,
    totalMessages: typeof page.totalMessages === 'number'
      ? page.totalMessages
      : 0,
  };
}
function mergeAgentHistoryEvents(...groups: readonly unknown[][]): unknown[] {
  const merged: unknown[] = [];
  const indexes = new Map<string, number>();
  for (const group of groups) {
    for (const value of group) {
      const eventId = isRecord(value) && typeof value.eventId === 'string'
        ? value.eventId
        : '';
      if (!eventId) {
        merged.push(value);
        continue;
      }
      const existing = indexes.get(eventId);
      if (existing === undefined) {
        indexes.set(eventId, merged.length);
        merged.push(value);
      } else {
        merged[existing] = value;
      }
    }
  }
  return merged;
}
function mergeAgentHistoryMessages(...groups: readonly unknown[][]): unknown[] {
  const merged: unknown[] = [];
  const indexes = new Map<string, number>();
  for (const group of groups) {
    for (const value of group) {
      const messageId = isRecord(value) && typeof value.id === 'string'
        ? value.id
        : '';
      if (!messageId) {
        merged.push(value);
        continue;
      }
      const existing = indexes.get(messageId);
      if (existing === undefined) {
        indexes.set(messageId, merged.length);
        merged.push(value);
      } else {
        merged[existing] = value;
      }
    }
  }
  return merged;
}
function conversationNodeText(blocks: Array<{ type: string; data: Record<string, unknown> }>): string {
  const value = blocks.map((block) => {
    const candidates = [block.data.text, block.data.markdown, block.data.code, block.data.message, block.data.summary];
    return candidates.find((item): item is string => typeof item === 'string' && item.trim().length > 0) ?? '';
  }).filter(Boolean).join('\n').replace(/\s+/gu, ' ').trim();
  return value.slice(0, 480) || '非文本消息';
}

function conversationNodesForSession(sessionId: string): ConversationNode[] {
  const projection = agentProjection(sessionId);
  return projection.messageOrder
    .map((messageId) => projection.messagesById[messageId])
    .filter((message) => (
      message
      && (message.role === 'user' || message.role === 'assistant')
    ))
    .map((message) => ({
      entryId: message!.id,
      role: message!.role as ConversationNode['role'],
      text: conversationNodeText(message!.blocks),
      createdAtMs: message!.createdAtMs,
    }))
    .filter((node) => node.text.length > 0);
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
function modelCatalogNotice(value: unknown, usingCachedCatalog = false): string {
  const message = value instanceof Error ? value.message : String(value ?? '');
  if (/session runtime is unavailable|workspace (?:does not exist|no longer exists)/i.test(message)) {
    return '这段对话的工作目录已不可用；对话记录仍保留，可以归档后选择其他对话。';
  }
  if (usingCachedCatalog) {
    return '模型目录刷新失败，正在继续使用这段对话上次由 Pi 确认的模型状态。';
  }
  return '模型目录暂时不可用，对话记录仍可查看。';
}
function isMobileViewport(): boolean { return window.matchMedia?.('(max-width: 760px)').matches === true; }
function shouldOpenTaskCenterByDefault(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && !window.matchMedia('(max-width: 1360px)').matches;
}

const PASTED_IMAGE_MIME_TYPES = new Set(['image/png', 'image/jpeg', 'image/gif', 'image/webp']);
const MAX_AGENT_IMAGE_BYTES = 20 * 1024 * 1024;

function latestActiveTurnId(projection?: AgentProjectionState): string {
  if (!projection) return '';
  // The newest visible turn owns retry, stop, and model-change availability.
  // A stale older streaming flag must not revive after a later terminal turn.
  for (let index = projection.turnOrder.length - 1; index >= 0; index -= 1) {
    const turnId = projection.turnOrder[index];
    const turn = turnId ? projection.turnsById[turnId] : undefined;
    if (!turn || (turn.messageIds.length === 0 && turn.activityIds.length === 0)) continue;
    return turn.status === 'queued' || turn.status === 'running' || turn.status === 'waiting'
      ? turnId
      : '';
  }
  return '';
}

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
