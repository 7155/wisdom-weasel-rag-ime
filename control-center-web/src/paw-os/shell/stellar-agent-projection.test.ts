import { describe, expect, it } from 'vitest';
import {
  projectStellarAgents,
  type StellarAgentRoomSource,
  type StellarAgentSessionSource,
} from './stellar-agent-projection';

const NOW = 1_800_000_000_000;

function session(
  id: string,
  status: string,
  overrides: Partial<StellarAgentSessionSource> = {},
): StellarAgentSessionSource {
  return {
    id,
    title: `Agent ${id}`,
    status,
    updatedAtMs: NOW - 1_000,
    ...overrides,
  };
}

function room(
  id: string,
  participants: StellarAgentRoomSource['participants'] = [],
): StellarAgentRoomSource {
  return {
    id,
    title: `Room ${id}`,
    status: 'active',
    updatedAtMs: NOW - 1_000,
    participants,
  };
}

describe('projectStellarAgents', () => {
  it('uses participant details only from the explicitly bound Room', () => {
    const projection = projectStellarAgents({
      nowMs: NOW,
      sessions: [session('shared', 'busy', {
        title: '',
        roomParticipant: { roomId: 'older-room' },
      })],
      rooms: [
        { ...room('older-room', [{ id: 'correct', sessionId: 'shared', displayName: '当前伙伴' }]), updatedAtMs: NOW - 2_000 },
        { ...room('newer-room', [{ id: 'wrong', sessionId: 'shared', displayName: '其他伙伴' }]), updatedAtMs: NOW - 1_000 },
      ],
    });

    expect(projection.planets[0]).toMatchObject({
      roomId: 'older-room',
      participantId: 'correct',
      name: '当前伙伴',
    });
    expect(projection.limitations).toContain('multiple-room-memberships');
  });

  it('keeps every fresh running standalone and Room Session as its own planet', () => {
    const projection = projectStellarAgents({
      nowMs: NOW,
      sessions: [
        session('standalone', 'busy'),
        session('room-earth', 'busy', {
          title: '实现伙伴',
          roomParticipant: { roomId: 'room-1', participantId: 'earth', status: 'active' },
        }),
        session('room-mars', 'running', {
          title: '验证伙伴',
          roomParticipant: { roomId: 'room-1', participantId: 'mars', status: 'active' },
        }),
      ],
      rooms: [room('room-1', [
        { id: 'earth', sessionId: 'room-earth', displayName: '实现伙伴', ordinal: 0, status: 'active' },
        { id: 'mars', sessionId: 'room-mars', displayName: '验证伙伴', ordinal: 1, status: 'active' },
      ])],
      sessionStatusFresh: true,
      roomStatusFresh: true,
    });

    expect(projection.runningPlanets.map((planet) => planet.sessionId).sort()).toEqual([
      'room-earth',
      'room-mars',
      'standalone',
    ]);
    expect(projection.runningPlanets.filter((planet) => planet.roomId === 'room-1')).toHaveLength(2);
    expect(projection.runningPlanets.find((planet) => planet.sessionId === 'room-earth')).toMatchObject({
      name: '实现伙伴',
      participantId: 'earth',
      status: 'running',
      running: true,
    });
    expect(projection.relationships).toEqual([]);
  });

  it('never claims a stale busy snapshot or a terminal Session is running', () => {
    const projection = projectStellarAgents({
      nowMs: NOW,
      sessions: [
        session('stale', 'busy'),
        session('done', 'completed'),
        session('faulted', 'faulted'),
      ],
      rooms: [],
      sessionStatusFresh: false,
      roomStatusFresh: false,
    });

    expect(projection.runningPlanets).toEqual([]);
    expect(projection.planets.find((planet) => planet.sessionId === 'stale')).toMatchObject({
      status: 'unknown',
      running: false,
    });
    expect(projection.planets.find((planet) => planet.sessionId === 'done')).toMatchObject({
      status: 'terminal',
      running: false,
    });
    expect(projection.planets.find((planet) => planet.sessionId === 'faulted')).toMatchObject({
      status: 'attention',
      running: false,
    });
    expect(projection.limitations).toContain('session-status-stale');
  });

  it('uses the supplied clock to reject an over-age snapshot', () => {
    const projection = projectStellarAgents({
      nowMs: NOW,
      maxSnapshotAgeMs: 60_000,
      sessionSnapshotAtMs: NOW - 60_001,
      sessions: [session('old', 'busy')],
      rooms: [],
      sessionStatusFresh: true,
      roomStatusFresh: true,
    });

    expect(projection.runningPlanets).toEqual([]);
    expect(projection.limitations).toContain('session-status-stale');
  });

  it('keeps identity, position, style and deterministic order across input reorder', () => {
    const sessions = [
      session('a', 'busy', { updatedAtMs: NOW - 5_000 }),
      session('b', 'busy', { updatedAtMs: NOW - 4_000 }),
      session('c', 'busy', { updatedAtMs: NOW - 3_000 }),
    ];
    const first = projectStellarAgents({
      nowMs: NOW,
      sessions,
      rooms: [],
      sessionStatusFresh: true,
      roomStatusFresh: true,
    });
    const second = projectStellarAgents({
      nowMs: NOW,
      sessions: [sessions[2]!, sessions[0]!, sessions[1]!],
      rooms: [],
      sessionStatusFresh: true,
      roomStatusFresh: true,
    });

    expect(second.planets.map((planet) => planet.sessionId)).toEqual(first.planets.map((planet) => planet.sessionId));
    for (const id of ['a', 'b', 'c']) {
      const left = first.planets.find((planet) => planet.sessionId === id)!;
      const right = second.planets.find((planet) => planet.sessionId === id)!;
      expect(right.position).toEqual(left.position);
      expect(right.style).toEqual(left.style);
      expect(right.key).toBe(`session:${id}`);
      expect(right.position.x).toBeGreaterThanOrEqual(0);
      expect(right.position.x).toBeLessThanOrEqual(1);
      expect(right.position.y).toBeGreaterThanOrEqual(0);
      expect(right.position.y).toBeLessThanOrEqual(1);
    }
  });

  it('projects an explicit parent Session link but does not invent Room peer edges', () => {
    const projection = projectStellarAgents({
      nowMs: NOW,
      sessions: [
        session('parent', 'busy', { title: '父 Session' }),
        session('child', 'busy', {
          title: '子 Agent',
          parentSessionId: 'parent',
          roomParticipant: { roomId: 'room-1', participantId: 'child', status: 'active' },
        }),
        session('peer', 'busy', {
          roomParticipant: { roomId: 'room-1', participantId: 'peer', status: 'active' },
        }),
      ],
      rooms: [room('room-1', [
        { id: 'child', sessionId: 'child', status: 'active', ordinal: 0 },
        { id: 'peer', sessionId: 'peer', status: 'active', ordinal: 1 },
      ])],
      sessionStatusFresh: true,
      roomStatusFresh: true,
    });

    expect(projection.relationships).toEqual([{
      id: 'parent-child:parent->child',
      kind: 'parent-child',
      fromSessionId: 'parent',
      toSessionId: 'child',
      evidence: 'session.parentSessionId',
    }]);
    expect(projection.relationships).not.toContainEqual(expect.objectContaining({
      fromSessionId: 'child',
      toSessionId: 'peer',
    }));
    expect(projection.planets.find((planet) => planet.sessionId === 'child')?.kind).toBe('subagent');
  });

  it('does not turn a Room-only member into a running planet without individual Session state', () => {
    const projection = projectStellarAgents({
      nowMs: NOW,
      sessions: [],
      rooms: [room('room-1', [
        { id: 'participant-1', sessionId: 'missing-session', displayName: 'Room 伙伴', status: 'active', ordinal: 0 },
      ])],
      sessionStatusFresh: true,
      roomStatusFresh: true,
    });

    expect(projection.runningPlanets).toEqual([]);
    expect(projection.planets.find((planet) => planet.sessionId === 'missing-session')).toMatchObject({
      status: 'unknown',
      running: false,
      name: 'Room 伙伴',
    });
    expect(projection.limitations).toContain('individual-session-state-missing');
  });
});
