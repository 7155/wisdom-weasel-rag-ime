import { useCallback, useEffect, useRef } from 'react';

import { createAgentDeltaBatcher } from '@/contracts/batching';
import type { UiAgentEvent } from '@/contracts/ui-events';
import type { ControlTransport } from '@/platform/transport';
import { agentProjection, useAgentLiveStore } from '../state/live-store';

export type AgentSnapshotView = 'recent' | 'full';
export type AgentRecoveryState = 'recovering' | 'failed' | 'synced';

export interface AgentLiveSnapshot {
  sessionId: string;
  value: unknown;
  view: AgentSnapshotView;
  presentable: boolean;
  hydrated: boolean;
  sequence: number;
  resumeToken: string;
}

export interface AgentLiveSnapshotError {
  sessionId: string;
  view: AgentSnapshotView;
  error: unknown;
  recoverable: boolean;
}

export interface AgentLiveSessionCallbacks {
  onLoadingChange?(loading: boolean): void;
  onRecoveryState?(state: AgentRecoveryState): void;
  onSnapshot?(snapshot: AgentLiveSnapshot): void;
  onSnapshotError?(failure: AgentLiveSnapshotError): void;
  onEvent?(event: UiAgentEvent): void;
  onEvents?(events: readonly UiAgentEvent[]): void;
  onConnectionRestored?(sessionId: string): void;
  onConnectionError?(sessionId: string, error: unknown): void;
}

export interface AgentLiveSnapshotRequest {
  preserveAfterSequence?: number;
  view?: AgentSnapshotView;
}

export type AgentLiveSnapshotLoader = (
  request?: AgentLiveSnapshotRequest,
) => Promise<boolean>;

export interface AgentLiveSessionOptions extends AgentLiveSessionCallbacks {
  sessionId: string;
  transport: ControlTransport;
  active?: boolean;
  live?: boolean;
  snapshotView?: AgentSnapshotView;
}

interface AgentLiveSessionLease {
  loadSnapshot(request?: AgentLiveSnapshotRequest): Promise<boolean>;
  update(options: { live: boolean; snapshotView: AgentSnapshotView }): void;
  release(): void;
}

interface SharedAgentLiveSession {
  attach(
    listener: AgentLiveSessionCallbacks,
    options: { live: boolean; snapshotView: AgentSnapshotView },
  ): AgentLiveSessionLease;
}

interface ListenerState {
  listener: AgentLiveSessionCallbacks;
  live: boolean;
  snapshotView: AgentSnapshotView;
}

const sharedAgentLiveSessions = new WeakMap<
  ControlTransport,
  Map<string, SharedAgentLiveSession>
>();

const AGENT_RECOVERY_BASE_DELAY_MS = 1_000;
const AGENT_RECOVERY_MAX_DELAY_MS = 8_000;
const AGENT_RECOVERY_VISIBLE_FAILURE_ATTEMPT = 3;

export function useAgentLiveSession({
  sessionId,
  transport,
  active: surfaceActive = true,
  live: liveSurface = true,
  snapshotView = 'recent',
  ...callbacks
}: AgentLiveSessionOptions): AgentLiveSnapshotLoader {
  const callbacksRef = useRef<AgentLiveSessionCallbacks>(callbacks);
  const listenerRef = useRef<AgentLiveSessionCallbacks | undefined>(undefined);
  const leaseRef = useRef<AgentLiveSessionLease | undefined>(undefined);
  callbacksRef.current = callbacks;

  if (!listenerRef.current) {
    listenerRef.current = {
      onLoadingChange: (loading) => callbacksRef.current.onLoadingChange?.(loading),
      onRecoveryState: (state) => callbacksRef.current.onRecoveryState?.(state),
      onSnapshot: (snapshot) => callbacksRef.current.onSnapshot?.(snapshot),
      onSnapshotError: (failure) => callbacksRef.current.onSnapshotError?.(failure),
      onEvent: (event) => callbacksRef.current.onEvent?.(event),
      onEvents: (events) => callbacksRef.current.onEvents?.(events),
      onConnectionRestored: (activeSessionId) => callbacksRef.current.onConnectionRestored?.(activeSessionId),
      onConnectionError: (activeSessionId, error) => callbacksRef.current.onConnectionError?.(activeSessionId, error),
    };
  }

  useEffect(() => {
    if (!sessionId || !surfaceActive) {
      leaseRef.current?.release();
      leaseRef.current = undefined;
      callbacksRef.current.onLoadingChange?.(false);
      return;
    }
    const lease = getSharedAgentLiveSession(transport, sessionId).attach(
      listenerRef.current!,
      { live: liveSurface, snapshotView },
    );
    leaseRef.current = lease;
    return () => {
      if (leaseRef.current === lease) leaseRef.current = undefined;
      lease.release();
    };
  }, [sessionId, surfaceActive, transport]);

  useEffect(() => {
    leaseRef.current?.update({ live: liveSurface, snapshotView });
  }, [liveSurface, snapshotView]);

  return useCallback(
    (request?: AgentLiveSnapshotRequest) => (
      leaseRef.current?.loadSnapshot(request) ?? Promise.resolve(false)
    ),
    [],
  );
}

