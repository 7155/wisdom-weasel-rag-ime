import { describe, expect, it } from 'vitest';
import { createRoomProjection } from '@/contracts/room-reducer';
import type { RoomParticipant, RoomSummary } from '@/features/rooms/room-types';
import {
  roomCollaborationSatelliteRequests,
  roomPlanetWindowRequest,
  roomProjectionRuntimeActiveParticipantIds,
  roomRuntimeActiveParticipantIds,
} from './room-satellite-auto-open';

describe('roomPlanetWindowRequest (planet 窗口统一铭牌)', () => {
  it('gives every entrance the same planet window: celestial title, role subtitle, no personal or machine identity', () => {
    const request = roomPlanetWindowRequest(participant('participant-a', 0), 'room-a');

    expect(request).toEqual({
      appId: 'agent',
      background: false,
      target: {
        kind: 'participant',
        id: 'participant-a',
        roomId: 'room-a',
        sessionId: 'session-participant-a',
        title: 'Earth',
        subtitle: '实现与验证',
      },
    });
    expect(request.target.subtitle).not.toContain('session-');
    expect(request.target.subtitle).not.toContain('伙伴 participant-a');
  });

  it('keeps a readable planet name beyond the named celestial list', () => {
    const request = roomPlanetWindowRequest(participant('participant-i', 8), 'room-a', true);

    expect(request.background).toBe(true);
    expect(request.target.title).toBe('Planet 9');
  });
});

describe('room collaboration mode satellite expansion (UR-177)', () => {
  it('recovers Runtime-active ids from execution lanes when snapshot participant ids lag', () => {
    const ids = roomRuntimeActiveParticipantIds({
      status: 'running',
      participantIds: ['participant-a'],
      terminalParticipantIds: ['participant-a'],
      failedParticipantIds: [],
      abortedParticipantIds: [],
    }, [
      { participantId: 'participant-a' },
      { participantId: 'participant-b' },
      { participantId: null },
    ]);

    expect([...ids]).toEqual(['participant-b']);
  });

  it('opens only Runtime-active Room participants as background planet Sessions', () => {
    const room = roomWith([
      participant('participant-a', 0),
      participant('participant-b', 1),
      participant('participant-idle', 2),
    ]);

    const requests = roomCollaborationSatelliteRequests(
      room,
      new Set(['participant-a', 'participant-b']),
    );

    expect(requests).toHaveLength(2);
    for (const request of requests) {
      expect(request.appId).toBe('agent');
      expect(request.background).toBe(true);
      expect(request.target.kind).toBe('participant');
    }
    expect(requests[0]?.target).toMatchObject({
      id: 'participant-a',
      roomId: 'room-a',
      sessionId: 'session-participant-a',
      title: 'Earth',
      subtitle: '实现与验证',
    });
    expect(requests[1]?.target).toMatchObject({ id: 'participant-b', title: 'Mars' });
    expect(requests.some((request) => request.target.id === 'participant-idle')).toBe(false);
  });

  it('unions disjoint partners from every running public root but excludes terminal and detached lanes', () => {
    const projection = createRoomProjection('room-a');
    projection.turnOrder = ['root-earth', 'root-mars', 'root-complete', 'delivery-turn'];
    projection.turnsById['root-earth'] = {
      id: 'root-earth', rootId: 'root-earth', status: 'running',
      messageIds: ['user-earth'], activityIds: [], participantIds: ['participant-earth'],
      createdAtMs: 1, updatedAtMs: 2,
    };
    projection.turnsById['root-mars'] = {
      id: 'root-mars', rootId: 'root-mars', status: 'running',
      messageIds: ['user-mars'], activityIds: [],
      participantIds: ['participant-mars', 'participant-finished'],
      terminalParticipantIds: ['participant-finished'],
      createdAtMs: 3, updatedAtMs: 4,
    };
    projection.turnsById['root-complete'] = {
      id: 'root-complete', rootId: 'root-complete', status: 'completed',
      messageIds: ['user-complete'], activityIds: [], participantIds: ['participant-complete'],
      createdAtMs: 5, updatedAtMs: 6,
    };
    projection.turnsById['delivery-turn'] = {
      id: 'delivery-turn', rootId: 'delivery-turn', status: 'running',
      messageIds: [], activityIds: ['intercom-delivered'], participantIds: ['participant-detached'],
      createdAtMs: 7, updatedAtMs: 8,
    };
    projection.activitiesById['intercom-delivered'] = {
      id: 'intercom-delivered', turnId: 'delivery-turn', participantId: 'participant-detached',
      sourceSessionId: 'session-detached', kind: 'participant_activity', status: 'completed',
      summary: '伙伴沟通', payload: { activityKind: 'intercom' }, createdAtMs: 7,
    };

    expect([...roomProjectionRuntimeActiveParticipantIds(projection)]).toEqual([
      'participant-earth',
      'participant-mars',
    ]);
  });

  it('opens every Runtime-active partner beyond five and keeps real ordinal order', () => {
    const room = roomWith(Array.from({ length: 7 }, (_, index) => participant(`participant-${index}`, 6 - index)));

    const requests = roomCollaborationSatelliteRequests(
      room,
      new Set(room.participants.map((item) => item.id)),
    );

    expect(requests.map((request) => request.target.id)).toEqual([
      'participant-6', 'participant-5', 'participant-4', 'participant-3',
      'participant-2', 'participant-1', 'participant-0',
    ]);
  });

  it('opens nothing for archived Rooms and never treats a removed member as Runtime-active', () => {
    const inactive = roomWith([
      participant('participant-a', 0),
      { ...participant('participant-b', 1), status: 'removed' },
    ]);
    expect(roomCollaborationSatelliteRequests(
      inactive,
      new Set(['participant-a', 'participant-b']),
    ).map((request) => request.target.id))
      .toEqual(['participant-a']);

    expect(roomCollaborationSatelliteRequests(inactive, new Set())).toEqual([]);

    const archived = { ...roomWith([participant('participant-a', 0)]), status: 'archived' };
    expect(roomCollaborationSatelliteRequests(archived, new Set(['participant-a']))).toEqual([]);
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
