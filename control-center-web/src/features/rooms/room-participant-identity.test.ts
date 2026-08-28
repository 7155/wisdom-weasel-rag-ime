import { describe, expect, it } from 'vitest';
import { roomCandidatePlanetName, roomParticipantPlanetName, roomPlanetName } from './room-participant-identity';

describe('Room participant public identity', () => {
  it('uses ordinal planets and never needs a persona display name', () => {
    expect(roomPlanetName(0)).toBe('Earth');
    expect(roomPlanetName(1)).toBe('Mars');
    expect(roomPlanetName(8)).toBe('Planet 9');
    expect(roomParticipantPlanetName({ ordinal: 2 })).toBe('Venus');
    expect(roomParticipantPlanetName({})).toBe('协作行星');
  });

  it('labels personas that have not joined as candidate planets', () => {
    expect(roomCandidatePlanetName(0)).toBe('候选行星 1');
    expect(roomCandidatePlanetName(3)).toBe('候选行星 4');
  });
});
