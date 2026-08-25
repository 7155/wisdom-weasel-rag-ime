/**
 * 星空 surface synthesis — deterministic, renderer-free planet/sun textures.
 *
 * Every celestial body gets an equirectangular color map plus a single
 * channel elevation (bump) map, synthesized from seeded 3D value noise
 * sampled **on the unit sphere**, so the maps wrap seamlessly at the
 * longitude seam and never pinch at the poles. Pure TypeScript over
 * `Uint8Array`s: no canvas, no WebGL — fully unit-testable in Node, and the
 * WebGL stage uploads the results as `THREE.DataTexture`s.
 *
 * Archetypes are visual vocabulary only; body identity (which run, which
 * partner, which Room) always comes from the scene model, never from here.
 */

export type SurfaceArchetype = 'sun' | 'gas' | 'rocky' | 'ice' | 'cratered';

export interface SurfaceMaps {
  width: number;
  height: number;
  /** RGBA8 color, length = width × height × 4. */
  color: Uint8Array;
  /** Single-channel R8 elevation for bump mapping, length = width × height. */
  bump: Uint8Array;
}

export interface SurfaceOptions {
  archetype: SurfaceArchetype;
  /** Stable identity seed — same seed always yields byte-identical maps. */
  seed: string;
  /** Map width in texels; height is always width / 2 (equirectangular). */
  width: number;
  /**
   * Base hue 0..1 for tinted archetypes (gas / rocky / ice). For `sun` this
   * is the temperature 0..1: 0 ≈ red dwarf, 0.5 ≈ Sol, 1 ≈ blue-white.
   */
  hue?: number;
}

/* ------------------------------------------------------------------ */
/* Seeded noise                                                        */
/* ------------------------------------------------------------------ */

/** FNV-1a — collapses a string seed into a 32-bit noise domain offset. */
function seedState(seed: string): number {
  let state = 0x811c9dc5;
  for (let index = 0; index < seed.length; index += 1) {
    state ^= seed.charCodeAt(index);
    state = Math.imul(state, 0x01000193);
  }
  return state >>> 0;
}

/** Integer lattice hash → [0, 1). One multiply-xor avalanche per axis. */
function latticeHash(base: number, x: number, y: number, z: number): number {
  let h = base ^ Math.imul(x, 0x27d4eb2f) ^ Math.imul(y, 0x165667b1) ^ Math.imul(z, 0x9e3779b9);
  h = Math.imul(h ^ (h >>> 15), 0x85ebca6b);
  h = Math.imul(h ^ (h >>> 13), 0xc2b2ae35);
  return ((h ^ (h >>> 16)) >>> 0) / 0x100000000;
}

function smooth(t: number): number {
  return t * t * (3 - 2 * t);
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/** Trilinear 3D value noise → [0, 1). */
function valueNoise3(base: number, x: number, y: number, z: number): number {
  const xi = Math.floor(x);
  const yi = Math.floor(y);
  const zi = Math.floor(z);
  const tx = smooth(x - xi);
  const ty = smooth(y - yi);
  const tz = smooth(z - zi);
  const c000 = latticeHash(base, xi, yi, zi);
  const c100 = latticeHash(base, xi + 1, yi, zi);
  const c010 = latticeHash(base, xi, yi + 1, zi);
  const c110 = latticeHash(base, xi + 1, yi + 1, zi);
  const c001 = latticeHash(base, xi, yi, zi + 1);
  const c101 = latticeHash(base, xi + 1, yi, zi + 1);
  const c011 = latticeHash(base, xi, yi + 1, zi + 1);
  const c111 = latticeHash(base, xi + 1, yi + 1, zi + 1);
  return lerp(
    lerp(lerp(c000, c100, tx), lerp(c010, c110, tx), ty),
    lerp(lerp(c001, c101, tx), lerp(c011, c111, tx), ty),
    tz,
  );
}

/** Fractional Brownian motion, 4 octaves → [0, 1]. */
function fbm3(base: number, x: number, y: number, z: number, octaves = 4): number {
  let sum = 0;
  let amplitude = 0.5;
  let total = 0;
  let frequency = 1;
  for (let octave = 0; octave < octaves; octave += 1) {
    sum += valueNoise3(base + octave * 101, x * frequency, y * frequency, z * frequency) * amplitude;
    total += amplitude;
    amplitude *= 0.5;
    frequency *= 2;
  }
  return sum / total;
}

/** Ridged fBM → [0, 1], with sharp bright creases (mountains, granulation). */
function ridged3(base: number, x: number, y: number, z: number, octaves = 4): number {
  const value = fbm3(base, x, y, z, octaves);
  return 1 - Math.abs(value * 2 - 1);
}

/* ------------------------------------------------------------------ */
/* Color helpers                                                       */
/* ------------------------------------------------------------------ */

type Rgb = readonly [number, number, number];

function hslToRgb(h: number, s: number, l: number): Rgb {
  const hue = ((h % 1) + 1) % 1;
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((hue * 6) % 2) - 1));
  const m = l - c / 2;
  const sector = Math.floor(hue * 6) % 6;
  const table: Rgb[] = [
    [c, x, 0],
    [x, c, 0],
    [0, c, x],
    [0, x, c],
    [x, 0, c],
    [c, 0, x],
  ];
  const [r, g, b] = table[sector]!;
  return [r + m, g + m, b + m];
}

