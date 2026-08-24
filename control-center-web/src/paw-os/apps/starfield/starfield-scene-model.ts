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
  orbitRadius: number;
  phaseRad: number;
  inclinationRad: number;
  size: number;
  /** Stable palette slot 0..5 for body hue variety. */
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

/** One accessible-name convention shared by the 3D label layer and 2D sky. */
export function sceneBodyAriaLabel(mode: SceneMode, body: SceneBody): string {
  if (mode === 'session') return `${body.title} 卫星 · ${body.detail} · ${body.subtitle}`;
  if (mode === 'room') return `${body.title}，${body.subtitle}`;
  return `${body.title} · ${body.subtitle}`;
}

function speedFactor(id: string): number {
  return Math.round((0.85 + starfieldUnit(`${id}:speed`) * 0.3) * 1000) / 1000;
}

function inclination(seed: string, spreadRad = 0.24): number {
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
    orbitRadius: Math.round(moon.orbit.radius * VIEWBOX_TO_WORLD * 100) / 100,
    phaseRad: Math.round((moon.orbit.angleDeg * Math.PI) / 180 * 1000) / 1000,
    inclinationRad: inclination(`${model.sessionId}:ring:${moon.orbit.ring}`),
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

export function buildRoomSceneModel(
  model: RoomStarfieldModel,
  roomId: string,
): StarfieldSceneModel {
  const bodies = model.planets.map((planet): SceneBody => ({
    id: planet.participantId,
    kind: 'planet',
    title: planet.celestialName,
    subtitle: `${planet.displayName} · ${planet.stateLabel}`,
    detail: planet.currentAction,
    orbitRadius: Math.round(planet.radius * VIEWBOX_TO_WORLD * 100) / 100,
    phaseRad: Math.round((planet.angleDeg * Math.PI) / 180 * 1000) / 1000,
    inclinationRad: inclination(`${roomId}:orbit:${planet.orbitIndex}`, 0.18),
    size: 0.56,
    paletteIndex: planet.orbitIndex % 6,
    speedFactor: speedFactor(planet.participantId),
    motion: roomBodyMotion(planet.state),
  }));
  return {
    seed: roomId,
    mode: 'room',
    center: {
      id: 'center',
      kind: 'sun',
      title: 'Sol',
      subtitle: model.goal.title,
      size: 1.5,
      motion: roomBodyMotion(model.goal.state),
    },
    bodies,
    ringRadii: uniqueSortedRadii(bodies),
    links: model.beams.map((beam) => ({
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
      orbitRadius: Math.round(Math.hypot(dx, dy) * VIEWBOX_TO_WORLD * 100) / 100,
      phaseRad: Math.round(Math.atan2(dy, dx) * 1000) / 1000,
      inclinationRad: inclination(`${system.roomId}:tilt`, 0.14),
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
