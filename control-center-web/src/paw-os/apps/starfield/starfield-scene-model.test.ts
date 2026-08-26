import { describe, expect, it } from 'vitest';
import type { RoomStarfieldModel, SessionStarfieldModel } from '../starfield-projection';
import { buildGalaxyStarfield } from '../starfield-projection';
import { roomFocusHasCoordinator } from '../room-focus-projection';
import {
  buildGalaxySceneModel,
  buildRoomSceneModel,
  buildSessionSceneModel,
  liveBeamLinks,
  SCENE_STAGE_RADIUS,
  sceneBodyAriaLabel,
  sceneModelSignature,
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

function roomModel(options: { hosted?: boolean; hostState?: RoomStarfieldModel['planets'][number]['state'] } = {}): RoomStarfieldModel {
  const hosted = options.hosted ?? true;
  const planet = (
    participantId: string,
    state: RoomStarfieldModel['planets'][number]['state'],
    orbitIndex: number,
    collaborationRole: RoomStarfieldModel['planets'][number]['collaborationRole'] = orbitIndex === 0 && hosted ? 'coordinator' : 'implementer',
  ): RoomStarfieldModel['planets'][number] => ({
    participantId,
    sessionId: `session:${participantId}`,
    celestialName: orbitIndex === 0 ? 'Earth' : 'Mars',
    displayName: `${participantId} 伙伴`,
    collaborationRole,
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
  const planets = [
    planet('participant-earth', options.hostState ?? 'running', 0),
    planet('participant-mars', 'blocked', 1),
  ];
  return {
    goal: { title: '交付星空 v2', state: 'running', stateLabel: '进行中' },
    // Derived exactly as `buildRoomStarfield` does, so the fixture never
    // claims a host the shared gate would not grant.
    hasCoordinator: roomFocusHasCoordinator(planets),
    planets,
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
    expect(scene.bodies.map((body) => body.id)).toEqual(['run-live', 'run-done']);
    const live = scene.bodies[0]!;
    const done = scene.bodies[1]!;
    expect(live.motion.orbitRadPerS).toBe(WORKING_ORBIT_RAD_PER_S);
    expect(done.motion.working).toBe(false);
    // The run's real task travels with the moon; a returned run goes quiet.
    expect(live).toMatchObject({ task: '任务 run-live', idle: false });
    expect(done).toMatchObject({ task: '任务 run-done', idle: true });
    for (const body of scene.bodies) {
      expect(body.orbitRadius).toBeGreaterThan(0);
      expect(body.orbitRadius).toBeLessThanOrEqual(SCENE_STAGE_RADIUS);
      expect(body.speedFactor).toBeGreaterThanOrEqual(0.85);
      expect(body.speedFactor).toBeLessThanOrEqual(1.15);
      expect(Math.abs(body.inclinationRad)).toBeLessThan(0.2);
      expect(body.eccentricity).toBeGreaterThanOrEqual(0);
      expect(body.eccentricity).toBeLessThanOrEqual(0.18);
      expect(Math.abs(body.axialTiltRad)).toBeLessThanOrEqual(0.2);
    }
    // Deterministic: the same projection always yields the same sky.
    expect(buildSessionSceneModel(sessionModel(), { busy: true, sessionTitle: '当前 Session' })).toEqual(scene);
  });

  it('signs equal skies equally and motion changes distinctly', () => {
    const base = sessionModel();
    const same = sceneModelSignature(buildSessionSceneModel(base, { busy: true, sessionTitle: 'S' }));
    expect(sceneModelSignature(buildSessionSceneModel(sessionModel(), { busy: true, sessionTitle: 'S' }))).toBe(same);
    const flipped = sessionModel();
    flipped.moons[0]!.state = 'completed';
    flipped.moons[0]!.active = false;
    expect(sceneModelSignature(buildSessionSceneModel(flipped, { busy: true, sessionTitle: 'S' }))).not.toBe(same);
  });

  it('omits Sol until a coordinator hosts the Room', () => {
    const dormant = buildRoomSceneModel({ ...roomModel(), hasCoordinator: false }, 'room-1');
    expect(dormant.center).toBeNull();
  });

  it('projects the Room into Sol, partner planets and real handoff links', () => {
    const scene = buildRoomSceneModel(roomModel(), 'room-1');

    expect(scene.center).toMatchObject({ kind: 'sun', title: 'Sol', subtitle: '交付星空 v2' });
    expect(scene.center?.motion.working).toBe(true);
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
    for (const body of scene.bodies) {
      expect(body.eccentricity).toBeGreaterThanOrEqual(0);
      expect(body.eccentricity).toBeLessThanOrEqual(0.36);
      expect(Math.abs(body.axialTiltRad)).toBeLessThanOrEqual(0.3);
    }
  });

  it('puts the real work on every partner planet and quiets the ones with none', () => {
    const model = roomModel();
    model.planets[1]!.state = 'completed';
    model.planets[1]!.stateLabel = '已完成';
    model.planets[1]!.active = false;
    model.planets[1]!.attention = false;
    model.planets[1]!.currentAction = '等待新的工作项';
    const scene = buildRoomSceneModel(model, 'room-1');

    const [earth, mars] = scene.bodies;
    expect(earth).toMatchObject({ task: '正在实现投影', idle: false });
    // Settled partners keep their identity and orbit, but read as quiet.
    expect(mars).toMatchObject({ task: '等待新的工作项', idle: true });
    // The task is part of the accessible name, not only a visual line.
    expect(sceneBodyAriaLabel('room', earth!)).toBe('Earth，最终汇合与回复 · 进行中，正在实现投影');

    // Only handoffs actually in flight are named on their beam.
    expect(liveBeamLinks(scene).map((link) => link.label)).toEqual(['交接复核']);
  });

  it('lights Sol only while a connected coordinator hosts the Room', () => {
    const unhosted = buildRoomSceneModel(roomModel({ hosted: false }), 'room-1');
    expect(unhosted.center).toBeNull();
    // Partner-only constellation: every real planet and orbit stays.
    expect(unhosted.bodies.map((body) => body.id)).toEqual(['participant-earth', 'participant-mars']);
    expect(unhosted.ringRadii).toHaveLength(2);
    // A beam between two visible planets still has an honest origin.
    expect(unhosted.links.map((link) => link.id)).toEqual(['handoff-1']);

    // A coordinator who dropped off cannot host either.
    const offline = roomModel({ hostState: 'disconnected' });
    expect(buildRoomSceneModel(offline, 'room-1').center).toBeNull();

    // With no visible source and no Sol, a handoff from off-stage is dropped.
    const orphaned = roomModel({ hosted: false });
    orphaned.beams[0]!.sourceParticipantId = 'participant-gone';
    expect(buildRoomSceneModel(orphaned, 'room-1').links).toEqual([]);
    // The same beam is drawn from Sol once a facilitator hosts the Room.
    const hostedOrphan = roomModel();
    hostedOrphan.beams[0]!.sourceParticipantId = 'participant-gone';
    expect(buildRoomSceneModel(hostedOrphan, 'room-1').links).toHaveLength(1);
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
  });
});
