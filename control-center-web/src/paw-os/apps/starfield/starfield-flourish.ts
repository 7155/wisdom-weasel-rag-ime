/**
 * 星空 flourish — pure parameters for the decorative deep-sky presence
 * layer: meteor streaks, star-shell twinkle and nebula breathing.
 *
 * Decoration only. Nothing here reads Runtime state and nothing here may
 * claim work motion: the honest orbit/spin language stays owned by
 * `starfield-motion`. Everything is deterministic given the caller's seeded
 * random stream, and renderer-free so the maths stays unit-testable in Node.
 */

export const METEOR_POOL_SIZE = 3;

/** Trail sample count for one meteor streak (head → tail). */
export const METEOR_TRAIL_POINTS = 12;

/** Seconds of travel the visible trail stretches behind the head. */
export const METEOR_TRAIL_SPAN_S = 0.22;

export interface MeteorSpawn {
  /** Spawn point on the deep-sky shell, world units. */
  origin: readonly [number, number, number];
  /** Constant world-units-per-second travel, biased sideways and down. */
  velocity: readonly [number, number, number];
  /** Seconds the streak stays lit. */
  lifeS: number;
  /** Quiet seconds before this streak ignites. */
  delayS: number;
  /** Relative head glow size. */
  headScale: number;
}

/**
 * One meteor pass across the upper sky. `shellRadius` is the distance band
 * the streak lives on — behind every orbit, in front of the sky dome.
 */
export function meteorSpawn(random: () => number, shellRadius: number): MeteorSpawn {
  const azimuth = random() * Math.PI * 2;
  const radius = shellRadius * (0.72 + random() * 0.36);
  const origin: readonly [number, number, number] = [
    Math.cos(azimuth) * radius,
    shellRadius * (0.3 + random() * 0.5),
    Math.sin(azimuth) * radius,
  ];
  // Tangential travel with a downward dip: reads as a real shooting star
  // instead of an object falling straight through the system.
  const travel = azimuth + Math.PI / 2 + (random() - 0.5) * 0.9;
  const dip = 0.28 + random() * 0.42;
  const direction: [number, number, number] = [Math.cos(travel), -dip, Math.sin(travel)];
  const length = Math.hypot(direction[0], direction[1], direction[2]);
  const speed = shellRadius * (0.55 + random() * 0.5);
  return {
    origin,
    velocity: [
      (direction[0] / length) * speed,
      (direction[1] / length) * speed,
      (direction[2] / length) * speed,
    ],
    lifeS: 0.9 + random() * 0.9,
    delayS: 2.5 + random() * 6.5,
    headScale: 0.85 + random() * 0.75,
  };
}

/** Streak brightness over its life: fast ignite, long graceful fade. */
export function meteorFade(ageS: number, lifeS: number): number {
  if (lifeS <= 0 || ageS <= 0 || ageS >= lifeS) return 0;
  const t = ageS / lifeS;
  return t < 0.18 ? t / 0.18 : 1 - (t - 0.18) / 0.82;
}

/**
 * Star-shell shimmer: a gentle presence wave that never drops a shell below
 * ~72% of its base opacity, so the sky sparkles without strobing.
 */
export function twinkleOpacity(baseOpacity: number, elapsedS: number, phase: number): number {
  return baseOpacity * (0.86 + 0.14 * Math.sin(elapsedS + phase));
}

/** Nebula breathing scale factor: ±4% over a slow cycle. */
export function nebulaBreath(elapsedS: number, phase: number): number {
  return 1 + 0.04 * Math.sin(elapsedS * 0.16 + phase);
}
