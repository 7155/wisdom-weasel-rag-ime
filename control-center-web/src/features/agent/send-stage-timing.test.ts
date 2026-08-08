import { describe, expect, it, vi } from 'vitest';
import type { UiAgentEvent } from '@/contracts/ui-events';
import {
  AgentSendTimingTracker,
  type AgentSendTimingName,
} from './send-stage-timing';

describe('AgentSendTimingTracker', () => {
  it('records click, optimistic append, Pi admission, and first-delta stages', () => {
    const rows: Array<[AgentSendTimingName, number, number]> = [];
    const tracker = new AgentSendTimingTracker(
      () => 0,
      (name, start, end) => rows.push([name, start, end]),
    );

    tracker.begin('session-1', 'client-1', 10);
    tracker.optimistic('client-1', 12);
    tracker.accepted('client-1', { turnId: 'turn-1' }, 30);
    tracker.observe(event('text_delta', 'turn-1'), 55);

    expect(rows).toEqual([
      ['agent.send.click_to_optimistic', 10, 12],
      ['agent.send.click_to_pi_accepted', 10, 30],
      ['agent.send.click_to_first_delta', 10, 55],
      ['agent.send.pi_accepted_to_first_delta', 30, 55],
    ]);
  });

  it('correlates the first delta when SSE admission arrives before HTTP', () => {
    const record = vi.fn();
    const tracker = new AgentSendTimingTracker(() => 0, record);

    tracker.begin('session-1', 'client-1', 10);
    tracker.observe(event('message_completed', 'turn-1', {
      clientMessageId: 'client-1',
    }), 20);
    tracker.observe(event('text_delta', 'turn-1'), 35);
    tracker.accepted('client-1', { turnId: 'turn-1' }, 45);

    expect(record).toHaveBeenCalledWith(
      'agent.send.click_to_first_delta',
      10,
      35,
    );
    expect(record).toHaveBeenCalledWith(
      'agent.send.click_to_pi_accepted',
      10,
      45,
    );
    expect(record).not.toHaveBeenCalledWith(
      'agent.send.pi_accepted_to_first_delta',
      expect.anything(),
      expect.anything(),
    );
  });

  it('keeps the turn bound by the earlier user-message event when a late acknowledgement differs', () => {
    const record = vi.fn();
    const tracker = new AgentSendTimingTracker(() => 0, record);

    tracker.begin('session-1', 'client-1', 10);
    tracker.observe(event('message_completed', 'turn-from-event', {
      clientMessageId: 'client-1',
    }), 20);
    tracker.accepted('client-1', { turnId: 'turn-from-late-ack' }, 30);
    tracker.observe(event('text_delta', 'turn-from-event'), 40);

    expect(record).toHaveBeenCalledWith(
      'agent.send.click_to_first_delta',
      10,
      40,
    );
  });

  it('retains an early delta until its user-message event identifies the client', () => {
    const record = vi.fn();
    const tracker = new AgentSendTimingTracker(() => 0, record);

    tracker.begin('session-1', 'client-1', 10);
    tracker.observe(event('text_delta', 'turn-1'), 25);
    tracker.observe(event('message_completed', 'turn-1', {
      message: { clientMessageId: 'client-1' },
    }), 30);

    expect(record).toHaveBeenCalledWith(
      'agent.send.click_to_first_delta',
      10,
      25,
    );
  });

  it('drops failed and cleared sends instead of reporting late events', () => {
    const record = vi.fn();
    const tracker = new AgentSendTimingTracker(() => 0, record);

    tracker.begin('session-1', 'client-1', 10);
    tracker.failed('client-1');
    tracker.accepted('client-1', { turnId: 'turn-1' }, 20);
    tracker.begin('session-2', 'client-2', 30);
    tracker.clearSession('session-2');
    tracker.accepted('client-2', { turnId: 'turn-2' }, 40);

    expect(record).not.toHaveBeenCalled();
  });
});

function event(
  eventType: UiAgentEvent['eventType'],
  turnId: string,
  payload: Record<string, unknown> = {},
): UiAgentEvent {
  return {
    schemaVersion: 'rag-ime.agent-event.v1',
    eventId: `${turnId}:${eventType}`,
    sessionId: 'session-1',
    turnId,
    sequence: 1,
    createdAtMs: 0,
    payload,
    resumeToken: '1',
    streamKind: 'agent',
    eventType,
  };
}
