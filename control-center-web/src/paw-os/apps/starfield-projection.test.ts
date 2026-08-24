import { describe, expect, it } from 'vitest';
import type { AgentSubagentRunV1 } from '@/contracts/generated/agent-subagent-run.v1';
import type { RoomSummary } from '@/features/rooms/room-types';
import type { RoomFocusProjection } from './room-focus-projection';
import {
  buildGalaxyStarfield,
  buildRoomStarfield,
  buildSessionStarfield,
  STARFIELD_VIEWBOX,
} from './starfield-projection';

function subagentRun(
  id: string,
  state: AgentSubagentRunV1['state'],
  overrides: Partial<AgentSubagentRunV1> = {},
): AgentSubagentRunV1 {
  return {
    schemaVersion: 'rag-ime.agent-subagent-run.v1',
    id,
    nodeId: `node:${id}`,
    attemptId: `attempt:${id}`,
    attemptNumber: 1,
    predecessorAttemptId: '',
    ownerRunId: '',
    parentRunId: '',
    depth: 1,
    batchId: 'batch:starfield',
    childSessionId: `child:${id}`,
    todoTask: '',
    todoPhase: '',
    templateId: 'researcher',
    templateVersion: '1',
    ordinal: 0,
    task: `任务 ${id}`,
    expectedOutput: '',
    acceptanceCriteria: [],
    launchDigest: {
      schemaVersion: 'rag-ime.agent-subagent-launch-digest.v1',
      contextMode: 'fresh',
      templateId: 'researcher',
      templateVersion: '1',
      modelProfile: 'default',
      thinkingLevel: 'medium',
      toolProfileVersion: 'subagent-readonly-v1',
      toolAllowlistMode: 'profile',
      tools: [],
      piSkillsEnabled: false,
      codexSkillsEnabled: false,
      workspaceAccess: 'read_only',
      workspaceRootCount: 0,
      outputContract: { required: false, schemaSha256: '' },
      extensionRuntime: 'pi_host_managed',
    },
    contract: { status: 'not_requested', error: '', toolCallId: '', validatedAtMs: null },
    state,
    budget: { maxTurns: 8, maxToolCalls: 12, maxTotalTokens: 16_000, maxDurationMs: 60_000, maxOutputChars: 8_000 },
    usage: { turnCount: 1, toolCount: 1, totalTokens: 100 },
    result: {},
    error: '',
    resultContextScheduledAtMs: null,
    createdAtMs: 1_000,
    startedAtMs: null,
    updatedAtMs: 1_000,
    completedAtMs: null,
    ...overrides,
  };
}

function roomFocus(): RoomFocusProjection {
  const partner = (
    participantId: string,
    ordinalName: string,
    state: RoomFocusProjection['partners'][number]['state'],
  ): RoomFocusProjection['partners'][number] => ({
    participantId,
    sessionId: `session:${participantId}`,
    displayName: `${ordinalName} 伙伴`,
    celestialName: ordinalName,
    state,
    ownedWorkItemIds: state === 'running' ? ['work-1'] : [],
    currentAction: state === 'running' ? '正在实现投影' : '等待新的工作项',
    unread: false,
  });
  return {
    goal: { title: '交付星空模式', description: '', rootId: 'root-1', state: 'running' },
    workItems: [],
    partners: [
      partner('participant-earth', 'Earth', 'running'),
      partner('participant-mars', 'Mars', 'completed'),
      partner('participant-venus', 'Venus', 'blocked'),
    ],
    handoffs: [
      {
        id: 'handoff-live',
        sourceParticipantId: 'participant-earth',
        targetParticipantId: 'participant-mars',
        task: '把投影结果交给 Mars 复核',
        state: 'dispatched',
        createdAtMs: 2_000,
      },
      {
        id: 'handoff-done',
        sourceParticipantId: 'participant-mars',
        targetParticipantId: 'participant-venus',
        task: '归档复核结论',
        state: 'completed',
        createdAtMs: 1_000,
      },
      {
        id: 'handoff-unknown-target',
        sourceParticipantId: 'participant-earth',
        targetParticipantId: 'participant-ghost',
        state: 'dispatched',
        createdAtMs: 3_000,
      },
    ],
    rootEvidence: [],
    counts: { active: 1, review: 0, blocked: 1, completed: 1 },
  };
}

