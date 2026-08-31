import { describe, expect, it } from 'vitest';
import { transientControlErrorRefetchInterval } from './query-client';

describe('transientControlErrorRefetchInterval', () => {
  it('retries only an active failed control query and stops after recovery', () => {
    expect(transientControlErrorRefetchInterval(true)({ state: { status: 'error' } })).toBe(4_000);
    expect(transientControlErrorRefetchInterval(true)({ state: { status: 'success' } })).toBe(false);
    expect(transientControlErrorRefetchInterval(false)({ state: { status: 'error' } })).toBe(false);
  });
});
