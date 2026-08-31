import { create } from 'zustand';

import type { RoomProjectionState } from '@/contracts/room-reducer';

/**
 * Lightweight shell projection of the Room live store.
 *
 * PAWOS needs Room projections only to draw cross-window flow and the Sol
 * focus status. Importing the writable live store here would also import the
 * reducer and the generated validator bundle on first paint. The Room owner
 * publishes the same immutable projections record into this tiny bridge when
 * its lazy chunk is active; the shell can subscribe without learning how Room
 * events are parsed or reduced.
 */
export const useRoomProjectionBridge = create<{
  projections: Record<string, RoomProjectionState>;
}>(() => ({ projections: {} }));

export function publishRoomProjectionSnapshot(
  projections: Record<string, RoomProjectionState>,
): void {
  if (useRoomProjectionBridge.getState().projections === projections) return;
  useRoomProjectionBridge.setState({ projections });
}