describe('starfield projection', () => {
  it('keeps every Session moon on its real subagent identity with a truthful state', () => {
    const runs = [
      subagentRun('run-live', 'running', { createdAtMs: 1_000 }),
      subagentRun('run-failed', 'failed', { createdAtMs: 2_000, error: '验收未通过' }),
      subagentRun('run-queued', 'queued', { createdAtMs: 3_000 }),
    ];
    const model = buildSessionStarfield('session-1', runs);

    expect(model.moons.map((moon) => moon.runId)).toEqual(['run-live', 'run-failed', 'run-queued']);
    const live = model.moons.find((moon) => moon.runId === 'run-live')!;
    const failed = model.moons.find((moon) => moon.runId === 'run-failed')!;
    const queued = model.moons.find((moon) => moon.runId === 'run-queued')!;
    expect(live.active).toBe(true);
    expect(live.attention).toBe(false);
    expect(live.stateLabel).toBe('进行中');
    expect(failed.active).toBe(false);
    expect(failed.attention).toBe(true);
    expect(failed.stateLabel).toBe('失败');
    expect(queued.active).toBe(true);
    expect(queued.stateLabel).toBe('排队中');
    expect(model.counts).toEqual({ active: 2, returned: 1, attention: 1 });
  });

  it('lays Session orbits deterministically inside the stage', () => {
    const runs = Array.from({ length: 9 }, (_, index) => subagentRun(`run-${index}`, 'completed', { createdAtMs: index }));
    const first = buildSessionStarfield('session-1', runs);
    const second = buildSessionStarfield('session-1', runs);

    expect(second).toEqual(first);
    for (const moon of first.moons) {
      expect(moon.orbit.radius).toBeGreaterThanOrEqual(150);
      expect(moon.orbit.radius).toBeLessThanOrEqual(STARFIELD_VIEWBOX / 2 - 50);
      expect(moon.orbit.periodS).toBeGreaterThan(0);
    }
    // Nine moons share at most six rings; rings stay distinct radii.
    expect(first.ringRadii.length).toBeLessThanOrEqual(6);
    expect(new Set(first.ringRadii).size).toBe(first.ringRadii.length);
  });

  it('projects the Room as one solar system with real participant identities', () => {
    const model = buildRoomStarfield(roomFocus());

    expect(model.goal).toMatchObject({ title: '交付星空模式', state: 'running', stateLabel: '进行中' });
    expect(model.planets.map((planet) => planet.participantId)).toEqual([
      'participant-earth',
      'participant-mars',
      'participant-venus',
    ]);
    const earth = model.planets[0]!;
    const venus = model.planets[2]!;
    expect(earth.celestialName).toBe('Earth');
    expect(earth.sessionId).toBe('session:participant-earth');
    expect(earth.active).toBe(true);
    expect(venus.attention).toBe(true);
    expect(venus.stateLabel).toBe('阻塞');
    for (const planet of model.planets) {
      expect(planet.x).toBeGreaterThanOrEqual(0);
      expect(planet.x).toBeLessThanOrEqual(STARFIELD_VIEWBOX);
      expect(planet.y).toBeGreaterThanOrEqual(0);
      expect(planet.y).toBeLessThanOrEqual(STARFIELD_VIEWBOX);
    }
  });

  it('draws handoff beams only between real planets and marks in-flight handoffs live', () => {
    const model = buildRoomStarfield(roomFocus());

    expect(model.beams.map((beam) => beam.id)).toEqual(['handoff-live', 'handoff-done']);
    const live = model.beams.find((beam) => beam.id === 'handoff-live')!;
    const done = model.beams.find((beam) => beam.id === 'handoff-done')!;
    expect(live.live).toBe(true);
    expect(done.live).toBe(false);
    const earth = model.planets[0]!;
    const mars = model.planets[1]!;
    expect(live.x1).toBe(earth.x);
    expect(live.y1).toBe(earth.y);
    expect(live.x2).toBe(mars.x);
    expect(live.y2).toBe(mars.y);
  });

  it('maps every Room to one star system in the galaxy, newest at the core', () => {
    const room = (id: string, updatedAtMs: number, status = 'active', participantCount = 3): RoomSummary => ({
      id,
      title: `Room ${id}`,
      status,
      routingPolicy: 'parallel',
      moderatorParticipantId: '',
      updatedAtMs,
      participants: Array.from({ length: participantCount }, (_, index) => ({
        id: `${id}-p${index}`,
        sessionId: `${id}-s${index}`,
        roleId: 'role',
        roleVersion: '1',
        displayName: `伙伴 ${index}`,
        status: 'active',
        ordinal: index,
      })),
    });
    const rooms = [
      room('room-old', 1_000, 'archived', 2),
      room('room-new', 3_000, 'active', 4),
      room('room-mid', 2_000, 'active', 3),
    ];
    const model = buildGalaxyStarfield(rooms);

    expect(model.totalRooms).toBe(3);
    expect(model.systems.map((system) => system.roomId)).toEqual(['room-new', 'room-mid', 'room-old']);
    const core = model.systems[0]!;
    expect(core.x).toBe(STARFIELD_VIEWBOX / 2);
    expect(core.y).toBe(STARFIELD_VIEWBOX / 2);
    expect(core.active).toBe(true);
    expect(core.participantCount).toBe(4);
    expect(model.systems[2]!.active).toBe(false);
    for (const system of model.systems) {
      expect(system.x).toBeGreaterThanOrEqual(0);
      expect(system.x).toBeLessThanOrEqual(STARFIELD_VIEWBOX);
      expect(system.y).toBeGreaterThanOrEqual(0);
      expect(system.y).toBeLessThanOrEqual(STARFIELD_VIEWBOX);
    }
    expect(buildGalaxyStarfield(rooms)).toEqual(model);
  });

  it('caps the galaxy at a readable system count while reporting the real total', () => {
    const rooms = Array.from({ length: 30 }, (_, index) => ({
      id: `room-${index}`,
      title: `Room ${index}`,
      status: 'active',
      routingPolicy: 'parallel' as const,
      moderatorParticipantId: '',
      updatedAtMs: index,
      participants: [],
    }));
    const model = buildGalaxyStarfield(rooms);

    expect(model.systems).toHaveLength(24);
    expect(model.totalRooms).toBe(30);
  });
});