/** Piecewise-linear ramp over [position, color] stops sorted by position. */
function rampAt(stops: ReadonlyArray<readonly [number, Rgb]>, t: number): Rgb {
  const clamped = Math.min(Math.max(t, 0), 1);
  for (let index = 1; index < stops.length; index += 1) {
    const [position, color] = stops[index]!;
    if (clamped <= position) {
      const [prevPosition, prevColor] = stops[index - 1]!;
      const span = position - prevPosition || 1;
      const local = (clamped - prevPosition) / span;
      return [
        lerp(prevColor[0], color[0], local),
        lerp(prevColor[1], color[1], local),
        lerp(prevColor[2], color[2], local),
      ];
    }
  }
  return stops[stops.length - 1]![1];
}

/* ------------------------------------------------------------------ */
/* Archetype shading                                                   */
/* ------------------------------------------------------------------ */

interface Texel {
  rgb: Rgb;
  /** Elevation 0..1 for the bump channel. */
  elevation: number;
}

/**
 * Sun photosphere: ridged granulation over a blackbody-ish ramp. `heat`
 * moves the ramp from red dwarf (0) through Sol (0.5) to blue-white (1).
 */
function shadeSun(base: number, x: number, y: number, z: number, heat: number): Texel {
  const granule = ridged3(base, x * 6, y * 6, z * 6, 4);
  const cell = fbm3(base + 977, x * 2.4, y * 2.4, z * 2.4, 3);
  const energy = Math.min(Math.max(granule * 0.72 + cell * 0.28, 0), 1);
  const coolHue = lerp(0.02, 0.16, heat);
  const hotHue = lerp(0.06, 0.55, heat);
  const stops: ReadonlyArray<readonly [number, Rgb]> = [
    [0, hslToRgb(coolHue, 0.92, lerp(0.3, 0.42, heat))],
    [0.55, hslToRgb(lerp(coolHue, hotHue, 0.5), 0.88, lerp(0.5, 0.62, heat))],
    [0.85, hslToRgb(hotHue, 0.72, lerp(0.68, 0.82, heat))],
    [1, [1, lerp(0.93, 0.98, heat), lerp(0.78, 0.96, heat)]],
  ];
  return { rgb: rampAt(stops, energy), elevation: energy };
}

/** Gas giant: latitude bands, domain-warped by fBM into flowing streams. */
function shadeGas(base: number, x: number, y: number, z: number, hue: number): Texel {
  const warp = (fbm3(base + 431, x * 2.1, y * 2.1, z * 2.1, 4) - 0.5) * 0.9;
  const flow = y + warp;
  const band = Math.sin(flow * 9.5) * 0.5 + Math.sin(flow * 23 + 1.7) * 0.28 + Math.sin(flow * 4.2 - 0.6) * 0.36;
  const storms = ridged3(base + 733, x * 3.4, y * 3.4, z * 3.4, 3);
  const tone = Math.min(Math.max(band * 0.35 + 0.5 + (storms - 0.5) * 0.22, 0), 1);
  const stops: ReadonlyArray<readonly [number, Rgb]> = [
    [0, hslToRgb(hue - 0.03, 0.34, 0.24)],
    [0.42, hslToRgb(hue, 0.4, 0.44)],
    [0.72, hslToRgb(hue + 0.04, 0.44, 0.6)],
    [1, hslToRgb(hue + 0.07, 0.38, 0.76)],
  ];
  return { rgb: rampAt(stops, tone), elevation: tone * 0.5 + 0.25 };
}

/** Rocky world: fBM elevation with ridged highlands and dark lowlands. */
function shadeRocky(base: number, x: number, y: number, z: number, hue: number): Texel {
  const elevation = fbm3(base, x * 3.1, y * 3.1, z * 3.1, 5);
  const ridges = ridged3(base + 557, x * 5.7, y * 5.7, z * 5.7, 3);
  const height = Math.min(Math.max(elevation * 0.7 + ridges * 0.3, 0), 1);
  const stops: ReadonlyArray<readonly [number, Rgb]> = [
    [0, hslToRgb(hue + 0.02, 0.36, 0.16)],
    [0.4, hslToRgb(hue, 0.32, 0.34)],
    [0.7, hslToRgb(hue - 0.02, 0.26, 0.5)],
    [1, hslToRgb(hue - 0.04, 0.18, 0.72)],
  ];
  return { rgb: rampAt(stops, height), elevation: height };
}

