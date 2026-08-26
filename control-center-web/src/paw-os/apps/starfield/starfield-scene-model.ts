/**
 * 星空 v2 scene model — one renderer-agnostic celestial layout shared by the
 * WebGL stage and the 2D fallback.
 *
 * Adapters below project the tested starfield projections (Session moons,
 * Room solar system, Room galaxy) into world-space bodies with deterministic
 * geometry (radius, phase, inclination, size) and an honest motion profile
 * from `starfield-motion`. Every body keeps its real Runtime identity as
 * `id`, so a pick in either renderer always lands on the real record.
 */

import {
  starfieldUnit,
  STARFIELD_VIEWBOX,
  type GalaxyStarfieldModel,
  type RoomStarfieldModel,
  type SessionStarfieldModel,
} from '../starfield-projection';
import { roomCollaborationRoleLabel } from '@/features/rooms/room-copy';
import {
  galaxySystemMotion,
  roomBodyMotion,
  sessionCoreMotion,
  subagentMotion,
  type StarfieldMotion,
} from './starfield-motion';

/** World-space stage radius; projection viewbox radius (500) maps onto it. */
export const SCENE_STAGE_RADIUS = 10;

const VIEWBOX_TO_WORLD = SCENE_STAGE_RADIUS / (STARFIELD_VIEWBOX / 2);

export type SceneBodyKind = 'moon' | 'planet' | 'star';
export type SceneCenterKind = 'planet' | 'sun' | 'core';
export type SceneMode = 'session' | 'room' | 'galaxy';

export interface SceneBody {
  /** Real Runtime identity: subagent run id / participant id / Room id. */
  id: string;
  kind: SceneBodyKind;
  title: string;
  subtitle: string;
  /** One-line honest description for hover / feed cross-reference. */
  detail: string;
  /**
   * The real work this body is carrying right now — a WorkItem objective, a
   * partner's current action, a subagent's task. Empty when the Runtime does
   * not report any; both renderers then simply omit the task line.
   */
  task: string;
  /**
   * No live work behind this body (settled, stopped, offline, or never
   * assigned). Both renderers quiet it down so the working bodies read first.
   */
  idle: boolean;
  /** Semi-major axis in world units (circular when eccentricity is 0). */
  orbitRadius: number;
  phaseRad: number;
  inclinationRad: number;
  /**
   * Visual eccentricity 0..~0.45 (q-jade solar-system seasoning). Never
   * claims real ephemeris — only decorates the sky from a stable seed.
   */
  eccentricity: number;
  /** Axial tilt applied before self-spin, radians. */
  axialTiltRad: number;
  size: number;
  /** Stable palette slot 0..5 — also keys the surface archetype/texture. */
  paletteIndex: number;
  /** Deterministic 0.85..1.15 so working bodies never move in lockstep. */
  speedFactor: number;
  motion: StarfieldMotion;
}

export interface SceneCenter {
  id: 'center';
  kind: SceneCenterKind;
  title: string;
  subtitle: string;
  size: number;
  motion: StarfieldMotion;
}

export interface SceneLink {
  id: string;
  fromId: string;
  toId: string;
  live: boolean;
  failed: boolean;
  label: string;
}

export interface StarfieldSceneModel {
  seed: string;
  mode: SceneMode;
  center: SceneCenter | null;
  bodies: SceneBody[];
  /** Unique orbit radii (world units) for ring rendering, inner → outer. */
  ringRadii: number[];
  links: SceneLink[];
}

/**
 * Only handoffs actually in flight earn a beam label, and only the newest few:
 * more than three floating strings turn the work chart back into noise. Both
 * renderers read this so the 2D fallback names exactly the same beams.
 */
export const LIVE_BEAM_LABEL_LIMIT = 3;

export function liveBeamLinks(model: StarfieldSceneModel): SceneLink[] {
  return model.links
    .filter((link) => link.live && link.label)
    .slice(-LIVE_BEAM_LABEL_LIMIT);
}

