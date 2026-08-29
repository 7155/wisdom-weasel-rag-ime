import { describe, expect, it } from 'vitest';
import { createRoomProjection } from '@/contracts/room-reducer';
import type { RoomParticipant, RoomSummary } from '@/features/rooms/room-types';
import {
  roomCollaborationPlanetRequests,
  roomPartnerSessionWindowRequest,
  roomPlanetObserverWindowRequest,
  roomProjectionRuntimeActiveParticipantIds,
  roomRuntimeActiveParticipantIds,
} from './room-satellite-auto-open';

describe('roomPlanetObserverWindowRequest (planet 观察窗统一铭牌)', () => {
  it('gives every entrance the same planet window: celestial title, role subtitle, no personal or machine identity', () => {
    const request = roomPlanetObserverWindowRequest(participant('participant-a', 0), 'room-a');

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
    const request = roomPlanetObserverWindowRequest(participant('participant-i', 8), 'room-a', true);

    expect(request.background).toBe(true);
    expect(request.target.title).toBe('Planet 9');
  });
});

describe('roomPartnerSessionWindowRequest (UR-170/172)', () => {
  it('opens the canonical full Session for an explicit task-table planet click', () => {
    const request = roomPartnerSessionWindowRequest(participant('participant-a', 0));

    expect(request).toEqual({
      appId: 'agent',
      background: false,
      target: {
        kind: 'session',
        id: 'session-participant-a',
        title: 'Earth',
        subtitle: '实现与验证',
      },
    });
  });
});

describe('room collaboration mode planet expansion (UR-184)', () => {
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

  it('opens every active roster planet even when Runtime activity is empty', () => {
    const room = roomWith([
      participant('participant-a', 0),
      participant('participant-b', 1),
      participant('participant-idle', 2),
    ]);

    const requests = roomCollaborationPlanetRequests(room);

    expect(requests).toHaveLength(3);
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
    expect(requests[2]?.target).toMatchObject({ id: 'participant-idle', title: 'Venus' });
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

  it('opens every active partner beyond five and keeps real ordinal order', () => {
    const room = roomWith(Array.from({ length: 7 }, (_, index) => participant(`participant-${index}`, 6 - index)));

    const requests = roomCollaborationPlanetRequests(room);

    expect(requests.map((request) => request.target.id)).toEqual([
      'participant-6', 'participant-5', 'participant-4', 'participant-3',
      'participant-2', 'participant-1', 'participant-0',
    ]);
  });

  it('opens nothing for archived Rooms and never opens a removed member', () => {
    const inactive = roomWith([
      participant('participant-a', 0),
      { ...participant('participant-b', 1), status: 'removed' },
    ]);
    expect(roomCollaborationPlanetRequests(inactive).map((request) => request.target.id))
      .toEqual(['participant-a']);

    const archived = { ...roomWith([participant('participant-a', 0)]), status: 'archived' };
    expect(roomCollaborationPlanetRequests(archived)).toEqual([]);
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
