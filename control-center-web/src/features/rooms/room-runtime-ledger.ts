import {
  createRoomProjection,
  type RoomProjectionState,
} from '@/contracts/room-reducer';

export interface RoomRuntimeEntry {
  projection: RoomProjectionState;
  lastTouchedMs: number;
}

export interface RoomRuntimeLedger {
  getOrCreate(roomId: string): RoomRuntimeEntry;
  peek(roomId: string): RoomRuntimeEntry | undefined;
  replace(roomId: string, projection: RoomProjectionState): RoomRuntimeEntry;
  remove(roomId: string): void;
  sweepIdle(cutoffMs: number): number;
}

export function createRoomRuntimeLedger(
  now: () => number = Date.now,
): RoomRuntimeLedger {
  const entries = new Map<string, RoomRuntimeEntry>();

  function requireRoomId(roomId: string): string {
    const value = roomId.trim();
    if (!value) throw new TypeError('roomId must not be empty');
    return value;
  }

  return {
    getOrCreate(roomId) {
      const id = requireRoomId(roomId);
      const existing = entries.get(id);
      if (existing) {
        existing.lastTouchedMs = now();
        return existing;
      }
      const created = {
        projection: createRoomProjection(id),
        lastTouchedMs: now(),
      };
      entries.set(id, created);
      return created;
    },
    peek(roomId) {
      return entries.get(roomId);
    },
    replace(roomId, projection) {
      const id = requireRoomId(roomId);
      if (projection.roomId !== id) {
        throw new TypeError('Room projection belongs to another Room');
      }
      const entry = { projection, lastTouchedMs: now() };
      entries.set(id, entry);
      return entry;
    },
    remove(roomId) {
      entries.delete(roomId);
    },
    sweepIdle(cutoffMs) {
      let removed = 0;
      for (const [roomId, entry] of entries) {
        if (entry.lastTouchedMs >= cutoffMs || projectionIsActive(entry.projection)) continue;
        entries.delete(roomId);
        removed += 1;
      }
      return removed;
    },
  };
}

function projectionIsActive(projection: RoomProjectionState): boolean {
  if (Object.keys(projection.optimisticByClientMessageId).length > 0) return true;
  return Object.values(projection.turnsById).some((turn) => (
    turn.status === 'queued' || turn.status === 'running'
  ));
}
