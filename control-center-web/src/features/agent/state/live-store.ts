import { create } from 'zustand';
import {
  applyAgentBackgroundJobReceipt,
  acknowledgeOptimisticAgentMessage,
  abortAgentTurn,
  agentSnapshotFromResponse,
  appendOptimisticAgentMessage,
  applyAgentSnapshot,
  createAgentProjection,
  discardOptimisticAgentMessage,
  failOptimisticAgentMessage,
  requeueOptimisticAgentMessage,
  reduceAgentEvents,
  rewriteOptimisticAgentMessage,
  type AgentProjectionState,
  type AgentSnapshot,
} from '@/contracts/agent-reducer';
import type { UiAgentEvent } from '@/contracts/ui-events';

interface AgentLiveStore {
  projections: Record<string, AgentProjectionState>;
  ensure(sessionId: string): void;
  hydrate(sessionId: string, value: unknown): void;
  hydrateSnapshot(sessionId: string, snapshot: AgentSnapshot): void;
  applyEvents(sessionId: string, events: readonly UiAgentEvent[]): boolean;
  applyBackgroundJobReceipt(sessionId: string, receipt: unknown): boolean;
  appendOptimistic(
    sessionId: string,
    input: {
      clientMessageId: string;
      retryOfClientMessageId?: string;
      text: string;
      attachments?: string[];
      nowMs: number;
      turnId?: string;
      delivery?: 'prompt' | 'steer' | 'followUp';
    },
  ): void;
  rewriteOptimistic(
    sessionId: string,
    targetMessageId: string,
    input: {
      clientMessageId: string;
      text: string;
      attachments?: string[];
      nowMs: number;
    },
  ): void;
  discardOptimistic(sessionId: string, clientMessageId: string): void;
  failOptimistic(
    sessionId: string,
    clientMessageId: string,
    error: string,
    nowMs: number,
    admissionState?: 'ambiguous' | 'pending' | 'unresolved',
  ): void;
  requeueOptimistic(
    sessionId: string,
    clientMessageId: string,
    nowMs: number,
  ): void;
  acknowledgeOptimistic(sessionId: string, clientMessageId: string, nowMs: number): void;
  abortTurn(sessionId: string, turnId: string, nowMs: number): void;
  clear(sessionId: string): void;
}

export const useAgentLiveStore = create<AgentLiveStore>((set, get) => ({
  projections: {},
  ensure(sessionId) {
    if (!sessionId || get().projections[sessionId]) return;
    set((state) => ({
      projections: {
        ...state.projections,
        [sessionId]: createAgentProjection(sessionId),
      },
    }));
  },
  hydrate(sessionId, value) {
    get().hydrateSnapshot(sessionId, agentSnapshotFromResponse(value));
  },
  hydrateSnapshot(sessionId, snapshot) {
    const current = get().projections[sessionId] ?? createAgentProjection(sessionId);
    if (snapshot.lastSequence < current.lastSequence) return;
    const projection = applyAgentSnapshot(current, normalizeLegacyHistoryTurns(snapshot));
    set((state) => ({
      projections: { ...state.projections, [sessionId]: projection },
    }));
  },
  applyEvents(sessionId, events) {
    const current = get().projections[sessionId] ?? createAgentProjection(sessionId);
    const projection = reduceAgentEvents(current, events);
    if (projection === current) return current.needsSnapshot;
    set((state) => ({
      projections: { ...state.projections, [sessionId]: projection },
    }));
    return projection.needsSnapshot;
  },
  applyBackgroundJobReceipt(sessionId, receipt) {
    const current = get().projections[sessionId] ?? createAgentProjection(sessionId);
    const projection = applyAgentBackgroundJobReceipt(current, receipt);
    if (projection === current) return false;
    set((state) => ({
      projections: { ...state.projections, [sessionId]: projection },
    }));
    return true;
  },
  appendOptimistic(sessionId, input) {
    const current = get().projections[sessionId] ?? createAgentProjection(sessionId);
    const projection = appendOptimisticAgentMessage(current, input);
    set((state) => ({
      projections: { ...state.projections, [sessionId]: projection },
    }));
  },
  rewriteOptimistic(sessionId, targetMessageId, input) {
    const current = get().projections[sessionId] ?? createAgentProjection(sessionId);
    const projection = rewriteOptimisticAgentMessage(current, targetMessageId, input);
    set((state) => ({
      projections: { ...state.projections, [sessionId]: projection },
    }));
  },
  discardOptimistic(sessionId, clientMessageId) {
    const current = get().projections[sessionId];
    if (!current) return;
    const projection = discardOptimisticAgentMessage(current, clientMessageId);
    set((state) => ({
      projections: { ...state.projections, [sessionId]: projection },
    }));
  },
  failOptimistic(
    sessionId,
    clientMessageId,
    error,
    nowMs,
    admissionState,
  ) {
    const current = get().projections[sessionId];
    if (!current) return;
    const projection = failOptimisticAgentMessage(
      current,
      clientMessageId,
      error,
      nowMs,
      admissionState,
    );
    set((state) => ({
      projections: { ...state.projections, [sessionId]: projection },
    }));
  },
  requeueOptimistic(sessionId, clientMessageId, nowMs) {
    const current = get().projections[sessionId];
    if (!current) return;
    const projection = requeueOptimisticAgentMessage(
      current,
      clientMessageId,
      nowMs,
    );
    set((state) => ({
      projections: { ...state.projections, [sessionId]: projection },
    }));
  },
  acknowledgeOptimistic(sessionId, clientMessageId, nowMs) {
    const current = get().projections[sessionId];
    if (!current) return;
    const projection = acknowledgeOptimisticAgentMessage(
      current,
      clientMessageId,
      nowMs,
    );
    if (projection === current) return;
    set((state) => ({
      projections: { ...state.projections, [sessionId]: projection },
    }));
  },
  abortTurn(sessionId, turnId, nowMs) {
    const current = get().projections[sessionId];
    if (!current) return;
    const projection = abortAgentTurn(current, turnId, nowMs);
    set((state) => ({
      projections: { ...state.projections, [sessionId]: projection },
    }));
  },
  clear(sessionId) {
    set((state) => {
      const projections = { ...state.projections };
      delete projections[sessionId];
      return { projections };
    });
  },
}));

export function agentProjection(sessionId: string): AgentProjectionState {
  return (
    useAgentLiveStore.getState().projections[sessionId] ?? createAgentProjection(sessionId)
  );
}

function normalizeLegacyHistoryTurns(snapshot: AgentSnapshot): AgentSnapshot {
  let currentTurnId = '';
  let changed = false;
  const messages = snapshot.messages.map((rawMessage, index) => {
    if (!isRecord(rawMessage) || rawMessage.turnId !== 'history') {
      currentTurnId = '';
      return rawMessage;
    }
    const role = typeof rawMessage.role === 'string' ? rawMessage.role : '';
    if (role === 'user' || !currentTurnId) {
      const messageId = typeof rawMessage.id === 'string' && rawMessage.id
        ? rawMessage.id
        : String(index);
      currentTurnId = `history:${messageId}`;
    }
    changed = true;
    return { ...rawMessage, turnId: currentTurnId };
  });
  return changed ? { ...snapshot, messages } : snapshot;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
