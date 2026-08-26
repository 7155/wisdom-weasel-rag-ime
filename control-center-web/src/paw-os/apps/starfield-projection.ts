/**
 * 星空 (starfield) visualization projections.
 *
 * Pure display projections over real Runtime records:
 * - one Session with its real subagent runs → a planet with orbiting moons;
 * - one Room focus projection → a whole solar system around Sol;
 * - many Rooms → a small galaxy where every Room is one star system.
 *
 * Celestial names stay display aliases only. Every body keeps its real
 * Runtime identity (Session id, subagent run id, Room id, participant id) and
 * a truthful state taken from the owning projection — this module never
 * invents running/idle/failed state. Geometry (orbit radius, angle, period)
 * is a deterministic function of those identities so the sky is stable
 * between renders and testable without randomness.
 */

import type { AgentSubagentRunV1 } from '@/contracts/generated/agent-subagent-run.v1';
import {
  isContractInvalid,
  subagentPresentationState,
  subagentStateLabel,
  subagentTemplateLabel,
  type SubagentPresentationState,
} from '@/features/agent/status/subagent-presentation';
import type { RoomSummary } from '@/features/rooms/room-types';
import {
  roomFocusStateLabel,
  roomFocusHasCoordinator,
  type RoomFocusPartner,
  type RoomFocusProjection,
  type RoomFocusState,
} from './room-focus-projection';

/** All charts share one square viewbox; positions below are viewbox units. */
export const STARFIELD_VIEWBOX = 1000;
const CENTER = STARFIELD_VIEWBOX / 2;

