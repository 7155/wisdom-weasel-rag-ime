/**
 * Kepler orbit helpers for 星空 — visual seasoning borrowed from
 * q-jade/solar-system elliptical paths, without claiming ephemeris truth.
 *
 * The Runtime still owns who is working; eccentricity and axial tilt are
 * deterministic decorations keyed by body identity so polls never jitter.
 */

const TWO_PI = Math.PI * 2;

/** Polar radius at true anomaly ν for an ellipse with focus at the origin. */
export function ellipticRadius(semiMajor: number, eccentricity: number, trueAnomalyRad: number): number {
  const e = Math.min(0.72, Math.max(0, eccentricity));
  const a = Math.max(0.01, semiMajor);
  return (a * (1 - e * e)) / (1 + e * Math.cos(trueAnomalyRad));
}

/** Focus-centered cartesian position in the orbital XZ plane (Y up). */
export function ellipticPosition(
  semiMajor: number,
  eccentricity: number,
  trueAnomalyRad: number,
  out: { x: number; y: number; z: number },
): { x: number; y: number; z: number } {
  const r = ellipticRadius(semiMajor, eccentricity, trueAnomalyRad);
  out.x = Math.cos(trueAnomalyRad) * r;
  out.y = 0;
  out.z = Math.sin(trueAnomalyRad) * r;
  return out;
}

/** Closed elliptical path samples for LineLoop geometry. */
export function ellipticOrbitSamples(
  semiMajor: number,
  eccentricity: number,
  segments = 128,
): Float32Array {
  const positions = new Float32Array(segments * 3);
  const scratch = { x: 0, y: 0, z: 0 };
  for (let index = 0; index < segments; index += 1) {
    const angle = (index / segments) * TWO_PI;
    ellipticPosition(semiMajor, eccentricity, angle, scratch);
    positions[index * 3] = scratch.x;
    positions[index * 3 + 1] = scratch.y;
    positions[index * 3 + 2] = scratch.z;
  }
  return positions;
}

/** Arc trail behind a working body along its elliptical path. */
export function ellipticTrailSamples(
  semiMajor: number,
  eccentricity: number,
  trueAnomalyRad: number,
  spanRad: number,
  segments: number,
  target?: Float32Array,
): Float32Array {
  const positions = target && target.length >= segments * 3
    ? target
    : new Float32Array(segments * 3);
  const scratch = { x: 0, y: 0, z: 0 };
  for (let index = 0; index < segments; index += 1) {
    const t = index / Math.max(segments - 1, 1);
    const angle = trueAnomalyRad - t * spanRad;
    ellipticPosition(semiMajor, eccentricity, angle, scratch);
    positions[index * 3] = scratch.x;
    positions[index * 3 + 1] = scratch.y;
    positions[index * 3 + 2] = scratch.z;
  }
  return positions;
}
