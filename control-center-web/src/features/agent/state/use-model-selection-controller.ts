import {
  useCallback,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from 'react';

import type { ControlTransport } from '@/platform/transport';
import {
  catalogWithConfigurationEvent,
  catalogWithModelSelection,
  modelSelectionFromCatalog,
  sameModelSelection,
  type AgentModelSelection,
} from '../model-selection';
import {
  isModelCatalog,
  type ModelCatalog,
  type SessionSummary,
} from '../types';

interface PendingModelSelection {
  confirmed: ModelCatalog;
  desired?: AgentModelSelection;
  running: boolean;
}

interface ModelSelectionCallbacks {
  selectedSessionId: string;
  setCatalog: Dispatch<SetStateAction<ModelCatalog | undefined>>;
  updateSession: (session: SessionSummary) => void;
  setSessionError: (sessionId: string, value: string) => void;
  errorText: (error: unknown) => string;
}

/**
 * Owns the complete optimistic model-selection lifecycle.
 *
 * The UI updates immediately, while provider writes are serialized per
 * Session. Rapid clicks coalesce to the latest desired selection and a failed
 * write rolls back to the last catalog confirmed by Pi.
 */
export function useModelSelectionController({
  transport,
  selectedSessionId,
  setCatalog,
  updateSession,
  setSessionError,
  errorText,
}: {
  transport: ControlTransport;
} & ModelSelectionCallbacks) {
  const selectionsRef = useRef(new Map<string, PendingModelSelection>());
  const callbacksRef = useRef<ModelSelectionCallbacks>({
    selectedSessionId,
    setCatalog,
    updateSession,
    setSessionError,
    errorText,
  });
  const [changingSessionIds, setChangingSessionIds] = useState<Set<string>>(
    () => new Set(),
  );
  callbacksRef.current = {
    selectedSessionId,
    setCatalog,
    updateSession,
    setSessionError,
    errorText,
  };

  const setChanging = useCallback((sessionId: string, changing: boolean) => {
    setChangingSessionIds((current) => {
      const next = new Set(current);
      if (changing) next.add(sessionId);
      else next.delete(sessionId);
      return next;
    });
  }, []);

  const flush = useCallback(async function flushSelection(
    sessionId: string,
  ): Promise<void> {
    const state = selectionsRef.current.get(sessionId);
    if (!state || state.running) return;
    state.running = true;
    try {
      while (state.desired) {
        const target = state.desired;
        const confirmedSelection = modelSelectionFromCatalog(state.confirmed);
        if (sameModelSelection(confirmedSelection, target)) break;
        try {
          const modelChanged = (
            confirmedSelection?.provider !== target.provider
            || confirmedSelection?.modelId !== target.modelId
          );
          if (modelChanged) {
            const response = await transport.request<Record<string, unknown>>({
              pathId: 'agent.session.model.select',
              params: { sessionId },
              body: { provider: target.provider, modelId: target.modelId },
            });
            if (isRecord(response.session)) {
              callbacksRef.current.updateSession(
                response.session as unknown as SessionSummary,
              );
            }
          }
          if (modelChanged || confirmedSelection?.level !== target.level) {
            await transport.request({
              pathId: 'agent.session.thinking.select',
              params: { sessionId },
              body: { level: target.level },
            });
          }
          const refreshed = await transport.request({
            pathId: 'agent.session.models',
            params: { sessionId },
          });
          if (!isModelCatalog(refreshed)) {
            throw new Error('Pi 没有返回有效的模型目录。');
          }
          state.confirmed = refreshed;
          if (
            sameModelSelection(state.desired, target)
            && !sameModelSelection(modelSelectionFromCatalog(refreshed), target)
          ) {
            state.desired = modelSelectionFromCatalog(refreshed);
            publishCatalog(sessionId, refreshed);
            callbacksRef.current.setSessionError(
              sessionId,
              '模型设置没有更新。Pi 返回的模型状态与刚才的选择不一致。',
            );
            break;
          }
          publishCatalog(
            sessionId,
            sameModelSelection(state.desired, target)
              ? refreshed
              : catalogWithModelSelection(refreshed, state.desired),
          );
          callbacksRef.current.setSessionError(sessionId, '');
        } catch (requestError) {
          let recovered = state.confirmed;
          try {
            const refreshed = await transport.request({
              pathId: 'agent.session.models',
              params: { sessionId },
            });
            if (isModelCatalog(refreshed)) recovered = refreshed;
          } catch {
            // The last confirmed catalog remains the rollback point.
          }
          state.confirmed = recovered;
          if (sameModelSelection(state.desired, target)) {
            state.desired = modelSelectionFromCatalog(recovered);
            publishCatalog(sessionId, recovered);
            callbacksRef.current.setSessionError(
              sessionId,
              `模型设置没有更新。${callbacksRef.current.errorText(requestError)}`,
            );
            break;
          }
        }
        if (sameModelSelection(state.desired, target)) break;
      }
    } finally {
      state.running = false;
      setChanging(sessionId, false);
      const finalSelection = modelSelectionFromCatalog(state.confirmed);
      if (state.desired && !sameModelSelection(state.desired, finalSelection)) {
        setChanging(sessionId, true);
        queueMicrotask(() => void flushSelection(sessionId));
      }
    }
  }, [setChanging, transport]);

  const acceptConfirmedCatalog = useCallback((
    sessionId: string,
    nextCatalog: ModelCatalog,
  ) => {
    const state = selectionsRef.current.get(sessionId);
    const pendingDesired = Boolean(
      state?.desired
      && !sameModelSelection(
        state.desired,
        modelSelectionFromCatalog(state.confirmed),
      ),
    );
    if (state && (state.running || pendingDesired)) {
      state.confirmed = nextCatalog;
      publishCatalog(
        sessionId,
        state.desired
          ? catalogWithModelSelection(nextCatalog, state.desired)
          : nextCatalog,
      );
      return;
    }
    selectionsRef.current.set(sessionId, {
      confirmed: nextCatalog,
      desired: modelSelectionFromCatalog(nextCatalog),
      running: false,
    });
    publishCatalog(sessionId, nextCatalog);
  }, []);

  const applyConfigurationEvent = useCallback((
    sessionId: string,
    payload: Record<string, unknown>,
  ) => {
    const kind = typeof payload.kind === 'string' ? payload.kind : '';
    if (kind !== 'model' && kind !== 'thinking') return;
    const state = selectionsRef.current.get(sessionId);
    if (state?.running || callbacksRef.current.selectedSessionId !== sessionId) return;
    callbacksRef.current.setCatalog((current) => {
      if (!current || current.sessionId !== sessionId) return current;
      const next = catalogWithConfigurationEvent(current, payload);
      selectionsRef.current.set(sessionId, {
        confirmed: next,
        desired: modelSelectionFromCatalog(next),
        running: false,
      });
      return next;
    });
  }, []);

  const select = useCallback((
    sessionId: string,
    catalog: ModelCatalog,
    desired: AgentModelSelection,
  ) => {
    if (sameModelSelection(modelSelectionFromCatalog(catalog), desired)) return;
    const current = selectionsRef.current.get(sessionId);
    const state = current ?? {
      confirmed: catalog,
      desired: modelSelectionFromCatalog(catalog),
      running: false,
    };
    state.desired = desired;
    selectionsRef.current.set(sessionId, state);
    publishCatalog(sessionId, catalogWithModelSelection(catalog, desired));
    setChanging(sessionId, true);
    if (!state.running) queueMicrotask(() => void flush(sessionId));
  }, [flush, setChanging]);

  function publishCatalog(sessionId: string, catalog: ModelCatalog): void {
    if (callbacksRef.current.selectedSessionId === sessionId) {
      callbacksRef.current.setCatalog(catalog);
    }
  }

  return {
    acceptConfirmedCatalog,
    applyConfigurationEvent,
    changingSessionIds,
    select,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