/** FNV-1a over the identity string: stable, dependency-free seeding. */
export function starfieldHash(seed: string): number {
  let hash = 0x811c9dc5;
  for (let index = 0; index < seed.length; index += 1) {
    hash ^= seed.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

/** Deterministic unit interval [0, 1) derived from an identity string. */
export function starfieldUnit(seed: string): number {
  return starfieldHash(seed) / 0x100000000;
}

/* ------------------------------------------------------------------ */
/* Session: one planet, real subagent runs as moons                    */
/* ------------------------------------------------------------------ */

export interface SessionStarfieldMoon {
  /** Real subagent run id — the click identity. */
  runId: string;
  parentRunId: string;
  templateId: AgentSubagentRunV1['templateId'];
  templateLabel: string;
  task: string;
  state: SubagentPresentationState;
  stateLabel: string;
  /** queued | running — the only states allowed to move. */
  active: boolean;
  /** failed | timed_out | contract_invalid — needs the user. */
  attention: boolean;
  contextMode: 'fresh' | 'fork';
  orbit: { ring: number; radius: number; angleDeg: number; periodS: number };
}

export interface SessionStarfieldModel {
  sessionId: string;
  moons: SessionStarfieldMoon[];
  /** Unique orbit radii, inner → outer, for ring rendering. */
  ringRadii: number[];
  counts: { active: number; returned: number; attention: number };
}

const SESSION_RING_MIN = 190;
const SESSION_RING_MAX = 442;
const SESSION_RING_CAP = 6;
const GOLDEN_ANGLE = 137.508;

export function buildSessionStarfield(
  sessionId: string,
  runs: readonly AgentSubagentRunV1[],
): SessionStarfieldModel {
  const ordered = [...runs].sort((left, right) => (
    left.createdAtMs - right.createdAtMs || left.id.localeCompare(right.id)
  ));
  const ringCount = Math.max(1, Math.min(ordered.length, SESSION_RING_CAP));
  const ringStep = ringCount > 1 ? (SESSION_RING_MAX - SESSION_RING_MIN) / (ringCount - 1) : 0;
  const moons = ordered.map((run, index) => {
    const ring = index % ringCount;
    const radius = ringCount > 1
      ? Math.round(SESSION_RING_MIN + ring * ringStep)
      : Math.round((SESSION_RING_MIN + SESSION_RING_MAX) / 2);
    const angleDeg = Math.round(((index * GOLDEN_ANGLE) + starfieldUnit(run.id) * 44) * 10) / 10 % 360;
    const periodS = Math.round(46 + starfieldUnit(`${run.id}:period`) * 44);
    const attention = isContractInvalid(run)
      || run.state === 'failed'
      || run.state === 'timed_out';
    return {
      runId: run.id,
      parentRunId: run.parentRunId,
      templateId: run.templateId,
      templateLabel: subagentTemplateLabel(run.templateId),
      task: run.task,
      state: subagentPresentationState(run),
      stateLabel: subagentStateLabel(run),
      active: run.state === 'queued' || run.state === 'running',
      attention,
      contextMode: run.launchDigest.contextMode,
      orbit: { ring, radius, angleDeg, periodS },
    } satisfies SessionStarfieldMoon;
  });
  return {
    sessionId,
    moons,
    ringRadii: [...new Set(moons.map((moon) => moon.orbit.radius))].sort((left, right) => left - right),
    counts: {
      active: moons.filter((moon) => moon.active).length,
      returned: moons.filter((moon) => !moon.active).length,
      attention: moons.filter((moon) => moon.attention).length,
    },
  };
}

/* ------------------------------------------------------------------ */
/* Room: the whole solar system                                        */
/* ------------------------------------------------------------------ */

export interface RoomStarfieldPlanet {
  /** Real Room participant id — the click identity. */
  participantId: string;
  sessionId: string;
  celestialName: string;
  displayName: string;
  collaborationRole?: RoomFocusPartner['collaborationRole'];
  state: RoomFocusState;
  stateLabel: string;
  /** running | waiting | review — live collaboration motion. */
  active: boolean;
  /** blocked | failed — needs the user. */
  attention: boolean;
  orbitIndex: number;
  radius: number;
  angleDeg: number;
  x: number;
  y: number;
  ownedWorkCount: number;
  currentAction: string;
}

export interface RoomStarfieldBeam {
  id: string;
  sourceParticipantId: string;
  targetParticipantId: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  state: RoomFocusProjection['handoffs'][number]['state'];
  /** offered | dispatched — a handoff actually in flight right now. */
  live: boolean;
  label: string;
}

export interface RoomStarfieldModel {
  goal: { title: string; state: RoomFocusState; stateLabel: string };
  /** Sol centre only when a connected coordinator hosts the Room. */
  hasCoordinator: boolean;
  planets: RoomStarfieldPlanet[];
  beams: RoomStarfieldBeam[];
  counts: RoomFocusProjection['counts'];
}

const ROOM_RING_MIN = 200;
const ROOM_RING_MAX = 436;
const ROOM_BEAM_LIMIT = 8;

export function buildRoomStarfield(focus: RoomFocusProjection): RoomStarfieldModel {
  const count = focus.partners.length;
  const ringStep = count > 1 ? (ROOM_RING_MAX - ROOM_RING_MIN) / (count - 1) : 0;
  const planets = focus.partners.map((partner, index) => {
    const radius = count > 1
      ? Math.round(ROOM_RING_MIN + index * ringStep)
      : Math.round((ROOM_RING_MIN + ROOM_RING_MAX) / 2);
    const spread = count > 0 ? 360 / count : 360;
    const jitter = (starfieldUnit(partner.participantId) - 0.5) * Math.min(28, spread / 3);
    const angleDeg = Math.round((-90 + index * spread + jitter) * 10) / 10;
    const angleRad = (angleDeg * Math.PI) / 180;
    return {
      participantId: partner.participantId,
      sessionId: partner.sessionId,
      celestialName: partner.celestialName,
      displayName: partner.displayName,
      collaborationRole: partner.collaborationRole,
      state: partner.state,
      stateLabel: roomFocusStateLabel(partner.state),
      active: partner.state === 'running' || partner.state === 'waiting' || partner.state === 'review',
      attention: partner.state === 'blocked' || partner.state === 'failed',
      orbitIndex: index,
      radius,
      angleDeg,
      x: Math.round(CENTER + radius * Math.cos(angleRad)),
      y: Math.round(CENTER + radius * Math.sin(angleRad)),
      ownedWorkCount: partner.ownedWorkItemIds.length,
      currentAction: partner.currentAction,
    } satisfies RoomStarfieldPlanet;
  });
  const planetById = new Map(planets.map((planet) => [planet.participantId, planet]));
  const beams = focus.handoffs
    .slice(-ROOM_BEAM_LIMIT)
    .map((handoff) => {
      const source = planetById.get(handoff.sourceParticipantId);
      const target = planetById.get(handoff.targetParticipantId);
      if (!target) return undefined;
      return {
        id: handoff.id,
        sourceParticipantId: handoff.sourceParticipantId,
        targetParticipantId: handoff.targetParticipantId,
        x1: source?.x ?? CENTER,
        y1: source?.y ?? CENTER,
        x2: target.x,
        y2: target.y,
        state: handoff.state,
        live: handoff.state === 'offered' || handoff.state === 'dispatched',
        label: handoff.task || handoff.artifactOrContract || '工作项交接',
      } satisfies RoomStarfieldBeam;
    })
    .filter((beam): beam is RoomStarfieldBeam => Boolean(beam));
  return {
    goal: {
      title: focus.goal.title,
      state: focus.goal.state,
      stateLabel: roomFocusStateLabel(focus.goal.state),
    },
    hasCoordinator: roomFocusHasCoordinator(focus.partners),
    planets,
    beams,
    counts: focus.counts,
  };
}

/* ------------------------------------------------------------------ */
/* Many Rooms: a small galaxy                                          */
/* ------------------------------------------------------------------ */

export interface GalaxyStarSystem {
  /** Real Room id — the click identity. */
  roomId: string;
  title: string;
  /** Truthful lifecycle from the Room record, not an invented pulse. */
  active: boolean;
  participantCount: number;
  x: number;
  y: number;
  /** 0.8 – 1.3, from the real participant count. */
  scale: number;
  /** Stable palette slot for this Room's star, 0..3. */
  hueIndex: number;
  updatedAtMs: number;
}

export interface GalaxyStarfieldModel {
  systems: GalaxyStarSystem[];
  totalRooms: number;
}

const GALAXY_SYSTEM_CAP = 24;
const GALAXY_RADIUS_MIN = 168;
const GALAXY_RADIUS_MAX = 424;

export function buildGalaxyStarfield(rooms: readonly RoomSummary[]): GalaxyStarfieldModel {
  const ordered = [...rooms]
    .sort((left, right) => right.updatedAtMs - left.updatedAtMs || left.id.localeCompare(right.id))
    .slice(0, GALAXY_SYSTEM_CAP);
  const denominator = Math.max(3, ordered.length - 1);
  const systems = ordered.map((room, index) => {
    const radius = index === 0
      ? 0
      : Math.min(
        GALAXY_RADIUS_MAX,
        GALAXY_RADIUS_MIN + (GALAXY_RADIUS_MAX - GALAXY_RADIUS_MIN) * Math.sqrt(index / denominator),
      );
    const angleDeg = index * GOLDEN_ANGLE + starfieldUnit(room.id) * 22;
    const angleRad = (angleDeg * Math.PI) / 180;
    const participantCount = room.participants?.length ?? 0;
    return {
      roomId: room.id,
      title: room.title,
      active: room.status === 'active',
      participantCount,
      x: Math.round(CENTER + radius * Math.cos(angleRad)),
      y: Math.round(CENTER + radius * Math.sin(angleRad)),
      scale: Math.round((0.8 + Math.min(participantCount, 6) / 12) * 100) / 100,
      hueIndex: starfieldHash(room.id) % 4,
      updatedAtMs: room.updatedAtMs,
    } satisfies GalaxyStarSystem;
  });
  return { systems, totalRooms: rooms.length };
}
