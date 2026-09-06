/** Dimensionless, time-compressed test particles in a smooth galactic field.
 * Plummer bulge + cored logarithmic halo; this is not Solar ephemeris data.
 * Potential conventions: https://docs.galpy.org/en/stable/reference/potential.html
 */
export type OrbitState = { x: number; y: number; z: number; vx: number; vy: number; vz: number };
export type OrbitElements = { orbitRadius: number; phaseRad: number; inclinationRad: number; eccentricity: number };
export const galaxyGravity = { bulgeMass: 2.4, bulgeRadius: 2.5, haloSpeed: .55, haloRadius: 3 };
const { bulgeMass, bulgeRadius, haloSpeed, haloRadius } = galaxyGravity;

export function galaxyPotential(radius: number) {
  return -bulgeMass / Math.sqrt(radius * radius + bulgeRadius * bulgeRadius)
    + .5 * haloSpeed * haloSpeed * Math.log(radius * radius + haloRadius * haloRadius);
}

function gravity(radiusSquared: number) {
  return bulgeMass / Math.pow(radiusSquared + bulgeRadius * bulgeRadius, 1.5)
    + haloSpeed * haloSpeed / (radiusSquared + haloRadius * haloRadius);
}

export function galaxyAngularSpeed(radius: number) { return Math.sqrt(gravity(radius * radius)); }

export function createOrbit(body: OrbitElements): OrbitState {
  const radius = body.orbitRadius;
  const cos = Math.cos(body.phaseRad), sin = Math.sin(body.phaseRad);
  const inclination = body.inclinationRad;
  const speed = radius * galaxyAngularSpeed(radius) * Math.sqrt(1 - body.eccentricity);
  return { x: cos * radius, y: sin * radius * Math.sin(inclination), z: sin * radius * Math.cos(inclination),
    vx: -sin * speed, vy: cos * speed * Math.sin(inclination), vz: cos * speed * Math.cos(inclination) };
}

/** Mutates one state, allocating nothing in the render loop. */
export function advanceOrbit(state: OrbitState, seconds: number) {
  if (!Number.isFinite(seconds) || seconds <= 0) return;
  const elapsed = Math.min(seconds, .5);
  const steps = Math.ceil(elapsed / .02), dt = elapsed / steps;
  for (let i = 0; i < steps; i++) {
    let acceleration = gravity(state.x * state.x + state.y * state.y + state.z * state.z);
    state.vx -= state.x * acceleration * dt * .5;
    state.vy -= state.y * acceleration * dt * .5;
    state.vz -= state.z * acceleration * dt * .5;
    state.x += state.vx * dt; state.y += state.vy * dt; state.z += state.vz * dt;
    acceleration = gravity(state.x * state.x + state.y * state.y + state.z * state.z);
    state.vx -= state.x * acceleration * dt * .5;
    state.vy -= state.y * acceleration * dt * .5;
    state.vz -= state.z * acceleration * dt * .5;
  }
}

export function orbitPath(body: OrbitElements, target: Float32Array = new Float32Array(193 * 3)) {
  const state = createOrbit(body);
  const dt = Math.PI * 2 / galaxyAngularSpeed(body.orbitRadius) / 192;
  for (let i = 0; i <= 192; i++) {
    target[i * 3] = state.x; target[i * 3 + 1] = state.y; target[i * 3 + 2] = state.z;
    advanceOrbit(state, dt);
  }
  return target;
}

export function orbitEnergy(state: OrbitState) {
  return .5 * (state.vx ** 2 + state.vy ** 2 + state.vz ** 2) + galaxyPotential(Math.hypot(state.x, state.y, state.z));
}
