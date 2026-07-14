import { describe, expect, it } from 'vitest';

import {
  abortAgentTurn,
  appendOptimisticAgentMessage,
  applyAgentSnapshot,
  createAgentProjection,
  reduceAgentEvent,
} from './agent-reducer';
import { parseAgentEvent } from './validators';
import { agentEventFixture as agentEvent } from '@/test/fixtures/events';

describe('AgentEventReducer', () => {
  it('applies ordered deltas and ignores replayed duplicates', () => {
    const initial = createAgentProjection('session-1');
    const first = reduceAgentEvent(initial, agentEvent(1, 'text_delta', { delta: '你' }));
    const second = reduceAgentEvent(first.state, agentEvent(2, 'text_delta', { delta: '好' }));
    const replay = reduceAgentEvent(second.state, agentEvent(2, 'text_delta', { delta: '好' }));

    expect(replay.disposition).toBe('ignored-duplicate');
    expect(replay.state).toBe(second.state);
    expect(textOf(second.state.messagesById['turn-1:assistant'])).toBe('你好');
  });

  it('stops projection on a sequence gap until a snapshot is applied', () => {
    const first = reduceAgentEvent(
      createAgentProjection('session-1'),
      agentEvent(4, 'status_changed', { status: 'busy' }),
    );
    const gap = reduceAgentEvent(first.state, agentEvent(6, 'text_delta', { delta: 'lost' }));
    const pending = reduceAgentEvent(gap.state, agentEvent(7, 'text_delta', { delta: 'late' }));

    expect(gap.disposition).toBe('snapshot-required');
    expect(gap.state.gap).toMatchObject({ expectedSequence: 5, receivedSequence: 6 });
    expect(pending.disposition).toBe('ignored-snapshot-pending');

    const recovered = applyAgentSnapshot(gap.state, {
      messages: [serverMessage('server-user', 'user', 'turn-snapshot', '恢复后的问题')],
      lastSequence: 8,
      resumeToken: 'session-1:8',
    });
    expect(recovered.needsSnapshot).toBe(false);
    expect(recovered.lastSequence).toBe(8);
    expect(recovered.messageOrder).toEqual(['server-user']);
  });

  it('merges an optimistic user message only by clientMessageId', () => {
    const optimistic = appendOptimisticAgentMessage(createAgentProjection('session-1'), {
      clientMessageId: 'client-1',
      text: '同一段文字',
      nowMs: 10,
    });
    const completed = reduceAgentEvent(
      optimistic,
      agentEvent(1, 'message_completed', {
        clientMessageId: 'client-1',
        message: {
          ...serverMessage('server-1', 'user', 'turn-server', '同一段文字'),
          clientMessageId: 'client-1',
        },
      }),
    ).state;

    expect(completed.messageOrder).toEqual(['server-1']);
    expect(completed.messagesById['local:client-1']).toBeUndefined();
    expect(completed.messagesById['server-1'].clientMessageId).toBe('client-1');
    expect(completed.optimisticByClientMessageId).toEqual({});
  });

  it('retains unknown events and can abort an active turn without throwing', () => {
    const unknown = reduceAgentEvent(
      createAgentProjection('session-1'),
      parseAgentEvent({
        ...rawAgentEvent(1, 'future_tool_panel', { safe: 'summary' }),
      }),
    ).state;
    expect(unknown.diagnostics[0]).toMatchObject({
      eventType: 'future_tool_panel',
      payload: { safe: 'summary' },
    });

    const streaming = reduceAgentEvent(
      unknown,
      agentEvent(2, 'text_delta', { delta: 'partial' }),
    ).state;
    const aborted = abortAgentTurn(streaming, 'turn-1', 30);
    expect(aborted.turnsById['turn-1'].status).toBe('aborted');
    expect(aborted.messagesById['turn-1:assistant'].status).toBe('aborted');
  });
});

function rawAgentEvent(
  sequence: number,
  eventType: string,
  payload: Record<string, unknown>,
) {
  return {
    schemaVersion: 'rag-ime.agent-event.v1',
    eventId: `session-1:${sequence}`,
    sessionId: 'session-1',
    turnId: 'turn-1',
    sequence,
    createdAtMs: sequence * 10,
    eventType,
    payload: {
      messageId: 'turn-1:assistant',
      blockId: 'turn-1:assistant:text',
      ...payload,
    },
    resumeToken: `session-1:${sequence}`,
  };
}

function serverMessage(id: string, role: 'user' | 'assistant', turnId: string, text: string) {
  return {
    schemaVersion: 'rag-ime.agent-message.v1',
    id,
    sessionId: 'session-1',
    turnId,
    role,
    status: 'completed',
    blocks: [
      {
        id: `${id}:text`,
        type: 'text',
        status: 'completed',
        presentationKind: 'markdown',
        data: { text },
      },
    ],
    attachments: [],
    citations: [],
    createdAtMs: 20,
    completedAtMs: 21,
  };
}

function textOf(message: { blocks: { data: Record<string, unknown> }[] }): string {
  return String(message.blocks[0]?.data.text ?? '');
}
