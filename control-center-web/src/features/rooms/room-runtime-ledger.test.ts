import { describe, expect, it } from 'vitest';
import { appendOptimisticRoomMessage, createRoomProjection } from '@/contracts/room-reducer';
import { createRoomRuntimeLedger } from './room-runtime-ledger';

describe('Room runtime ledger', () => {
  it('isolates projections by Room and retains them across navigation', () => {
    let now = 10;
    const ledger = createRoomRuntimeLedger(() => now);
    const roomA = appendOptimisticRoomMessage(
      ledger.getOrCreate('room:a').projection,
      { clientMessageId: 'client:a', text: '继续执行', nowMs: now },
    );
    ledger.replace('room:a', roomA);

    now = 20;
    expect(ledger.getOrCreate('room:b').projection.messageOrder).toEqual([]);
    expect(ledger.getOrCreate('room:a').projection.messageOrder).toEqual([
      'local-room:client:a',
    ]);
  });

  it('rejects cross-Room projection replacement', () => {
    const ledger = createRoomRuntimeLedger(() => 1);
    expect(() => ledger.replace('room:a', createRoomProjection('room:b'))).toThrow(
      'Room projection belongs to another Room',
    );
  });

  it('keeps active Rooms during cleanup and removes only idle entries', () => {
    let now = 10;
    const ledger = createRoomRuntimeLedger(() => now);
    ledger.replace(
      'room:active',
      appendOptimisticRoomMessage(
        ledger.getOrCreate('room:active').projection,
        { clientMessageId: 'client:active', text: '仍在执行', nowMs: now },
      ),
    );
    ledger.getOrCreate('room:idle');

    now = 100;
    expect(ledger.sweepIdle(50)).toBe(1);
    expect(ledger.peek('room:idle')).toBeUndefined();
    expect(ledger.peek('room:active')).toBeDefined();
  });
});
