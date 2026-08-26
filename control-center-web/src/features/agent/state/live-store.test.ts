import { afterEach, describe, expect, it } from 'vitest';
import type { AgentSnapshot } from '@/contracts/agent-reducer';
import { parseAgentEvent } from '@/contracts/validators';
import { useAgentLiveStore } from './live-store';

const sessionId = 'session-room-managed';

afterEach(() => {
  useAgentLiveStore.getState().clear(sessionId);
});

describe('Agent live store snapshot hydration', () => {
  it('keeps a newer confirmed projection when reconnect hydration returns an older snapshot', () => {
    const confirmedSnapshot: AgentSnapshot = {
      messages: [],
      liveEvents: [],
      lastSequence: 8,
      resumeToken: `${sessionId}:8`,
      status: 'working',
    };
    const store = useAgentLiveStore.getState();
    store.hydrateSnapshot(sessionId, confirmedSnapshot);
    const confirmed = useAgentLiveStore.getState().projections[sessionId];

    store.hydrateSnapshot(sessionId, {
      ...confirmedSnapshot,
      lastSequence: 5,
      resumeToken: `${sessionId}:5`,
      status: 'idle',
    });

    expect(useAgentLiveStore.getState().projections[sessionId]).toBe(confirmed);
    expect(useAgentLiveStore.getState().projections[sessionId]).toMatchObject({
      lastSequence: 8,
      resumeToken: `${sessionId}:8`,
      status: 'working',
    });
  });

  it('does not leave an equal-cursor history alias active after the real turn completes', () => {
    const clientMessageId = 'client-equal-cursor-race';
    const store = useAgentLiveStore.getState();
    store.appendOptimistic(sessionId, {
      clientMessageId,
      text: '检查完成后告诉我结果',
      nowMs: 10,
    });
    store.applyEvents(sessionId, [event(1, 'turn-real', 'message_completed', {
      clientMessageId,
      message: message('runtime-user', 'user', 'turn-real', '检查完成后告诉我结果'),
    })]);
    store.hydrateSnapshot(sessionId, {
      messages: [message('history-user', 'user', 'history', '检查完成后告诉我结果')],
      liveEvents: [],
      lastSequence: 1,
      resumeToken: `${sessionId}:1`,
      status: 'busy',
    });
    store.applyEvents(sessionId, [
      event(2, 'turn-real', 'message_completed', {
        message: message('runtime-assistant', 'assistant', 'turn-real', '检查完成。'),
      }),
      event(3, 'turn-real', 'turn_completed', { status: 'completed' }),
    ]);

    const settled = useAgentLiveStore.getState().projections[sessionId];
    expect(settled.status).toBe('idle');
    expect(settled.turnsById['turn-real']?.status).toBe('completed');
    expect(settled.turnsById['history:history-user']).toBeUndefined();
    expect(settled.turnOrder.filter((turnId) => (
      ['queued', 'running', 'waiting'].includes(settled.turnsById[turnId]?.status ?? '')
    ))).toEqual([]);
  });
});

function event(
  sequence: number,
  turnId: string,
  eventType: string,
  payload: Record<string, unknown>,
) {
  return parseAgentEvent({
    schemaVersion: 'rag-ime.agent-event.v1',
    eventId: `${sessionId}:${sequence}`,
    sessionId,
    turnId,
    sequence,
    createdAtMs: sequence * 10,
    eventType,
    payload,
    resumeToken: `${sessionId}:${sequence}`,
  });
}

function message(
  id: string,
  role: 'user' | 'assistant',
  turnId: string,
  text: string,
) {
  return {
    schemaVersion: 'rag-ime.agent-message.v1',
    id,
    sessionId,
    turnId,
    role,
    status: 'completed',
    blocks: [{
      id: `${id}:text`,
      type: 'text',
      status: 'completed',
      presentationKind: 'markdown',
      data: { text },
    }],
    attachments: [],
    citations: [],
    createdAtMs: 20,
    completedAtMs: 21,
  };
}
