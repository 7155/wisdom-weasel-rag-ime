import { describe, expect, it } from 'vitest';
import type { RoomStarfieldModel, SessionStarfieldModel } from '../starfield-projection';
import { buildGalaxyStarfield } from '../starfield-projection';
import {
  buildGalaxySceneModel,
  buildRoomSceneModel,
  buildSessionSceneModel,
  SCENE_STAGE_RADIUS,
} from './starfield-scene-model';
import { WORKING_ORBIT_RAD_PER_S } from './starfield-motion';

function sessionModel(): SessionStarfieldModel {
  const moon = (
    runId: string,
    state: SessionStarfieldModel['moons'][number]['state'],
    active: boolean,
    attention = false,
  ): SessionStarfieldModel['moons'][number] => ({
    runId,
    parentRunId: '',
    templateId: 'researcher',
    templateLabel: '研究员',
    task: `任务 ${runId}`,
    state,
    stateLabel: state === 'running' ? '进行中' : '已完成',
    active,
    attention,
    contextMode: 'fresh',
    orbit: { ring: 0, radius: 320, angleDeg: 120, periodS: 60 },
  });
  return {
    sessionId: 'session-1',
    moons: [moon('run-live', 'running', true), moon('run-done', 'completed', false)],
    ringRadii: [320],
    counts: { active: 1, returned: 1, attention: 0 },
  };
}

function roomModel(): RoomStarfieldModel {
  const planet = (
    participantId: string,
    state: RoomStarfieldModel['planets'][number]['state'],
    orbitIndex: number,
  ): RoomStarfieldModel['planets'][number] => ({
    participantId,
    sessionId: `session:${participantId}`,
    celestialName: orbitIndex === 0 ? 'Earth' : 'Mars',
    displayName: `${participantId} 伙伴`,
    state,
    stateLabel: state === 'running' ? '进行中' : '阻塞',
    active: state === 'running',
    attention: state === 'blocked',
    orbitIndex,
    radius: 200 + orbitIndex * 100,
    angleDeg: orbitIndex * 90,
    x: 500,
    y: 300,
    ownedWorkCount: 1,
    currentAction: '正在实现投影',
  });
  return {
    goal: { title: '交付星空 v2', state: 'running', stateLabel: '进行中' },
    planets: [planet('participant-earth', 'running', 0), planet('participant-mars', 'blocked', 1)],
    beams: [{
      id: 'handoff-1',
      sourceParticipantId: 'participant-earth',
      targetParticipantId: 'participant-mars',
      x1: 0,
      y1: 0,
      x2: 0,
      y2: 0,
      state: 'dispatched',
      live: true,
      label: '交接复核',
    }],
    counts: { active: 1, review: 0, blocked: 1, completed: 0 },
  };
}

describe('starfield scene model', () => {
  it('keeps Session bodies on real run identities with honest motion in world space', () => {
    const scene = buildSessionSceneModel(sessionModel(), { busy: true, sessionTitle: '当前 Session' });

    expect(scene.mode).toBe('session');
    expect(scene.center).toMatchObject({ id: 'center', kind: 'planet', title: '当前 Session', subtitle: '正在执行' });
    expect(scene.center?.motion.working).toBe(true);
    // Prominent bodies carry real surface maps: gas-giant core, lunar moons.
    expect(scene.center?.textureKey).toBe('jupiter');
    expect(scene.bodies.every((body) => body.textureKey === 'moon')).toBe(true);
    expect(scene.bodies.map((body) => body.id)).toEqual(['run-live', 'run-done']);
    const live = scene.bodies[0]!;
    const done = scene.bodies[1]!;
    expect(live.motion.orbitRadPerS).toBe(WORKING_ORBIT_RAD_PER_S);
    expect(done.motion.working).toBe(false);
    for (const body of scene.bodies) {
      expect(body.orbitRadius).toBeGreaterThan(0);
      expect(body.orbitRadius).toBeLessThanOrEqual(SCENE_STAGE_RADIUS);
      expect(body.speedFactor).toBeGreaterThanOrEqual(0.85);
      expect(body.speedFactor).toBeLessThanOrEqual(1.15);
      expect(Math.abs(body.inclinationRad)).toBeLessThan(0.2);
    }
    // Deterministic: the same projection always yields the same sky.
    expect(buildSessionSceneModel(sessionModel(), { busy: true, sessionTitle: '当前 Session' })).toEqual(scene);
  });

  it('projects the Room into Sol, partner planets and real handoff links', () => {
    const scene = buildRoomSceneModel(roomModel(), 'room-1');

    expect(scene.center).toMatchObject({ kind: 'sun', title: 'Sol', subtitle: '交付星空 v2' });
    expect(scene.center?.motion.working).toBe(true);
    // Partners named after real planets get the matching NASA-style map.
    expect(scene.center?.textureKey).toBe('sun');
    expect(scene.bodies.map((body) => body.textureKey)).toEqual(['earth', 'mars']);
    expect(scene.bodies.map((body) => body.id)).toEqual(['participant-earth', 'participant-mars']);
    expect(scene.bodies[0]?.motion.working).toBe(true);
    expect(scene.bodies[1]?.motion.ring).toBe('attention');
    expect(scene.links).toEqual([{
      id: 'handoff-1',
      fromId: 'participant-earth',
      toId: 'participant-mars',
      live: true,
      failed: false,
      label: '交接复核',
    }]);
    expect(scene.ringRadii).toHaveLength(2);
  });

  it('maps every Room in the galaxy to a star with polar world coordinates', () => {
    const rooms = [
      { id: 'room-a', title: 'Room A', status: 'active', routingPolicy: 'parallel' as const, moderatorParticipantId: '', updatedAtMs: 2_000, participants: [] },
      { id: 'room-b', title: 'Room B', status: 'archived', routingPolicy: 'parallel' as const, moderatorParticipantId: '', updatedAtMs: 1_000, participants: [] },
    ];
    const scene = buildGalaxySceneModel(buildGalaxyStarfield(rooms));

    expect(scene.mode).toBe('galaxy');
    expect(scene.center).toBeNull();
    expect(scene.bodies.map((body) => body.id)).toEqual(['room-a', 'room-b']);
    // Newest Room sits at the galactic core.
    expect(scene.bodies[0]?.orbitRadius).toBe(0);
    expect(scene.bodies[1]?.orbitRadius).toBeGreaterThan(0);
    expect(scene.bodies[0]?.motion.working).toBe(false);
    expect(scene.bodies[1]?.motion.tone).toBe('muted');
    // Galaxy stars stay emissive points of light — no surface maps to fetch.
    expect(scene.bodies.every((body) => body.textureKey === null)).toBe(true);
  });
});
