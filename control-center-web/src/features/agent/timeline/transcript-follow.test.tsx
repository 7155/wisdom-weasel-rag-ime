import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { TooltipProvider } from '@/components/primitives';
import type { UiAgentMessage } from '@/contracts/ui-events';
import { agentEventFixture } from '@/test/fixtures/events';
import { AgentComposer } from '../composer/AgentComposer';
import { previewSessions } from '../preview-data';
import { useAgentLiveStore } from '../state/live-store';
import { SettledTurnAnnouncer, settledTurnAnnouncement } from './SettledTurnAnnouncer';
import {
  FOLLOWING_TRANSCRIPT,
  reduceTranscriptFollow,
  unseenUpdatesLabel,
} from './transcript-follow';

const SESSION_ID = 'session-1';
const TURN_ID = 'turn-1';

afterEach(() => {
  cleanup();
  useAgentLiveStore.getState().clear(SESSION_ID);
});

describe('transcript follow ownership', () => {
  it('ignores appended content while following so live output costs no host render', () => {
    const next = reduceTranscriptFollow(FOLLOWING_TRANSCRIPT, {
      type: 'content-appended',
      count: 4,
    });

    expect(next).toBe(FOLLOWING_TRANSCRIPT);
  });

  it('counts content appended after the reader leaves the end', () => {
    const detached = reduceTranscriptFollow(FOLLOWING_TRANSCRIPT, { type: 'user-detached' });
    expect(detached).toEqual({ mode: 'detached', unseenUpdates: 0, detachedReason: 'user-scroll' });

    const afterOne = reduceTranscriptFollow(detached, { type: 'content-appended' });
    const afterBatch = reduceTranscriptFollow(afterOne, { type: 'content-appended', count: 3 });

    expect(afterBatch.unseenUpdates).toBe(4);
    expect(afterBatch.mode).toBe('detached');
  });

  it('does not reset an existing count when the reader detaches again for a new reason', () => {
    const withBacklog = reduceTranscriptFollow(
      reduceTranscriptFollow(FOLLOWING_TRANSCRIPT, { type: 'user-detached' }),
      { type: 'content-appended', count: 5 },
    );

    const jumped = reduceTranscriptFollow(withBacklog, {
      type: 'user-detached',
      reason: 'jump-to-message',
    });

    expect(jumped.unseenUpdates).toBe(5);
    expect(jumped.detachedReason).toBe('jump-to-message');
  });

  it('returns to the end and clears the count on jump, submit and conversation switch', () => {
    const detached = reduceTranscriptFollow(
      reduceTranscriptFollow(FOLLOWING_TRANSCRIPT, { type: 'user-detached' }),
      { type: 'content-appended', count: 9 },
    );

    for (const type of ['reached-end', 'jump-to-latest', 'prompt-submitted', 'conversation-switched'] as const) {
      expect(reduceTranscriptFollow(detached, { type })).toEqual(FOLLOWING_TRANSCRIPT);
    }
  });

  it('keeps object identity when an event changes nothing', () => {
    expect(reduceTranscriptFollow(FOLLOWING_TRANSCRIPT, { type: 'reached-end' }))
      .toBe(FOLLOWING_TRANSCRIPT);
    const detached = reduceTranscriptFollow(FOLLOWING_TRANSCRIPT, { type: 'user-detached' });
    expect(reduceTranscriptFollow(detached, { type: 'user-detached' })).toBe(detached);
  });

  it('bounds the visible count so an unattended stream cannot widen the control', () => {
    expect(unseenUpdatesLabel(0)).toBe('');
    expect(unseenUpdatesLabel(12)).toBe('12');
    expect(unseenUpdatesLabel(240)).toBe('99+');
  });
});

describe('jump-to-latest control', () => {
  function renderJumpControl(unseenUpdates: number) {
    return render(
      <TooltipProvider>
        <AgentComposer
          attachments={[]}
          busy={false}
          commands={[]}
          draft=""
          onAttachmentsChange={() => {}}
          onDraftChange={() => {}}
          onModelChange={() => {}}
          onPasteImages={() => {}}
          onPermissionChange={() => {}}
          onPickAttachments={() => {}}
          onProductCommand={() => {}}
          onSend={() => {}}
          onStop={() => {}}
          onToolSelect={() => {}}
          onWorkspaceRootsChange={() => {}}
          sending={false}
          session={previewSessions[0]}
          showJumpLatest
          toolCatalogStatus="ready"
          tools={[]}
          unseenUpdates={unseenUpdates}
        />
      </TooltipProvider>,
    );
  }

  it('says only that a way back exists when nothing arrived while the reader was away', () => {
    renderJumpControl(0);

    expect(screen.getByRole('button', { name: '回到最新' })).not.toHaveAttribute('data-unseen');
  });

  it('states how much content arrived while the reader was away', () => {
    renderJumpControl(7);

    const jump = screen.getByRole('button', { name: '回到最新，有 7 条新内容' });
    expect(jump).toHaveAttribute('data-unseen');
    expect(jump).toHaveTextContent('7');
  });
});

