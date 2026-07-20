import { describe, expect, it } from 'vitest';
import {
  bindRootRuntime,
  createRootRuntimeLedger,
  markRootStopAcknowledged,
  requestRootRuntimeStop,
  trackRootDispatch,
  trackRootSession,
} from './root-runtime-ledger';

describe('Root runtime ledger', () => {
  it('isolates live resources by Room, Root, and generation', () => {
    const ledger = createRootRuntimeLedger();
    bindRootRuntime(ledger, 'room-a', 'root-a', 1);
    bindRootRuntime(ledger, 'room-a', 'root-b', 3);
    trackRootSession(ledger, 'room-a', 'root-a', 1, 'session-a');
    trackRootDispatch(ledger, 'room-a', 'root-b', 3, 'dispatch-b');

    expect(ledger.get('room-a', 'root-a')?.activeSessionIds).toEqual(new Set(['session-a']));
    expect(ledger.get('room-a', 'root-a')?.activeDispatchIds).toEqual(new Set());
    expect(ledger.get('room-a', 'root-b')?.activeDispatchIds).toEqual(new Set(['dispatch-b']));
  });

  it('targets Stop to one Root and rejects a stale generation', () => {
    const ledger = createRootRuntimeLedger();
    bindRootRuntime(ledger, 'room-a', 'root-a', 2);
    bindRootRuntime(ledger, 'room-a', 'root-b', 5);

    requestRootRuntimeStop(ledger, 'room-a', 'root-b', 5, 'stop-b-5', 100);
    expect(ledger.get('room-a', 'root-a')?.stopRequest).toBeNull();
    expect(ledger.get('room-a', 'root-b')?.stopRequest).toMatchObject({
      idempotencyKey: 'stop-b-5', state: 'requested',
    });
    expect(() => requestRootRuntimeStop(ledger, 'room-a', 'root-b', 4, 'stale', 101))
      .toThrow(/generation/);

    markRootStopAcknowledged(ledger, 'room-a', 'root-b', 5, 'stop-b-5');
    expect(ledger.get('room-a', 'root-b')?.stopRequest?.state).toBe('acknowledged');
  });

  it('clears stale live resources when a Root advances generation', () => {
    const ledger = createRootRuntimeLedger();
    bindRootRuntime(ledger, 'room-a', 'root-a', 2);
    trackRootSession(ledger, 'room-a', 'root-a', 2, 'session-old');
    trackRootDispatch(ledger, 'room-a', 'root-a', 2, 'dispatch-old');
    requestRootRuntimeStop(ledger, 'room-a', 'root-a', 2, 'stop-old', 100);

    bindRootRuntime(ledger, 'room-a', 'root-a', 3);
    const advanced = ledger.get('room-a', 'root-a');
    expect(advanced?.generation).toBe(3);
    expect(advanced?.activeSessionIds).toEqual(new Set());
    expect(advanced?.activeDispatchIds).toEqual(new Set());
    expect(advanced?.stopRequest).toBeNull();
  });
});