/** Ice world: bright low-contrast sheet crossed by darker fracture lines. */
function shadeIce(base: number, x: number, y: number, z: number, hue: number): Texel {
  const sheet = fbm3(base, x * 2.6, y * 2.6, z * 2.6, 4);
  const crack = ridged3(base + 389, x * 4.8, y * 4.8, z * 4.8, 3);
  const fracture = crack > 0.82 ? (crack - 0.82) / 0.18 : 0;
  const brightness = Math.min(Math.max(0.78 + (sheet - 0.5) * 0.24 - fracture * 0.34, 0), 1);
  const rgb = hslToRgb(hue, 0.22 + fracture * 0.2, lerp(0.55, 0.92, brightness));
  return { rgb, elevation: brightness };
}

interface Crater {
  x: number;
  y: number;
  z: number;
  radius: number;
}

/** Deterministic crater field on the unit sphere. */
function craterField(base: number, count: number): Crater[] {
  const craters: Crater[] = [];
  for (let index = 0; index < count; index += 1) {
    const u = latticeHash(base, index, 11, 3);
    const v = latticeHash(base, index, 29, 7);
    const theta = u * Math.PI * 2;
    const phi = Math.acos(2 * v - 1);
    craters.push({
      x: Math.sin(phi) * Math.cos(theta),
      y: Math.cos(phi),
      z: Math.sin(phi) * Math.sin(theta),
      radius: 0.1 + latticeHash(base, index, 53, 17) * 0.24,
    });
  }
  return craters;
}

/** Cratered regolith: gray fBM plus bowl-and-rim profiles per crater. */
function shadeCratered(
  base: number,
  x: number,
  y: number,
  z: number,
  hue: number,
  craters: readonly Crater[],
): Texel {
  const regolith = fbm3(base, x * 3.6, y * 3.6, z * 3.6, 4);
  let height = regolith * 0.4 + 0.4;
  for (const crater of craters) {
    // Chord distance on the unit sphere — cheap and monotonic with arc.
    const dx = x - crater.x;
    const dy = y - crater.y;
    const dz = z - crater.z;
    const distance = Math.sqrt(dx * dx + dy * dy + dz * dz);
    if (distance >= crater.radius) continue;
    const t = distance / crater.radius;
    // Bowl below the plain, sharp rim just inside the edge.
    const bowl = -(1 - t * t) * 0.26;
    const rim = t > 0.72 ? (t - 0.72) / 0.28 * 0.2 : 0;
    height += bowl + rim;
  }
  const tone = Math.min(Math.max(height, 0), 1);
  const rgb = hslToRgb(hue, 0.1, lerp(0.2, 0.62, tone));
  return { rgb, elevation: tone };
}

/* ------------------------------------------------------------------ */
/* Synthesis                                                           */
/* ------------------------------------------------------------------ */

/**
 * Synthesize one equirectangular surface. Deterministic: byte-identical
 * output for identical options.
 */
export function synthesizeSurface(options: SurfaceOptions): SurfaceMaps {
  const width = Math.max(4, Math.floor(options.width));
  const height = Math.max(2, Math.floor(width / 2));
  const base = seedState(`${options.archetype}:${options.seed}`);
  const hue = ((options.hue ?? 0.58) % 1 + 1) % 1;
  const color = new Uint8Array(width * height * 4);
  const bump = new Uint8Array(width * height);
  const craters = options.archetype === 'cratered' ? craterField(base + 191, 14) : [];

  for (let row = 0; row < height; row += 1) {
    const lat = Math.PI * ((row + 0.5) / height) - Math.PI / 2;
    const cosLat = Math.cos(lat);
    const sinLat = Math.sin(lat);
    for (let col = 0; col < width; col += 1) {
      const lon = Math.PI * 2 * ((col + 0.5) / width);
      const x = cosLat * Math.cos(lon);
      const y = sinLat;
      const z = cosLat * Math.sin(lon);
      let texel: Texel;
      switch (options.archetype) {
        case 'sun':
          texel = shadeSun(base, x, y, z, hue);
          break;
        case 'gas':
          texel = shadeGas(base, x, y, z, hue);
          break;
        case 'rocky':
          texel = shadeRocky(base, x, y, z, hue);
          break;
        case 'ice':
          texel = shadeIce(base, x, y, z, hue);
          break;
        case 'cratered':
        default:
          texel = shadeCratered(base, x, y, z, hue, craters);
          break;
      }
      const offset = (row * width + col) * 4;
      color[offset] = Math.round(Math.min(Math.max(texel.rgb[0], 0), 1) * 255);
      color[offset + 1] = Math.round(Math.min(Math.max(texel.rgb[1], 0), 1) * 255);
      color[offset + 2] = Math.round(Math.min(Math.max(texel.rgb[2], 0), 1) * 255);
      color[offset + 3] = 255;
      bump[row * width + col] = Math.round(Math.min(Math.max(texel.elevation, 0), 1) * 255);
    }
  }
  return { width, height, color, bump };
}
