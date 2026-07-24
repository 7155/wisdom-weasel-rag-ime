import {
  useCallback,
  useRef,
  useState,
} from 'react';

import type { ControlTransport } from '@/platform/transport';
import {
  contextResourceSelection,
  sameContextResourceSelection,
  sessionWithContextResources,
  type ContextResourceSelection,
} from '../context-resource-profile';
import type { SessionSummary } from '../types';

interface PendingContextResources {
  confirmed: SessionSummary;
  desired: ContextResourceSelection;
  running: boolean;
}

interface ContextResourceCallbacks {
  updateSession: (session: SessionSummary) => void;
  setSessionError: (sessionId: string, value: string) => void;
  errorText: (error: unknown) => string;
}

/**
 * Owns one atomic, optimistic context-resource setting per Session.
 *
 * The UI changes synchronously. Rapid selections coalesce to the latest
 * profile, while the runtime receives all source flags in one request.
 */
export function useContextResourceController({
  transport,
  updateSession,
  setSessionError,
  errorText,
}: {
  transport: ControlTransport;
} & ContextResourceCallbacks) {
  const statesRef = useRef(new Map<string, PendingContextResources>());
  const callbacksRef = useRef<ContextResourceCallbacks>({
    updateSession,
    setSessionError,
    errorText,
  });
  const [changingSessionIds, setChangingSessionIds] = useState<Set<string>>(
    () => new Set(),
  );
  callbacksRef.current = { updateSession, setSessionError, errorText };

  const setChanging = useCallback((sessionId: string, changing: boolean) => {
    setChangingSessionIds((current) => {
      const next = new Set(current);
      if (changing) next.add(sessionId);
      else next.delete(sessionId);
      return next;
    });
  }, []);

  const flush = useCallback(async function flushContextResources(
    sessionId: string,
  ): Promise<void> {
    const state = statesRef.current.get(sessionId);
    if (!state || state.running) return;
    state.running = true;
    try {
      while (!sameContextResourceSelection(
        contextResourceSelection(state.confirmed),
        state.desired,
      )) {
        const target = state.desired;
        const base = state.confirmed;
        try {
          const explicit = base.toolAllowlistMode === 'explicit';
          const response = await transport.request<Record<string, unknown>>({
            pathId: 'agent.session.mode.update',
            params: { sessionId },
            body: {
              mode: base.mode,
              executionMode: base.executionMode ?? 'per_action',
              workspaceRoots: base.workspaceRoots,
              toolProfileVersion: base.toolProfileVersion ?? 'control-center-v1',
              toolAllowlistMode: explicit ? 'explicit' : 'profile',
              ...(explicit ? { allowedTools: base.allowedTools ?? [] } : {}),
              ...target,
            },
          });
          const confirmed = isRecord(response.session)
            ? response.session as unknown as SessionSummary
            : sessionWithContextResources(base, target);
          state.confirmed = confirmed;
          if (
            sameContextResourceSelection(state.desired, target)
            && !sameContextResourceSelection(
              contextResourceSelection(confirmed),
              target,
            )
          ) {
            state.desired = contextResourceSelection(confirmed);
            callbacksRef.current.updateSession(confirmed);
            callbacksRef.current.setSessionError(
              sessionId,
              '上下文资源没有更新。服务端返回的设置与选择不一致。',
            );
            break;
          }
          callbacksRef.current.updateSession(
            sameContextResourceSelection(state.desired, target)
              ? confirmed
              : sessionWithContextResources(confirmed, state.desired),
          );
          callbacksRef.current.setSessionError(sessionId, '');
        } catch (requestError) {
          if (sameContextResourceSelection(state.desired, target)) {
            state.desired = contextResourceSelection(state.confirmed);
            callbacksRef.current.updateSession(state.confirmed);
            callbacksRef.current.setSessionError(
              sessionId,
              `上下文资源没有更新。${callbacksRef.current.errorText(requestError)}`,
            );
            break;
          }
        }
      }
    } finally {
      state.running = false;
      setChanging(sessionId, false);
      if (!sameContextResourceSelection(
        contextResourceSelection(state.confirmed),
        state.desired,
      )) {
        setChanging(sessionId, true);
        queueMicrotask(() => void flushContextResources(sessionId));
      }
    }
  }, [setChanging, transport]);

  const select = useCallback((
    session: SessionSummary,
    desired: ContextResourceSelection,
  ) => {
    if (sameContextResourceSelection(contextResourceSelection(session), desired)) return;
    const state = statesRef.current.get(session.id) ?? {
      confirmed: session,
      desired: contextResourceSelection(session),
      running: false,
    };
    if (!state.running) state.confirmed = session;
    state.desired = desired;
    statesRef.current.set(session.id, state);
    callbacksRef.current.updateSession(sessionWithContextResources(session, desired));
    setChanging(session.id, true);
    if (!state.running) queueMicrotask(() => void flush(session.id));
  }, [flush, setChanging]);

  return {
    changingSessionIds,
    select,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