/** One accessible-name convention shared by the 3D label layer and 2D sky. */
export function sceneBodyAriaLabel(mode: SceneMode, body: SceneBody): string {
  if (mode === 'session') return `${body.title} 卫星 · ${body.detail} · ${body.subtitle}`;
  if (mode === 'room') return `${body.title}，${body.subtitle}${body.task ? `，${body.task}` : ''}`;
  return `${body.title} · ${body.subtitle}`;
}

/**
 * Content signature of a scene model. The model is plain deterministic data
 * built in stable key order, so equal content always serializes equally —
 * the WebGL stage uses this to skip a full scene rebuild (geometry, GPU
 * uploads) when a poll tick returned an unchanged sky.
 */
export function sceneModelSignature(model: StarfieldSceneModel): string {
  return JSON.stringify(model);
}

function speedFactor(id: string): number {
  return Math.round((0.85 + starfieldUnit(`${id}:speed`) * 0.3) * 1000) / 1000;
}

function inclination(seed: string, spreadRad = 0.24): number {
  return Math.round((starfieldUnit(seed) - 0.5) * spreadRad * 1000) / 1000;
}

/** Mild eccentricity so orbits read as ellipses without crushing the stage. */
function eccentricity(seed: string, max = 0.32): number {
  return Math.round(starfieldUnit(seed) * max * 1000) / 1000;
}

function axialTilt(seed: string, spreadRad = 0.45): number {
  return Math.round((starfieldUnit(seed) - 0.5) * spreadRad * 1000) / 1000;
}

function uniqueSortedRadii(bodies: readonly SceneBody[]): number[] {
  return [...new Set(bodies.map((body) => Math.round(body.orbitRadius * 100) / 100))]
    .sort((left, right) => left - right);
}

/* ------------------------------------------------------------------ */
/* Session: core planet + subagent moons                               */
/* ------------------------------------------------------------------ */

export function buildSessionSceneModel(
  model: SessionStarfieldModel,
  options: { busy: boolean; sessionTitle: string },
): StarfieldSceneModel {
  const bodies = model.moons.map((moon): SceneBody => ({
    id: moon.runId,
    kind: 'moon',
    title: moon.templateLabel,
    subtitle: moon.stateLabel,
    detail: moon.task || '未公开任务说明',
    task: moon.task.trim(),
    // A returned or aborted run is history: it keeps its identity and ring
    // but must not compete with the runs still doing work.
    idle: !moon.active && !moon.attention,
    orbitRadius: Math.round(moon.orbit.radius * VIEWBOX_TO_WORLD * 100) / 100,
    phaseRad: Math.round((moon.orbit.angleDeg * Math.PI) / 180 * 1000) / 1000,
    inclinationRad: inclination(`${model.sessionId}:ring:${moon.orbit.ring}`),
    eccentricity: eccentricity(`${moon.runId}:e`, 0.18),
    axialTiltRad: axialTilt(`${moon.runId}:tilt`, 0.35),
    size: 0.3,
    paletteIndex: Math.floor(starfieldUnit(`${moon.runId}:hue`) * 6),
    speedFactor: speedFactor(moon.runId),
    motion: subagentMotion(moon.state, moon.attention),
  }));
  return {
    seed: model.sessionId,
    mode: 'session',
    center: {
      id: 'center',
      kind: 'planet',
      title: options.sessionTitle,
      subtitle: options.busy ? '正在执行' : 'Session 主星',
      size: 1.2,
      motion: sessionCoreMotion(options.busy),
    },
    bodies,
    ringRadii: uniqueSortedRadii(bodies),
    links: [],
  };
}

/* ------------------------------------------------------------------ */
/* Room: Sol + partner planets + handoff beams                         */
/* ------------------------------------------------------------------ */

/**
 * Sol is the Room facilitator's star, not scenery: it only lights when a
 * participant is actually hosting this Room. `model.hasCoordinator` carries
 * that one shared decision (`roomFocusHasCoordinator`) down from the Room
 * focus projection; a Room where nobody hosts renders a partner-only
 * constellation around an empty origin instead of inventing a center.
 */
