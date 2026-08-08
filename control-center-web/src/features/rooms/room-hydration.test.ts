import { describe, expect, it } from 'vitest';

import { roomHydrationState } from './room-hydration';

describe('roomHydrationState', () => {
  it('does not present a failed empty snapshot as an empty Room', () => {
    expect(roomHydrationState({
      hasContent: false,
      loading: false,
      recoveryState: 'failed',
    })).toBe('failed-empty');
  });

  it('preserves cached conversation during a failed refresh', () => {
    expect(roomHydrationState({
      hasContent: true,
      loading: false,
      recoveryState: 'failed',
    })).toBe('failed-with-cache');
  });
});