function getSharedAgentLiveSession(
  transport: ControlTransport,
  sessionId: string,
): SharedAgentLiveSession {
  let transportSessions = sharedAgentLiveSessions.get(transport);
  if (!transportSessions) {
    transportSessions = new Map();
    sharedAgentLiveSessions.set(transport, transportSessions);
  }
  const existing = transportSessions.get(sessionId);
  if (existing) return existing;
  let session: SharedAgentLiveSession;
  session = createSharedAgentLiveSession(transport, sessionId, () => {
    if (transportSessions?.get(sessionId) === session) transportSessions.delete(sessionId);
    if (transportSessions?.size === 0) sharedAgentLiveSessions.delete(transport);
  });
  transportSessions.set(sessionId, session);
  return session;
}

function createSharedAgentLiveSession(
  transport: ControlTransport,
  sessionId: string,
  onEmpty: () => void,
): SharedAgentLiveSession {
  const listeners = new Map<AgentLiveSessionCallbacks, ListenerState>();
  let active = false;
  let loading = false;
  let recoveryState: AgentRecoveryState = 'recovering';
  let snapshotAttempted = false;
  let loadedView: AgentSnapshotView | undefined;
  let latestSnapshot: AgentLiveSnapshot | undefined;
  let lastSnapshotError: AgentLiveSnapshotError | undefined;
  let lastConnectionError: unknown;
  let connected = false;
  let snapshotTask: Promise<boolean> | undefined;
  let snapshotController: AbortController | undefined;
  let snapshotGeneration = 0;
  let streamGeneration = 0;
  let unsubscribe: (() => void) | undefined;
  let reloadQueued = false;
  let snapshotReloadPending: AgentLiveSnapshotRequest | undefined;
  let recoveryAttempt = 0;
  let recoveryTimer: ReturnType<typeof setTimeout> | undefined;

  const broadcast = (notify: (listener: AgentLiveSessionCallbacks) => void) => {
    for (const { listener } of listeners.values()) notify(listener);
  };
  const setLoading = (next: boolean) => {
    loading = next;
    broadcast((listener) => listener.onLoadingChange?.(next));
  };
  const setRecoveryState = (next: AgentRecoveryState) => {
    recoveryState = next;
    broadcast((listener) => listener.onRecoveryState?.(next));
  };
  const clearRecoveryTimer = () => {
    if (recoveryTimer === undefined) return;
    clearTimeout(recoveryTimer);
    recoveryTimer = undefined;
  };
  const resetRecoveryBackoff = () => {
    recoveryAttempt = 0;
    clearRecoveryTimer();
  };
  const scheduleAutomaticRecovery = () => {
    if (!active || !shouldStream() || recoveryTimer !== undefined) return;
    const delayMs = Math.min(
      AGENT_RECOVERY_BASE_DELAY_MS * (2 ** recoveryAttempt),
      AGENT_RECOVERY_MAX_DELAY_MS,
    );
    recoveryAttempt += 1;
    setRecoveryState(
      recoveryAttempt >= AGENT_RECOVERY_VISIBLE_FAILURE_ATTEMPT
        ? 'failed'
        : 'recovering',
    );
    recoveryTimer = setTimeout(() => {
      recoveryTimer = undefined;
      if (!active || !shouldStream()) return;
      void loadSnapshot({
        preserveAfterSequence: agentProjection(sessionId).lastSequence,
      });
    }, delayMs);
  };
  const preferredSnapshotView = (): AgentSnapshotView => (
    [...listeners.values()].some(({ snapshotView }) => snapshotView === 'full')
      ? 'full'
      : 'recent'
  );
  const shouldStream = (): boolean => [...listeners.values()].some(({ live }) => live);
  const currentResumeToken = (): string => (
    agentProjection(sessionId).resumeToken
      || latestSnapshot?.resumeToken
      || ''
  );
  const clearStream = () => {
    streamGeneration += 1;
    const cancel = unsubscribe;
    unsubscribe = undefined;
    connected = false;
    batcher.clear();
    cancel?.();
  };
  const mergeSnapshotRequests = (
    current: AgentLiveSnapshotRequest | undefined,
    next: AgentLiveSnapshotRequest,
  ): AgentLiveSnapshotRequest => ({
    ...(current?.view === 'full' || next.view === 'full' || preferredSnapshotView() === 'full'
      ? { view: 'full' as const }
      : { view: 'recent' as const }),
    ...(
      current?.preserveAfterSequence === undefined && next.preserveAfterSequence === undefined
        ? {}
        : {
            preserveAfterSequence: Math.max(
              current?.preserveAfterSequence ?? -1,
              next.preserveAfterSequence ?? -1,
            ),
          }
    ),
  });
  const scheduleSnapshotReload = (request: AgentLiveSnapshotRequest = {}) => {
    if (!active) return;
    snapshotReloadPending = mergeSnapshotRequests(snapshotReloadPending, {
      ...request,
      view: request.view ?? preferredSnapshotView(),
    });
    if (snapshotTask || reloadQueued) return;
    reloadQueued = true;
    queueMicrotask(() => {
      reloadQueued = false;
      const pending = snapshotReloadPending;
      snapshotReloadPending = undefined;
      if (active) void loadSnapshot(pending);
    });
  };
  const batcher = createAgentDeltaBatcher((events) => {
    if (!active) return;
    const needsSnapshot = useAgentLiveStore.getState().applyEvents(sessionId, events);
    if (needsSnapshot) {
      scheduleSnapshotReload({
        preserveAfterSequence: events.at(-1)?.sequence,
      });
    } else {
      broadcast((listener) => listener.onEvents?.(events));
    }
  });

  function requestSnapshotValue(
    view: AgentSnapshotView,
    signal: AbortSignal,
  ): Promise<unknown> {
    return transport.request({
      pathId: 'agent.session.snapshot',
      params: { sessionId },
      ...(view === 'recent' ? { query: { view: 'recent' as const } } : {}),
      signal,
    });
  }

  async function performSnapshot(
    request: AgentLiveSnapshotRequest,
    requestId: number,
    controller: AbortController,
  ): Promise<boolean> {
    let requestedView = request.view ?? preferredSnapshotView();
    let value: unknown = undefined;
    try {
      while (true) {
        try {
          value = await requestSnapshotValue(requestedView, controller.signal);
        } catch (error) {
          if (requestedView === 'recent' && preferredSnapshotView() === 'full') {
            requestedView = 'full';
            continue;
          }
          throw error;
        }
        if (!isCurrentSnapshot(requestId, controller)) return false;
        if (requestedView === 'recent' && preferredSnapshotView() === 'full') {
          requestedView = 'full';
          continue;
        }
        break;
      }
      if (!isCurrentSnapshot(requestId, controller)) return false;
      const recent = isRecentAgentSnapshot(value);
      const actualView: AgentSnapshotView = recent ? 'recent' : 'full';
      const presentable = actualView === 'full' || recentAgentSnapshotIsPresentable(value);
      const sequence = agentSnapshotSequence(value);
      const resumeToken = agentSnapshotResumeToken(value);
      const shouldHydrate = presentable
        && (
          request.preserveAfterSequence === undefined
          || sequence > request.preserveAfterSequence
        );
      if (shouldHydrate) useAgentLiveStore.getState().hydrate(sessionId, value);
      const snapshot = {
        sessionId,
        value,
        view: actualView,
        presentable,
        hydrated: shouldHydrate,
        sequence,
        resumeToken,
      };
      snapshotAttempted = true;
      loadedView = actualView;
      latestSnapshot = snapshot;
      lastSnapshotError = undefined;
      setLoading(false);
      broadcast((listener) => listener.onSnapshot?.(snapshot));
      if (shouldStream()) maybeSubscribe();
      else setRecoveryState('synced');
      return true;
    } catch (error) {
      if (!isCurrentSnapshot(requestId, controller) || isAbortError(error)) return false;
      snapshotAttempted = true;
      const recoverable = requestedView === 'recent' && preferredSnapshotView() !== 'full';
      const failure = {
        sessionId,
        view: requestedView,
        error,
        recoverable,
      };
      lastSnapshotError = failure;
      setLoading(false);
      setRecoveryState('failed');
      broadcast((listener) => listener.onSnapshotError?.(failure));
      if (recoverable && shouldStream()) {
        maybeSubscribe();
        return true;
      }
      return false;
    }
  }

  function isCurrentSnapshot(requestId: number, controller: AbortController): boolean {
    return active && requestId === snapshotGeneration && !controller.signal.aborted;
  }

  function shouldRunPendingRequest(request: AgentLiveSnapshotRequest): boolean {
    if (!active) return false;
    const projection = agentProjection(sessionId);
    return projection.needsSnapshot
      || (
        request.view === 'full'
        && loadedView !== 'full'
      )
      || (
        request.preserveAfterSequence !== undefined
        && projection.lastSequence < request.preserveAfterSequence
      );
  }

  function startSnapshot(request: AgentLiveSnapshotRequest): Promise<boolean> {
    clearRecoveryTimer();
    clearStream();
    batcher.clear();
    const requestId = ++snapshotGeneration;
    const controller = new AbortController();
    snapshotController = controller;
    setRecoveryState('recovering');
    setLoading(true);
    let task: Promise<boolean>;
    task = performSnapshot(request, requestId, controller).finally(() => {
      if (snapshotTask === task) snapshotTask = undefined;
      if (snapshotController === controller) snapshotController = undefined;
      const pending = snapshotReloadPending;
      snapshotReloadPending = undefined;
      if (active && pending && shouldRunPendingRequest(pending)) scheduleSnapshotReload(pending);
    });
    snapshotTask = task;
    return task;
  }
  function loadSnapshot(request: AgentLiveSnapshotRequest = {}): Promise<boolean> {
    if (!active) return Promise.resolve(false);
    const normalized = {
      ...request,
      view: request.view ?? preferredSnapshotView(),
    };
    if (snapshotTask) {
      snapshotReloadPending = mergeSnapshotRequests(snapshotReloadPending, normalized);
      return snapshotTask;
    }
    if (reloadQueued) {
      snapshotReloadPending = mergeSnapshotRequests(snapshotReloadPending, normalized);
      return Promise.resolve(true);
    }
    return startSnapshot(normalized);
  }

  function maybeSubscribe(): void {
    if (!active || !shouldStream() || !snapshotAttempted || unsubscribe) return;
    const subscriptionGeneration = ++streamGeneration;
    try {
      unsubscribe = transport.subscribe<UiAgentEvent>(
        {
          pathId: 'agent.session.events',
          params: { sessionId },
          lastEventId: currentResumeToken(),
        },
        {
          open: () => {
            if (!active || subscriptionGeneration !== streamGeneration) return;
            resetRecoveryBackoff();
            connected = true;
            lastConnectionError = undefined;
            broadcast((listener) => listener.onConnectionRestored?.(sessionId));
          },
          next: (event) => {
            if (!active || subscriptionGeneration !== streamGeneration) return;
            if (event.eventType === 'snapshot_required') {
              batcher.flush();
              const needsSnapshot = useAgentLiveStore.getState().applyEvents(sessionId, [event]);
              broadcast((listener) => listener.onEvent?.(event));
              if (needsSnapshot) {
                scheduleSnapshotReload({ preserveAfterSequence: event.sequence });
              }
              return;
            }
            batcher.push(event);
            broadcast((listener) => listener.onEvent?.(event));
          },
          error: (error) => {
            if (!active || subscriptionGeneration !== streamGeneration) return;
            unsubscribe?.();
            unsubscribe = undefined;
            streamGeneration += 1;
            connected = false;
            lastConnectionError = error;
            setRecoveryState('recovering');
            broadcast((listener) => listener.onConnectionError?.(sessionId, error));
            scheduleAutomaticRecovery();
          },
        },
      );
    } catch (error) {
      if (!active || subscriptionGeneration !== streamGeneration) return;
      connected = false;
      lastConnectionError = error;
      setRecoveryState('recovering');
      broadcast((listener) => listener.onConnectionError?.(sessionId, error));
      scheduleAutomaticRecovery();
    }
  }

  function reconcileOptions(): void {
    if (!active) return;
    if (!shouldStream()) {
      if (unsubscribe) clearStream();
    } else if (snapshotAttempted) {
      maybeSubscribe();
    }
    if (preferredSnapshotView() === 'full' && loadedView !== 'full') {
      void loadSnapshot({ view: 'full' });
    }
  }

  function stop(): void {
    active = false;
    clearRecoveryTimer();
    snapshotGeneration += 1;
    snapshotController?.abort();
    snapshotController = undefined;
    clearStream();
    batcher.clear();
    snapshotReloadPending = undefined;
    reloadQueued = false;
    loading = false;
    snapshotAttempted = false;
    loadedView = undefined;
    latestSnapshot = undefined;
    lastSnapshotError = undefined;
    lastConnectionError = undefined;
  }

  return {
    attach(listener, options) {
      const alreadyRunning = active;
      listeners.set(listener, { listener, ...options });
      if (!alreadyRunning) {
        active = true;
        useAgentLiveStore.getState().ensure(sessionId);
        void loadSnapshot({ view: preferredSnapshotView() });
      } else {
        listener.onLoadingChange?.(loading);
        listener.onRecoveryState?.(recoveryState);
        if (lastConnectionError !== undefined) listener.onConnectionError?.(sessionId, lastConnectionError);
        else if (connected) listener.onConnectionRestored?.(sessionId);
        reconcileOptions();
      }
      let released = false;
      return {
        loadSnapshot,
        update(nextOptions) {
          if (released || !listeners.has(listener)) return;
          const previousView = preferredSnapshotView();
          const previousLive = shouldStream();
          listeners.set(listener, { listener, ...nextOptions });
          const nextView = preferredSnapshotView();
          const nextLive = shouldStream();
          if (previousLive !== nextLive || previousView !== nextView) reconcileOptions();
        },
        release() {
          if (released) return;
          released = true;
          const previousLive = shouldStream();
          listeners.delete(listener);
          if (listeners.size > 0) {
            if (previousLive !== shouldStream()) reconcileOptions();
            return;
          }
          stop();
          onEmpty();
        },
      };
    },
  };
}

export function isRecentAgentSnapshot(value: unknown): boolean {
  return isRecord(value)
    && value.snapshotScope === 'recent'
    && value.partial === true;
}

export function recentAgentSnapshotIsPresentable(value: unknown): boolean {
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

function agentSnapshotSequence(value: unknown): number {
  if (!isRecord(value)) return -1;
  return typeof value.lastSequence === 'number' && Number.isFinite(value.lastSequence)
    ? value.lastSequence
    : -1;
}

function agentSnapshotResumeToken(value: unknown): string {
  if (!isRecord(value)) return '';
  return typeof value.resumeToken === 'string'
    ? value.resumeToken
    : typeof value.lastEventId === 'string'
      ? value.lastEventId
      : '';
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isAbortError(value: unknown): boolean {
  return value instanceof DOMException && value.name === 'AbortError';
}
