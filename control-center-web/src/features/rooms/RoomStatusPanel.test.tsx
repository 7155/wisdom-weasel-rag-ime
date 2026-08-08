import { describe, expect, it } from 'vitest';

import type {
  RoomActivityProjection,
  RoomMessageProjection,
  RoomTurnProjection,
} from '@/contracts/room-reducer';
import { roomProjectedStatus } from './RoomStatusPanel';

describe('roomProjectedStatus', () => {
  it('does not promote a settled Runtime turn without a Room outcome to completed', () => {
    expect(roomProjectedStatus(
      { id: 'turn-a', status: 'completed' } as RoomTurnProjection,
      [] as RoomActivityProjection[],
      [] as RoomMessageProjection[],
    )).toBe('settled');
  });
});
