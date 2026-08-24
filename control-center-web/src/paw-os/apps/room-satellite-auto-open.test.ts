import { describe, expect, it } from 'vitest';
import type { RoomParticipant, RoomSummary } from '@/features/rooms/room-types';
import { ROOM_AUTO_SATELLITE_LIMIT, roomAutoSatelliteRequests } from './room-satellite-auto-open';

describe('room satellite auto expansion (UR-054)', () => {
  it('expands active partners as background satellites so the main Room keeps focus', () => {
    const room = roomWith([
      participant('participant-a', 0),
      participant('participant-b', 1),
    ]);

    const requests = roomAutoSatelliteRequests(room, { 'participant-a': 'Earth' }, new Set());

    expect(requests).toHaveLength(2);
    for (const request of requests) {
      expect(request.appId).toBe('agent');
      expect(request.background).toBe(true);
      expect(request.target.kind).toBe('participant');
    }
    expect(requests[0]?.target).toMatchObject({
      id: 'participant-a',
      roomId: 'room-a',
      title: 'Earth',
      subtitle: '伙伴 participant-a · 实现与验证 · session-participant-a',
    });
    expect(requests[1]?.target).toMatchObject({ id: 'participant-b', title: '伙伴 participant-b' });
  });

  it('never expands more than the four-to-five partner bound and keeps real ordinal order', () => {
    const room = roomWith(Array.from({ length: 7 }, (_, index) => participant(`participant-${index}`, 6 - index)));

    const requests = roomAutoSatelliteRequests(room, {}, new Set());

    expect(ROOM_AUTO_SATELLITE_LIMIT).toBe(5);
    expect(requests.map((request) => request.target.id)).toEqual([
      'participant-6', 'participant-5', 'participant-4', 'participant-3', 'participant-2',
    ]);
  });

  it('does not loop-reopen partners the user already saw or closed in this Room visit', () => {
    const room = roomWith([participant('participant-a', 0), participant('participant-b', 1)]);

    const requests = roomAutoSatelliteRequests(room, {}, new Set(['participant-a']));

    expect(requests.map((request) => request.target.id)).toEqual(['participant-b']);
    expect(roomAutoSatelliteRequests(room, {}, new Set(['participant-a', 'participant-b']))).toEqual([]);
  });

  it('expands nothing for archived Rooms or inactive partners', () => {
    const inactive = roomWith([
      participant('participant-a', 0),
      { ...participant('participant-b', 1), status: 'removed' },
    ]);
    expect(roomAutoSatelliteRequests(inactive, {}, new Set()).map((request) => request.target.id))
      .toEqual(['participant-a']);

    const archived = { ...roomWith([participant('participant-a', 0)]), status: 'archived' };
    expect(roomAutoSatelliteRequests(archived, {}, new Set())).toEqual([]);
  });
});

function participant(id: string, ordinal: number): RoomParticipant {
  return {
    id,
    sessionId: `session-${id}`,
    roleId: 'implementer',
    roleVersion: '1',
    displayName: `伙伴 ${id}`,
    collaborationRole: 'implementer',
    status: 'active',
    ordinal,
  };
}

function roomWith(participants: RoomParticipant[]): RoomSummary {
  return {
    id: 'room-a',
    title: 'Room A',
    status: 'active',
    routingPolicy: 'natural',
    moderatorParticipantId: participants[0]?.id ?? '',
    updatedAtMs: 1,
    participants,
  };
}
