/**
 * 星空 v2 motion semantics — the single honest mapping from real Runtime
 * state to celestial motion.
 *
 * The contract with the user is simple and must never be violated:
 * - a body orbits and spins fast **only while it is genuinely working**
 *   (subagent run `running`, Room partner `running`, Session busy);
 * - settled bodies (completed / idle) may drift almost imperceptibly or
 *   stand still — never fake-spin;
 * - queued, review/approval and failure are told through light and rings
 *   (dashed queue ring, amber review ring, red alert ring), not motion;
 * - reduced motion stills everything while rings and tones keep the story.
 *
 * Both the 3D stage and the 2D fallback read this module, so the two
 * renderers can never disagree about what movement means.
 */

import type { SubagentPresentationState } from '@/features/agent/status/subagent-presentation';
import type { RoomFocusState } from '../room-focus-projection';

/** Honest status ring drawn around a body (light, not motion). */
export type StarfieldRing = 'none' | 'queued' | 'review' | 'attention';

/** Stable light tone of a body; renderers map tones to colors. */
export type StarfieldTone =
  | 'working'
  | 'queued'
  | 'waiting'
  | 'review'
  | 'done'
  | 'attention'
  | 'paused'
  | 'muted';

export interface StarfieldMotion {
  /** Orbital angular velocity in rad/s. > drift only while working. */
  orbitRadPerS: number;
  /** Self-rotation angular velocity in rad/s. > 0 only while working. */
  spinRadPerS: number;
  /** Glow pulse frequency in Hz. 0 = steady light. */
  pulseHz: number;
  ring: StarfieldRing;
  tone: StarfieldTone;
  /** True only for genuinely running work — the only fast-motion license. */
  working: boolean;
}

/** Full working revolution ≈ 34 s — clearly alive, never dizzying. */
export const WORKING_ORBIT_RAD_PER_S = 0.185;
/** Working self-rotation ≈ 7 s per turn. */
export const WORKING_SPIN_RAD_PER_S = 0.9;
/** Settled drift ≈ 13 min per revolution — visibly at rest. */
export const IDLE_DRIFT_RAD_PER_S = 0.008;

const STILL = 0;

function motion(partial: Partial<StarfieldMotion> & { tone: StarfieldTone }): StarfieldMotion {
  return {
    orbitRadPerS: STILL,
    spinRadPerS: STILL,
    pulseHz: 0,
    ring: 'none',
    working: false,
    ...partial,
  };
}

/** Session subagent run → motion. `attention` covers contract_invalid too. */
export function subagentMotion(
  state: SubagentPresentationState,
  attention: boolean,
): StarfieldMotion {
  if (attention || state === 'failed' || state === 'timed_out' || state === 'contract_invalid') {
    return motion({ tone: 'attention', ring: 'attention', pulseHz: 0.6 });
  }
  switch (state) {
    case 'running':
      return motion({
        tone: 'working',
        working: true,
        orbitRadPerS: WORKING_ORBIT_RAD_PER_S,
        spinRadPerS: WORKING_SPIN_RAD_PER_S,
        pulseHz: 0.4,
      });
    case 'queued':
      return motion({ tone: 'queued', ring: 'queued' });
    case 'returned':
      // Returned but unverified: settled, with an amber review ring.
      return motion({ tone: 'review', ring: 'review', orbitRadPerS: IDLE_DRIFT_RAD_PER_S });
    case 'completed':
      return motion({ tone: 'done', orbitRadPerS: IDLE_DRIFT_RAD_PER_S });
    case 'aborted':
      return motion({ tone: 'paused' });
    default:
      return motion({ tone: 'muted' });
  }
}

/** Room partner / goal state → motion. Sol reuses this for the goal. */
export function roomBodyMotion(state: RoomFocusState): StarfieldMotion {
  switch (state) {
    case 'running':
      return motion({
        tone: 'working',
        working: true,
        orbitRadPerS: WORKING_ORBIT_RAD_PER_S,
        spinRadPerS: WORKING_SPIN_RAD_PER_S,
        pulseHz: 0.35,
      });
    case 'waiting':
      return motion({ tone: 'waiting', ring: 'queued' });
    case 'review':
      return motion({ tone: 'review', ring: 'review' });
    case 'blocked':
    case 'failed':
      return motion({ tone: 'attention', ring: 'attention', pulseHz: 0.6 });
    case 'completed':
      return motion({ tone: 'done', orbitRadPerS: IDLE_DRIFT_RAD_PER_S });
    case 'stopped':
      return motion({ tone: 'paused' });
    case 'disconnected':
      return motion({ tone: 'muted' });
    case 'idle':
    default:
      return motion({ tone: 'muted', orbitRadPerS: IDLE_DRIFT_RAD_PER_S });
  }
}

/**
 * Session core planet: the Session itself. Busy means the main turn is
 * genuinely executing right now — only then does the planet spin fast.
 */
export function sessionCoreMotion(busy: boolean): StarfieldMotion {
  return busy
    ? motion({
        tone: 'working',
        working: true,
        spinRadPerS: WORKING_SPIN_RAD_PER_S * 0.55,
        pulseHz: 0.45,
      })
    : motion({ tone: 'muted', spinRadPerS: IDLE_DRIFT_RAD_PER_S });
}

/**
 * Galaxy star system: a Room being `active` proves it is alive, not that it
 * is working this second — so active Rooms get light and a slow drift only.
 */
export function galaxySystemMotion(active: boolean): StarfieldMotion {
  return active
    ? motion({ tone: 'working', orbitRadPerS: IDLE_DRIFT_RAD_PER_S })
    : motion({ tone: 'muted' });
}

/** Reduced motion: still every velocity and pulse; light keeps the story. */
export function stilledMotion(value: StarfieldMotion): StarfieldMotion {
  return { ...value, orbitRadPerS: 0, spinRadPerS: 0, pulseHz: 0 };
}