export function buildRoomSceneModel(
  model: RoomStarfieldModel,
  roomId: string,
): StarfieldSceneModel {
  const bodies = model.planets.map((planet): SceneBody => ({
    id: planet.participantId,
    kind: 'planet',
    title: planet.celestialName,
    subtitle: `${roomCollaborationRoleLabel(planet.collaborationRole)} · ${planet.stateLabel}`,
    detail: planet.currentAction,
    // What this partner is actually working on — the headline of the sky.
    task: planet.currentAction.trim(),
    // Settled, stopped or offline partners still hold their orbit; they just
    // stop competing with the partners carrying live work.
    idle: !planet.active && !planet.attention,
    orbitRadius: Math.round(planet.radius * VIEWBOX_TO_WORLD * 100) / 100,
    phaseRad: Math.round((planet.angleDeg * Math.PI) / 180 * 1000) / 1000,
    inclinationRad: inclination(`${roomId}:orbit:${planet.orbitIndex}`, 0.18),
    // Room solar system: slightly more eccentric so partner paths diverge.
    eccentricity: eccentricity(`${planet.participantId}:e`, 0.36),
    axialTiltRad: axialTilt(`${planet.participantId}:tilt`, 0.55),
    size: 0.56,
    paletteIndex: planet.orbitIndex % 6,
    speedFactor: speedFactor(planet.participantId),
    motion: roomBodyMotion(planet.state),
  }));
  const hosted = model.hasCoordinator;
  const bodyIds = new Set(bodies.map((body) => body.id));
  return {
    seed: roomId,
    mode: 'room',
    center: hosted
      ? {
        id: 'center',
        kind: 'sun',
        title: 'Sol',
        subtitle: model.goal.title,
        size: 1.5,
        motion: roomBodyMotion(model.goal.state),
      }
      : null,
    bodies,
    ringRadii: uniqueSortedRadii(bodies),
    // A beam must leave something the user can see. Without Sol, a handoff
    // whose source is not a planet on stage has no honest origin to draw.
    links: model.beams
      .filter((beam) => (
        bodyIds.has(beam.targetParticipantId)
        && (hosted || bodyIds.has(beam.sourceParticipantId))
      ))
      .map((beam) => ({
        id: beam.id,
        fromId: beam.sourceParticipantId,
        toId: beam.targetParticipantId,
        live: beam.live,
        failed: beam.state === 'failed',
        label: beam.label,
      })),
  };
}

/* ------------------------------------------------------------------ */
/* Galaxy: every Room one star system                                  */
/* ------------------------------------------------------------------ */

export function buildGalaxySceneModel(model: GalaxyStarfieldModel): StarfieldSceneModel {
  const center = STARFIELD_VIEWBOX / 2;
  const bodies = model.systems.map((system): SceneBody => {
    const dx = system.x - center;
    const dy = system.y - center;
    return {
      id: system.roomId,
      kind: 'star',
      title: system.title,
      subtitle: `${system.participantCount} 位伙伴 · ${system.active ? '活跃' : '已归档'}`,
      detail: system.active ? '这间 Room 正在使用中' : '这间 Room 已归档',
      // A galaxy star stands for a whole Room, not one task: the sky never
      // claims to know what that Room is working on this second.
      task: '',
      idle: !system.active,
      orbitRadius: Math.round(Math.hypot(dx, dy) * VIEWBOX_TO_WORLD * 100) / 100,
      phaseRad: Math.round(Math.atan2(dy, dx) * 1000) / 1000,
      inclinationRad: inclination(`${system.roomId}:tilt`, 0.14),
      // Galaxy stars sit on fixed polar positions — keep circular.
      eccentricity: 0,
      axialTiltRad: axialTilt(`${system.roomId}:spin`, 0.4),
      size: Math.round((0.42 + system.scale * 0.28) * 100) / 100,
      paletteIndex: system.hueIndex,
      speedFactor: speedFactor(system.roomId),
      motion: galaxySystemMotion(system.active),
    };
  });
  return {
    seed: model.systems.map((system) => system.roomId).join('|') || 'galaxy',
    mode: 'galaxy',
    center: null,
    bodies,
    ringRadii: [],
    links: [],
  };
}
