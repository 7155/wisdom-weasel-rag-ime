import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { UiAgentMessage } from '@/contracts/ui-events';
import { agentEventFixture } from '@/test/fixtures/events';
import agentFxCss from '@/paw-os/styles/paw-os-agent-fx.css?raw';
import { useAgentLiveStore } from '../state/live-store';
import agentCss from '../agent.css?raw';
import { AgentTurn } from './AgentTimeline';

afterEach(() => {
  cleanup();
  useAgentLiveStore.getState().clear('session-status-polish');
});

describe('conversation status polish', () => {
  it('removes the thinking status as soon as the turn receives a terminal event', () => {
    const sessionId = 'session-status-polish';
    const turnId = 'turn-status-polish';
    useAgentLiveStore.getState().hydrateSnapshot(sessionId, {
      messages: [userMessage(sessionId, turnId)],
      liveEvents: [],
      lastSequence: 0,
      resumeToken: '',
      status: 'busy',
      partial: true,
    });

    const { container } = render(
      <AgentTurn sessionId={sessionId} turnId={turnId} onApprovalDecision={() => {}} />,
    );
    expect(screen.getByRole('status')).toHaveClass('agent-assistant-pending');
    expect(container.querySelector('[data-turn-status="running"]')).toBeInTheDocument();

    act(() => useAgentLiveStore.getState().applyEvents(sessionId, [
      {
        ...agentEventFixture(1, 'turn_completed', { status: 'completed' }),
        eventId: `${sessionId}:1`,
        sessionId,
        turnId,
      },
    ]));

    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(container.querySelector('.agent-assistant-pending')).not.toBeInTheDocument();
  });

  it('keeps ordinary and PAWOS thinking states content-sized without a card surface', () => {
    expect(agentCss).toMatch(/\.agent-assistant-pending \{[^}]*display: inline-flex;/);
    expect(agentCss).toMatch(/\.agent-assistant-pending \{[^}]*width: fit-content;/);
    expect(agentCss).toMatch(/\.agent-assistant-pending \{[^}]*min-height: 0;/);
    expect(agentCss).toMatch(/\.agent-assistant-pending \{[^}]*border: 0;/);
    expect(agentFxCss).toMatch(/\.agent-assistant-pending \{[^}]*width: fit-content;/);
    expect(agentFxCss).toMatch(/\.agent-assistant-pending \{[^}]*box-shadow: none;/);
  });

  it('keeps terminal failures as a compact recoverable inline notice', () => {
    const sessionId = 'session-status-polish';
    const turnId = 'turn-status-polish';
    useAgentLiveStore.getState().hydrateSnapshot(sessionId, {
      messages: [userMessage(sessionId, turnId)],
      liveEvents: [{
        ...agentEventFixture(1, 'turn_failed', { error: '503 upstream request failed' }),
        eventId: `${sessionId}:1`,
        sessionId,
        turnId,
      }],
      lastSequence: 1,
      resumeToken: `${sessionId}:1`,
      status: 'faulted',
    });

    render(
      <AgentTurn
        sessionId={sessionId}
        turnId={turnId}
        onApprovalDecision={() => {}}
        onRetryTurn={() => true}
        onSwitchModel={() => {}}
      />,
    );

    const failure = screen.getByRole('alert');
    expect(failure).toHaveClass('agent-turn__failure');
    expect(failure).toHaveTextContent('本轮未完成');
    expect(screen.getByRole('button', { name: '重试本轮' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '切换模型' })).toBeInTheDocument();
    expect(agentCss).toMatch(/\.agent-turn__failure \{[^}]*width: fit-content;/);
    expect(agentCss).toMatch(/\.agent-turn__failure \{[^}]*min-height: 0;/);
    expect(agentCss).toMatch(/\.agent-turn__failure \{[^}]*border: 0;/);
    expect(agentFxCss).toMatch(/\.agent-turn__failure \{[^}]*background: transparent;/);
  });
});

function userMessage(sessionId: string, turnId: string): UiAgentMessage {
  return {
    schemaVersion: 'rag-ime.agent-message.v1',
    id: `${turnId}:user`,
    sessionId,
    turnId,
    role: 'user',
    status: 'completed',
    blocks: [{
      id: `${turnId}:user:text`,
      type: 'text',
      status: 'completed',
      presentationKind: 'markdown',
      data: { text: '检查对话状态' },
    }],
    attachments: [],
    citations: [],
    createdAtMs: 0,
    completedAtMs: 1,
  };
}
