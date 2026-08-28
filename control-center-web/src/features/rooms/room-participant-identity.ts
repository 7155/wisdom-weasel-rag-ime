import { roomPlanetName as baseRoomPlanetName } from './room-copy';

type ParticipantIdentity = { ordinal?: number };

export function roomPlanetName(ordinal: number | undefined): string {
  return baseRoomPlanetName(ordinal ?? 0);
}

export function roomParticipantPlanetName(participant: ParticipantIdentity | undefined): string {
  return participant && Number.isInteger(participant.ordinal) && (participant.ordinal ?? -1) >= 0
    ? roomPlanetName(participant.ordinal!)
    : '协作行星';
}

export function roomCandidatePlanetName(index: number): string {
  return `候选行星 ${Math.max(0, index) + 1}`;
}
