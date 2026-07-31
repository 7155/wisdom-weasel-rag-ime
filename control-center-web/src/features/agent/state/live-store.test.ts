import { afterEach, describe, expect, it } from 'vitest';
import type { AgentSnapshot } from '@/contracts/agent-reducer';
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
});
