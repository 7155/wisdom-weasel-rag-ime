import fixture from '../../../../../tests/fixtures/room_version_replay/pre_0124_root_replay.json';
import { describe, expect, it } from 'vitest';

import {
  createRoomKernelProjection,
  reduceRoomKernelEvent,
} from '@/contracts/room-kernel-reducer';
import type { RoomEventEnvelopeV2 } from '@/contracts/generated/room-event-envelope.v2';

import { parseSnapshot } from './RoomKernelLivePanel';

describe('historical Room version replay', () => {
  it('consumes the upcast pre-0124 snapshot and live replay as current contracts', () => {
    const snapshot = parseSnapshot(fixture.snapshot, fixture.snapshot.roomId);
    expect(snapshot.roots).toEqual([
      expect.objectContaining({
        schemaVersion: 'wisdom-weasel.room-root-execution.v3',
        facilitatorParticipantId: 'participant:legacy-facilitator',
        reporterParticipantId: null,
        independentReviewRequired: true,
      }),
    ]);

    let projection = createRoomKernelProjection(fixture.snapshot.roomId);
    for (const rawEvent of fixture.replayEvents) {
      const reduced = reduceRoomKernelEvent(
        projection,
        rawEvent as unknown as RoomEventEnvelopeV2,
      );
      expect(reduced.disposition).toBe('applied');
      projection = reduced.state;
    }

    expect(projection.lastSequence).toBe(2);
    expect(projection.rootsById['root:legacy-version-replay']).toEqual(
      expect.objectContaining({
        schemaVersion: 'wisdom-weasel.room-root-execution.v3',
        facilitatorParticipantId: 'participant:legacy-facilitator',
        independentReviewRequired: true,
      }),
    );
  });
});
