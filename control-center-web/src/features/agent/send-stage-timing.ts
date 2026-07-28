import type { UiAgentEvent } from '@/contracts/ui-events';

export type AgentSendTimingName =
  | 'agent.send.click_to_optimistic'
  | 'agent.send.click_to_pi_accepted'
  | 'agent.send.click_to_first_delta'
  | 'agent.send.pi_accepted_to_first_delta';

interface PendingSendTiming {
  sessionId: string;
  clientMessageId: string;
  startedAt: number;
  acceptedAt?: number;
  turnId?: string;
  firstDeltaAt?: number;
  acceptedRecorded: boolean;
  firstDeltaRecorded: boolean;
}

export interface AgentSendTimingRecorder {
  (name: AgentSendTimingName, startedAt: number, endedAt: number): void;
}

/**
 * Correlates the four user-visible send stages without changing delivery:
 * click -> optimistic append -> Pi admission -> first streamed text.
 *
 * The tracker is bounded, stores no message text, and accepts both the HTTP
 * admission receipt and the user-message SSE event as turn-correlation
 * evidence. Either can arrive first.
 */
export class AgentSendTimingTracker {
  private readonly pending = new Map<string, PendingSendTiming>();
  private readonly clientByTurn = new Map<string, string>();
  private readonly firstDeltaByTurn = new Map<string, number>();

  constructor(
    private readonly now: () => number = monotonicNow,
    private readonly record: AgentSendTimingRecorder = recordPerformanceMeasure,
    private readonly limit = 64,
  ) {}

  begin(sessionId: string, clientMessageId: string, startedAt = this.now()): void {
    this.pending.delete(clientMessageId);
    this.pending.set(clientMessageId, {
      sessionId,
      clientMessageId,
      startedAt,
      acceptedRecorded: false,
      firstDeltaRecorded: false,
    });
    while (this.pending.size > this.limit) {
      const oldest = this.pending.keys().next().value as string | undefined;
      if (!oldest) break;
      this.drop(oldest);
    }
  }

  optimistic(clientMessageId: string, endedAt = this.now()): void {
    const item = this.pending.get(clientMessageId);
    if (!item) return;
    this.record('agent.send.click_to_optimistic', item.startedAt, endedAt);
  }

  accepted(
    clientMessageId: string,
    response: unknown,
    endedAt = this.now(),
  ): void {
    const item = this.pending.get(clientMessageId);
    if (!item) return;
    item.acceptedAt = endedAt;
    if (!item.acceptedRecorded) {
      item.acceptedRecorded = true;
      this.record('agent.send.click_to_pi_accepted', item.startedAt, endedAt);
    }
    const turnId = record(response).turnId;
    if (typeof turnId === 'string' && turnId) this.bindTurn(item, turnId);
    this.finishIfComplete(item);
  }

  observe(event: UiAgentEvent, observedAt = this.now()): void {
    if (event.eventType === 'message_completed') {
      const message = record(event.payload.message);
      const clientMessageId = stringValue(
        event.payload.clientMessageId ?? message.clientMessageId,
      );
      const item = this.pending.get(clientMessageId);
      if (item && item.sessionId === event.sessionId) this.bindTurn(item, event.turnId);
      return;
    }
    if (event.eventType !== 'text_delta') return;
    const clientMessageId = this.clientByTurn.get(event.turnId);
    const item = clientMessageId ? this.pending.get(clientMessageId) : undefined;
    if (!item || item.sessionId !== event.sessionId) {
      if (!this.firstDeltaByTurn.has(event.turnId)) {
        this.firstDeltaByTurn.set(event.turnId, observedAt);
        while (this.firstDeltaByTurn.size > this.limit) {
          const oldest = this.firstDeltaByTurn.keys().next().value as string | undefined;
          if (!oldest) break;
          this.firstDeltaByTurn.delete(oldest);
        }
      }
      return;
    }
    if (item.firstDeltaAt === undefined) item.firstDeltaAt = observedAt;
    this.recordFirstDelta(item);
    this.finishIfComplete(item);
  }

  failed(clientMessageId: string): void {
    this.drop(clientMessageId);
  }

  clearSession(sessionId: string): void {
    for (const [clientMessageId, item] of this.pending) {
      if (item.sessionId === sessionId) this.drop(clientMessageId);
    }
  }

  private bindTurn(item: PendingSendTiming, turnId: string): void {
    if (item.turnId && item.turnId !== turnId) this.clientByTurn.delete(item.turnId);
    item.turnId = turnId;
    this.clientByTurn.set(turnId, item.clientMessageId);
    const observedDeltaAt = this.firstDeltaByTurn.get(turnId);
    if (observedDeltaAt !== undefined && item.firstDeltaAt === undefined) {
      item.firstDeltaAt = observedDeltaAt;
      this.firstDeltaByTurn.delete(turnId);
    }
    this.recordFirstDelta(item);
  }

  private recordFirstDelta(item: PendingSendTiming): void {
    if (item.firstDeltaAt === undefined || item.firstDeltaRecorded) return;
    item.firstDeltaRecorded = true;
    this.record(
      'agent.send.click_to_first_delta',
      item.startedAt,
      item.firstDeltaAt,
    );
    if (item.acceptedAt !== undefined && item.firstDeltaAt >= item.acceptedAt) {
      this.record(
        'agent.send.pi_accepted_to_first_delta',
        item.acceptedAt,
        item.firstDeltaAt,
      );
    }
  }

  private finishIfComplete(item: PendingSendTiming): void {
    if (item.acceptedRecorded && item.firstDeltaRecorded) {
      this.drop(item.clientMessageId);
    }
  }

  private drop(clientMessageId: string): void {
    const item = this.pending.get(clientMessageId);
    if (item?.turnId) {
      this.clientByTurn.delete(item.turnId);
      this.firstDeltaByTurn.delete(item.turnId);
    }
    this.pending.delete(clientMessageId);
  }
}

export function monotonicNow(): number {
  return typeof performance === 'undefined' ? Date.now() : performance.now();
}

function recordPerformanceMeasure(
  name: AgentSendTimingName,
  startedAt: number,
  endedAt: number,
): void {
  if (typeof performance === 'undefined' || endedAt < startedAt) return;
  try {
    performance.clearMeasures(name);
    performance.measure(name, { start: startedAt, end: endedAt });
  } catch {
    // Performance timing is diagnostic only and must never block a send.
  }
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