describe('settle-only transcript announcement', () => {
  function hydrateRunningTurn(): void {
    useAgentLiveStore.getState().hydrateSnapshot(SESSION_ID, {
      messages: [userMessage()],
      liveEvents: [],
      lastSequence: 0,
      resumeToken: '',
      status: 'idle',
    });
    useAgentLiveStore.getState().applyEvents(SESSION_ID, [
      agentEventFixture(1, 'text_delta', { delta: '正在检查运行状态', replaceBlock: true }),
    ]);
  }

  function announcer(container: HTMLElement): HTMLElement {
    const element = container.querySelector<HTMLElement>('[data-transcript-announcer]');
    if (!element) throw new Error('transcript announcer is not mounted');
    return element;
  }

  it('stays silent while the answer is still growing', () => {
    hydrateRunningTurn();
    const { container } = render(<SettledTurnAnnouncer sessionId={SESSION_ID} />);

    act(() => {
      useAgentLiveStore.getState().applyEvents(SESSION_ID, [
        agentEventFixture(2, 'text_delta', { delta: '，已经读取到第一批结果' }),
        agentEventFixture(3, 'text_delta', { delta: '，正在继续。' }),
      ]);
    });

    expect(announcer(container)).toHaveTextContent('');
  });

  it('speaks once when the turn reaches a terminal status', () => {
    hydrateRunningTurn();
    const { container } = render(<SettledTurnAnnouncer sessionId={SESSION_ID} />);

    act(() => {
      useAgentLiveStore.getState().applyEvents(SESSION_ID, [
        agentEventFixture(2, 'text_delta', { delta: '，运行正常。' }),
        agentEventFixture(3, 'message_completed', {
          message: assistantMessage('正在检查运行状态，运行正常。'),
        }),
        agentEventFixture(4, 'turn_completed', { status: 'completed' }),
      ]);
    });

    expect(announcer(container)).toHaveTextContent('Agent 回复已完成，共 14 字。');
  });

  it('reports a stopped turn as stopped rather than as an empty reply', () => {
    hydrateRunningTurn();
    const { container } = render(<SettledTurnAnnouncer sessionId={SESSION_ID} />);

    act(() => {
      useAgentLiveStore.getState().applyEvents(SESSION_ID, [
        agentEventFixture(2, 'turn_completed', { status: 'aborted' }),
      ]);
    });

    expect(announcer(container)).toHaveTextContent('本轮已停止。');
  });

  it('never echoes the reply, so the transcript stays the only copy of the answer', () => {
    hydrateRunningTurn();
    const reply = '运行状态正常。'.repeat(80);
    useAgentLiveStore.getState().applyEvents(SESSION_ID, [
      agentEventFixture(2, 'message_completed', { message: assistantMessage(reply) }),
      agentEventFixture(3, 'turn_completed', { status: 'completed' }),
    ]);

    const announcement = settledTurnAnnouncement(
      useAgentLiveStore.getState().projections[SESSION_ID],
      TURN_ID,
    );

    expect(announcement).toBe(`Agent 回复已完成，共 ${reply.length} 字。`);
    expect(announcement).not.toContain('运行状态正常');
  });
});

function userMessage(): UiAgentMessage {
  return {
    schemaVersion: 'rag-ime.agent-message.v1',
    id: 'follow-user-message',
    sessionId: SESSION_ID,
    turnId: TURN_ID,
    role: 'user',
    status: 'completed',
    blocks: [{
      id: 'follow-user-text',
      type: 'text',
      status: 'completed',
      presentationKind: 'markdown',
      data: { text: '检查运行状态' },
    }],
    attachments: [],
    citations: [],
    createdAtMs: 0,
    completedAtMs: 1,
  };
}

function assistantMessage(value: string): UiAgentMessage {
  return {
    schemaVersion: 'rag-ime.agent-message.v1',
    id: 'turn-1:assistant',
    sessionId: SESSION_ID,
    turnId: TURN_ID,
    role: 'assistant',
    status: 'completed',
    blocks: [{
      id: 'turn-1:assistant:text',
      type: 'text',
      status: 'completed',
      presentationKind: 'markdown',
      data: { text: value },
    }],
    attachments: [],
    citations: [],
    createdAtMs: 10,
    completedAtMs: 20,
  };
}
