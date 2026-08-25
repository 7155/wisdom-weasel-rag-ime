import { cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { TooltipProvider } from '@/components/primitives';
import type { UiAgentMessage } from '@/contracts/ui-events';
import { useAgentLiveStore } from '../state/live-store';
import { AgentTurn, clearAgentTimelineScrollMemory } from './AgentTimeline';

const sessionId = 'session-scroll-anchor';

function message(
  turnId: string,
  role: 'user' | 'assistant',
  value: string,
  createdAtMs: number,
): UiAgentMessage {
  return {
    schemaVersion: 'rag-ime.agent-message.v1',
    id: `${turnId}:${role}`,
    sessionId,
    turnId,
    role,
    status: 'completed',
    blocks: [{
      id: `${turnId}:${role}:text`,
      type: 'text',
      status: 'completed',
      presentationKind: 'markdown',
      data: { text: value },
    }],
    attachments: [],
    citations: [],
    createdAtMs,
    completedAtMs: createdAtMs,
  };
}

afterEach(() => {
  cleanup();
  clearAgentTimelineScrollMemory();
  useAgentLiveStore.getState().clear(sessionId);
});

describe('Session transcript scroll anchor', () => {
  it('gives a turn the stable row key an anchor is remembered by', () => {
    const turnId = 'turn-anchored';
    useAgentLiveStore.getState().hydrateSnapshot(sessionId, {
      messages: [
        message(turnId, 'user', '第一个问题', 1),
        message(turnId, 'assistant', '第一个回答', 2),
      ],
      liveEvents: [],
      lastSequence: 0,
      resumeToken: '',
      status: 'idle',
    });

    const { container } = render(
      <TooltipProvider>
        <AgentTurn onApprovalDecision={() => {}} sessionId={sessionId} turnId={turnId} />
      </TooltipProvider>,
    );

    // A turn id, not a list position: an edit, retry or fork renumbers
    // positions while the reader is still looking at the same turn, so the
    // anchor has to be remembered by identity.
    expect(container.querySelector('[data-agent-turn-id]'))
      .toHaveAttribute('data-agent-turn-id', turnId);
  });
});
