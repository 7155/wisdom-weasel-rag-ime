/**
 * 星空 procedural texture synthesis — deterministic, DOM-free image data for
 * the WebGL stage.
 *
 * Every map is generated from seeded value-noise fBm into plain RGBA byte
 * arrays, so:
 * - the same Runtime identity always receives the same surface — no flicker
 *   and no fake variety between polls;
 * - generation is unit-testable in Node without a canvas or GL context;
 * - nothing is fetched at runtime — no CDN and no packed binary assets.
 *
 * Planet surfaces come in six archetypes tied to the stable palette slot of
 * a body, each producing an albedo map plus a normal map derived from the
 * same height field. The sun gets a granulation map, the sky an equirect
 * dome with nebulae, a tilted milky-way band and scattered stars, and the
 * center planet a banded ring alpha map.
 *
 * `StarfieldTextureFactory` wraps the raw data into cached THREE.DataTexture
 * instances and owns their disposal; the scene never disposes a texture the
 * factory created.
 */

import * as THREE from 'three';

const TWO_PI = Math.PI * 2;

export interface GeneratedTextureData {
  width: number;
  height: number;
  /** Tightly packed RGBA bytes, row-major, no padding. */
  data: Uint8ClampedArray;
}

export type PlanetArchetype = 'ocean' | 'rocky' | 'desert' | 'gas' | 'ice' | 'terra';

/** Palette slot → archetype: stable so a body never changes its surface. */
const ARCHETYPE_BY_PALETTE: readonly PlanetArchetype[] = [
  'ocean', 'rocky', 'desert', 'gas', 'ice', 'terra',
];

export function archetypeForPalette(paletteIndex: number): PlanetArchetype {
  const index = ((paletteIndex % ARCHETYPE_BY_PALETTE.length) + ARCHETYPE_BY_PALETTE.length)
    % ARCHETYPE_BY_PALETTE.length;
  return ARCHETYPE_BY_PALETTE[index]!;
}

export function archetypeForSeed(seed: string): PlanetArchetype {
  return ARCHETYPE_BY_PALETTE[textureSeed(seed) % ARCHETYPE_BY_PALETTE.length]!;
}

/* ------------------------------------------------------------------ */
/* Seeds and noise                                                     */
/* ------------------------------------------------------------------ */

/** FNV-1a of a string → uint32; mirrors starfieldHash determinism. */
export function textureSeed(seed: string): number {
  let state = 0x811c9dc5;
  for (let index = 0; index < seed.length; index += 1) {
    state ^= seed.charCodeAt(index);
    state = Math.imul(state, 0x01000193);
  }
  return state >>> 0;
}

function hashUint(value: number): number {
  let h = value >>> 0;
  h = Math.imul(h ^ (h >>> 16), 0x45d9f3b);
  h = Math.imul(h ^ (h >>> 16), 0x45d9f3b);
  return (h ^ (h >>> 16)) >>> 0;
}

function seedUnit(seed: number, salt: number): number {
  return hashUint(seed ^ Math.imul(salt, 0x9e3779b1)) / 4294967295;
}

function lattice(ix: number, iy: number, seed: number): number {
  return hashUint((Math.imul(ix, 374761393) ^ Math.imul(iy, 668265263) ^ seed) >>> 0) / 4294967295;
}

/**
 * Smoothstep-interpolated value noise whose integer lattice wraps in x with
 * `periodX`, so equirect surface maps are horizontally seamless.
 */
export function periodicValueNoise(x: number, y: number, periodX: number, seed: number): number {
  const xf = Math.floor(x);
  const yf = Math.floor(y);
  const fx = x - xf;
  const fy = y - yf;
  const sx = fx * fx * (3 - 2 * fx);
  const sy = fy * fy * (3 - 2 * fy);
  const x0 = ((xf % periodX) + periodX) % periodX;
  const x1 = (x0 + 1) % periodX;
  const n00 = lattice(x0, yf, seed);
  const n10 = lattice(x1, yf, seed);
  const n01 = lattice(x0, yf + 1, seed);
  const n11 = lattice(x1, yf + 1, seed);
  return n00 + (n10 - n00) * sx + (n01 - n00) * sy + (n00 - n10 - n01 + n11) * sx * sy;
}

/** Fractional Brownian motion over the periodic value noise, output 0..1. */
export function periodicFbm(
  x: number,
  y: number,
  periodX: number,
  seed: number,
  octaves = 5,
  gain = 0.5,
): number {
  let amplitude = 1;
  let frequency = 1;
  let period = periodX;
  let sum = 0;
  let norm = 0;
  for (let octave = 0; octave < octaves; octave += 1) {
    sum += periodicValueNoise(x * frequency, y * frequency, period, seed + octave * 1013) * amplitude;
    norm += amplitude;
    amplitude *= gain;
    frequency *= 2;
    period *= 2;
  }
  return sum / norm;
}

function valueNoise1(x: number, seed: number): number {
  const xf = Math.floor(x);
  const fx = x - xf;
  const sx = fx * fx * (3 - 2 * fx);
  const a = hashUint(Math.imul(xf, 374761393) ^ seed) / 4294967295;
  const b = hashUint(Math.imul(xf + 1, 374761393) ^ seed) / 4294967295;
  return a + (b - a) * sx;
}

/* ------------------------------------------------------------------ */
/* Color helpers                                                       */
/* ------------------------------------------------------------------ */

type Rgb = readonly [number, number, number];

const WHITE: Rgb = [255, 255, 255];

function clamp01(value: number): number {
  return value < 0 ? 0 : value > 1 ? 1 : value;
}

function smoothstep(edge0: number, edge1: number, value: number): number {
  const t = clamp01((value - edge0) / Math.max(edge1 - edge0, 1e-6));
  return t * t * (3 - 2 * t);
}

function rgbFromHex(hex: number): Rgb {
  return [(hex >> 16) & 255, (hex >> 8) & 255, hex & 255];
}

function mixRgb(a: Rgb, b: Rgb, t: number): Rgb {
  const k = clamp01(t);
  return [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k];
}

function shade(color: Rgb, factor: number): Rgb {
  return [
    Math.min(255, color[0] * factor),
    Math.min(255, color[1] * factor),
    Math.min(255, color[2] * factor),
  ];
}

function rampRgb(stops: ReadonlyArray<readonly [number, Rgb]>, t: number): Rgb {
  if (t <= stops[0]![0]) return stops[0]![1];
  for (let index = 1; index < stops.length; index += 1) {
    const [prevT, prevColor] = stops[index - 1]!;
    const [currT, currColor] = stops[index]!;
    if (t <= currT) return mixRgb(prevColor, currColor, (t - prevT) / Math.max(currT - prevT, 1e-6));
  }
  return stops[stops.length - 1]![1];
}

/* ------------------------------------------------------------------ */
/* Spectral star population                                            */
/* ------------------------------------------------------------------ */

export interface SpectralStarType {
  /** Upper bound of this type's slice of a 0..1 pick. */
  cumulative: number;
  /** Linear RGB 0..1. */
  rgb: readonly [number, number, number];
}

/**
 * Approximate real spectral-type distribution (ported from the q-jade
 * solar-system reference): a few hot blue O/B stars, some white A/F, and a
 * warm majority of G/K/M — so the deep sky reads warm-and-cool natural
 * instead of a uniform blue haze. The dome stars baked into the sky map and
 * the parallax star shells in front of it share this one table, so the two
 * layers cannot drift into different populations.
 */
const SPECTRAL_STAR_TYPES: readonly SpectralStarType[] = [
  { cumulative: 0.04, rgb: [0.72, 0.84, 1] },
  { cumulative: 0.12, rgb: [0.9, 0.94, 1] },
  { cumulative: 0.24, rgb: [1, 0.96, 0.82] },
  { cumulative: 0.64, rgb: [1, 0.82, 0.62] },
  { cumulative: 1, rgb: [1, 0.7, 0.52] },
];

/** Deterministic spectral type for a 0..1 pick. */
export function spectralStarType(unit: number): SpectralStarType {
  const pick = clamp01(unit);
  for (const type of SPECTRAL_STAR_TYPES) {
    if (pick <= type.cumulative) return type;
  }
  return SPECTRAL_STAR_TYPES[SPECTRAL_STAR_TYPES.length - 1]!;
}

/** Deterministic spectral tint for a 0..1 pick, RGB channels in 0..1. */
export function spectralStarColor(unit: number): readonly [number, number, number] {
  return spectralStarType(unit).rgb;
}

/* ------------------------------------------------------------------ */
/* Planet surfaces                                                     */
/* ------------------------------------------------------------------ */

const NORMAL_STRENGTH: Record<PlanetArchetype, number> = {
  rocky: 2.4,
  terra: 1.9,
  desert: 1.6,
  ice: 1.3,
  ocean: 0.9,
  gas: 0.5,
};

export interface PlanetMaps {
  albedo: GeneratedTextureData;
  normal: GeneratedTextureData;
}

export interface PlanetMapOptions {
  seed: string;
  archetype: PlanetArchetype;
  /** 0xRRGGBB base hue — the body keeps its stable palette identity. */
  baseColor: number;
  width?: number;
  height?: number;
}

export function generatePlanetMaps(options: PlanetMapOptions): PlanetMaps {
  const width = options.width ?? 256;
  const heightPx = options.height ?? Math.max(4, width >> 1);
  const seed = textureSeed(`${options.seed}|${options.archetype}`);
  const base = rgbFromHex(options.baseColor);
  const field = new Float32Array(width * heightPx);
  const albedo = new Uint8ClampedArray(width * heightPx * 4);
  const bandCount = 4 + Math.floor(seedUnit(seed, 11) * 4);

  for (let py = 0; py < heightPx; py += 1) {
    const v = (py + 0.5) / heightPx;
    for (let px = 0; px < width; px += 1) {
      const u = (px + 0.5) / width;
      // 2:1 x/y frequency keeps noise cells roughly square on the equirect.
      const fbm = (frequency: number, salt: number, octaves = 5, stretchY = 1) =>
        periodicFbm(u * frequency * 2, v * frequency * stretchY, frequency * 2, seed + salt, octaves);

      let heightValue = 0.5;
      let rgb: Rgb = base;
      switch (options.archetype) {
        case 'rocky': {
          const hills = fbm(6, 101, 6);
          const ridged = 1 - Math.abs(2 * fbm(9, 202, 5) - 1);
          heightValue = clamp01(0.55 * hills + 0.45 * ridged);
          rgb = rampRgb([
            [0, shade(base, 0.26)],
            [0.42, shade(base, 0.6)],
            [0.66, shade(base, 0.94)],
            [0.84, mixRgb(base, WHITE, 0.28)],
            [1, mixRgb(base, WHITE, 0.62)],
          ], heightValue);
          const rubble = fbm(26, 303, 2);
          if (rubble > 0.68) rgb = shade(rgb, 1 - (rubble - 0.68) * 1.6);
          break;
        }
        case 'terra': {
          const continents = fbm(4, 101, 6);
          const detail = fbm(16, 202, 4);
          const polar = smoothstep(0.38, 0.47, Math.abs(v - 0.5));
          if (continents < 0.52) {
            const depth = (0.52 - continents) / 0.52;
            rgb = mixRgb([47, 86, 129], [10, 27, 54], clamp01(depth * 1.4));
            heightValue = 0.42 - depth * 0.08;
            if (polar > 0.35 && continents > 0.4) rgb = mixRgb(rgb, [222, 234, 244], polar * 0.9);
          } else {
            const land = (continents - 0.52) / 0.48;
            heightValue = 0.5 + land * 0.5;
            rgb = rampRgb([
              [0, shade(base, 0.5)],
              [0.35, shade(base, 0.85)],
              [0.7, mixRgb(base, [168, 148, 110], 0.5)],
              [1, mixRgb(base, WHITE, 0.66)],
            ], clamp01(land * (0.7 + detail * 0.6)));
            if (polar > 0.2) rgb = mixRgb(rgb, [235, 242, 248], polar);
          }
          break;
        }
        case 'ocean': {
          const current = fbm(7, 101, 5);
          const island = fbm(10, 202, 5);
          heightValue = 0.46 + current * 0.08;
          rgb = rampRgb([
            [0, shade(base, 0.3)],
            [0.5, shade(base, 0.6)],
            [0.82, shade(base, 0.88)],
            [1, mixRgb(base, WHITE, 0.3)],
          ], current);
          if (island > 0.74) {
            const t = smoothstep(0.74, 0.86, island);
            rgb = mixRgb(rgb, mixRgb(base, [214, 196, 150], 0.7), t);
            heightValue = 0.5 + t * 0.4;
          }
          break;
        }
        case 'desert': {
          const dunes = 1 - Math.abs(2 * fbm(5, 101, 4, 3.2) - 1);
          const wind = fbm(3, 202, 4);
          heightValue = clamp01(dunes * 0.8 + wind * 0.2);
          rgb = rampRgb([
            [0, shade(base, 0.42)],
            [0.55, shade(base, 0.82)],
            [1, mixRgb(base, WHITE, 0.42)],
          ], dunes);
          rgb = shade(rgb, 0.85 + wind * 0.3);
          if (wind < 0.3) rgb = mixRgb(rgb, shade(base, 0.34), (0.3 - wind) * 2.4);
          break;
        }
        case 'ice': {
          const frost = fbm(6, 101, 5);
          const crackNoise = 1 - Math.abs(2 * fbm(11, 202, 4) - 1);
          const crack = smoothstep(0.84, 0.96, crackNoise);
          const pale = mixRgb(base, WHITE, 0.58);
          rgb = rampRgb([
            [0, shade(base, 0.72)],
            [0.55, pale],
            [1, mixRgb(pale, WHITE, 0.7)],
          ], frost);
          rgb = mixRgb(rgb, shade(base, 0.36), crack);
          heightValue = clamp01(frost * 0.75 + (1 - crack) * 0.25);
          break;
        }
        case 'gas': {
          const warp = fbm(5, 101, 4);
          const band = 0.5 + 0.5 * Math.sin(v * bandCount * TWO_PI + (warp - 0.5) * 3.4);
          const flow = fbm(6, 202, 4, 6);
          const storm = fbm(9, 303, 5);
          rgb = mixRgb(shade(base, 0.55), mixRgb(base, WHITE, 0.42), band);
          rgb = shade(rgb, 0.86 + flow * 0.26);
          const spot = smoothstep(0.8, 0.92, storm);
          if (spot > 0) rgb = mixRgb(rgb, mixRgb(base, WHITE, 0.7), spot);
          heightValue = clamp01(0.4 + band * 0.25 + flow * 0.15);
          break;
        }
      }

      const index = py * width + px;
      field[index] = heightValue;
      const offset = index * 4;
      albedo[offset] = rgb[0];
      albedo[offset + 1] = rgb[1];
      albedo[offset + 2] = rgb[2];
      albedo[offset + 3] = 255;
    }
  }

  return {
    albedo: { width, height: heightPx, data: albedo },
    normal: normalMapFromHeight(field, width, heightPx, NORMAL_STRENGTH[options.archetype]),
  };
}

/** Tangent-space normal map via central differences; wraps in x. */
export function normalMapFromHeight(
  field: Float32Array,
  width: number,
  height: number,
  strength: number,
): GeneratedTextureData {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let py = 0; py < height; py += 1) {
    const rowUp = Math.max(py - 1, 0) * width;
    const rowDown = Math.min(py + 1, height - 1) * width;
    const row = py * width;
    for (let px = 0; px < width; px += 1) {
      const left = field[row + ((px - 1 + width) % width)]!;
      const right = field[row + ((px + 1) % width)]!;
      const up = field[rowUp + px]!;
      const down = field[rowDown + px]!;
      const nx = (left - right) * strength;
      const ny = (down - up) * strength;
      const inv = 1 / Math.sqrt(nx * nx + ny * ny + 1);
      const offset = (row + px) * 4;
      data[offset] = (nx * inv * 0.5 + 0.5) * 255;
      data[offset + 1] = (ny * inv * 0.5 + 0.5) * 255;
      data[offset + 2] = (inv * 0.5 + 0.5) * 255;
      data[offset + 3] = 255;
    }
  }
  return { width, height, data };
}

/* ------------------------------------------------------------------ */
/* Cloud / atmosphere shell maps                                       */
/* ------------------------------------------------------------------ */

/**
 * Soft translucent cloud sheet for terra/ocean bodies — q-jade Earth
 * cloud layer seasoning, generated procedurally so nothing is fetched.
 */
export function generateCloudMap(seed: string, width = 256, height?: number): GeneratedTextureData {
  const heightPx = height ?? Math.max(4, width >> 1);
  const s = textureSeed(`cloud|${seed}`);
  const data = new Uint8ClampedArray(width * heightPx * 4);
  for (let py = 0; py < heightPx; py += 1) {
    const v = (py + 0.5) / heightPx;
    for (let px = 0; px < width; px += 1) {
      const u = (px + 0.5) / width;
      const banks = periodicFbm(u * 10, v * 5, 10, s + 17, 5);
      const wisps = periodicFbm(u * 22, v * 11, 22, s + 41, 3);
      const coverage = smoothstep(0.48, 0.78, banks * 0.72 + wisps * 0.28);
      const brightness = 210 + wisps * 45;
      const offset = (py * width + px) * 4;
      data[offset] = brightness;
      data[offset + 1] = brightness;
      data[offset + 2] = Math.min(255, brightness + 8);
      data[offset + 3] = coverage * 170;
    }
  }
  return { width, height: heightPx, data };
}

/* ------------------------------------------------------------------ */
/* Sun / star granulation                                              */
/* ------------------------------------------------------------------ */

export function generateSunMap(seed: string, width = 256, height?: number): GeneratedTextureData {
  const heightPx = height ?? Math.max(4, width >> 1);
  const s = textureSeed(`sun|${seed}`);
  const data = new Uint8ClampedArray(width * heightPx * 4);
  for (let py = 0; py < heightPx; py += 1) {
    const v = (py + 0.5) / heightPx;
    for (let px = 0; px < width; px += 1) {
      const u = (px + 0.5) / width;
      const granulation = 1 - Math.abs(2 * periodicFbm(u * 14, v * 7, 14, s + 11, 5) - 1);
      const cells = periodicFbm(u * 28, v * 14, 28, s + 47, 3);
      const t = clamp01(0.18 + 0.62 * granulation + 0.3 * (cells - 0.5));
      const rgb = rampRgb([
        [0, [121, 32, 6]],
        [0.3, [196, 78, 16]],
        [0.55, [243, 138, 42]],
        [0.8, [255, 197, 110]],
        [1, [255, 244, 215]],
      ], t);
      const offset = (py * width + px) * 4;
      data[offset] = rgb[0];
      data[offset + 1] = rgb[1];
      data[offset + 2] = rgb[2];
      data[offset + 3] = 255;
    }
  }
  return { width, height: heightPx, data };
}

/** Neutral granulation for galaxy stars — tinted by the material color. */
export function generateStarMap(seed = 'shared-star', width = 128, height?: number): GeneratedTextureData {
  const heightPx = height ?? Math.max(4, width >> 1);
  const s = textureSeed(`star|${seed}`);
  const data = new Uint8ClampedArray(width * heightPx * 4);
  for (let py = 0; py < heightPx; py += 1) {
    const v = (py + 0.5) / heightPx;
    for (let px = 0; px < width; px += 1) {
      const u = (px + 0.5) / width;
      const granulation = 1 - Math.abs(2 * periodicFbm(u * 12, v * 6, 12, s + 11, 4) - 1);
      const t = clamp01(0.25 + 0.75 * granulation);
      const rgb = rampRgb([
        [0, [46, 46, 54]],
        [0.45, [142, 148, 160]],
        [0.75, [219, 224, 235]],
        [1, WHITE],
      ], t);
      const offset = (py * width + px) * 4;
      data[offset] = rgb[0];
      data[offset + 1] = rgb[1];
      data[offset + 2] = rgb[2];
      data[offset + 3] = 255;
    }
  }
  return { width, height: heightPx, data };
}

/* ------------------------------------------------------------------ */
/* Deep-sky dome                                                       */
/* ------------------------------------------------------------------ */

/** Dome width used for the first-frame sky while the full map is queued. */
export const SKY_PREVIEW_WIDTH = 256;

export function generateSkyMap(seed: string, width = 768, height?: number): GeneratedTextureData {
  const heightPx = height ?? Math.max(4, width >> 1);
  const s = textureSeed(`sky|${seed}`);
  const data = new Uint8ClampedArray(width * heightPx * 4);

  // Tilted milky-way plane normal, stable per seed.
  const tilt = 0.5 + seedUnit(s, 3) * 0.6;
  const azimuth = seedUnit(s, 5) * TWO_PI;
  const planeX = Math.sin(tilt) * Math.cos(azimuth);
  const planeY = Math.cos(tilt);
  const planeZ = Math.sin(tilt) * Math.sin(azimuth);

  for (let py = 0; py < heightPx; py += 1) {
    const v = (py + 0.5) / heightPx;
    const phi = v * Math.PI;
    const sinPhi = Math.sin(phi);
    const dirY = Math.cos(phi);
    for (let px = 0; px < width; px += 1) {
      const u = (px + 0.5) / width;
      const theta = u * TWO_PI;
      const dirX = sinPhi * Math.cos(theta);
      const dirZ = sinPhi * Math.sin(theta);
      const d = dirX * planeX + dirY * planeY + dirZ * planeZ;
      const band = Math.exp(-(d * 4.2) * (d * 4.2));
      const bandTexture = periodicFbm(u * 16, v * 8, 16, s + 21, 4);
      const nebulaBlue = smoothstep(0.55, 0.92, periodicFbm(u * 6, v * 3, 6, s + 31, 5));
      const nebulaViolet = smoothstep(0.58, 0.94, periodicFbm(u * 8, v * 4, 8, s + 41, 5));
      const dust = periodicFbm(u * 10, v * 5, 10, s + 51, 3);

      let red = 4 + nebulaBlue * 28 + nebulaViolet * 58 + band * (42 + 38 * bandTexture);
      let green = 6 + nebulaBlue * 44 + nebulaViolet * 34 + band * (36 + 32 * bandTexture);
      let blue = 14 + nebulaBlue * 96 + nebulaViolet * 92 + band * (48 + 36 * bandTexture);
      // Dark dust lanes threading the bright band.
      const lane = 1 - band * smoothstep(0.52, 0.88, dust) * 0.58;
      red *= lane;
      green *= lane;
      blue *= lane;

      const offset = (py * width + px) * 4;
      data[offset] = red;
      data[offset + 1] = green;
      data[offset + 2] = blue;
      data[offset + 3] = 255;
    }
  }

  // Scattered stars, denser inside the band (rejection sampling by hash).
  const starCount = Math.round(width * heightPx * 0.0058);
  for (let index = 0; index < starCount; index += 1) {
    const h1 = hashUint(s ^ Math.imul(index + 1, 0x27d4eb2f));
    const h2 = hashUint(h1 + 0x9e3779b9);
    const u = (h1 & 0xffff) / 65536;
    const v = ((h1 >>> 16) & 0xffff) / 65536;
    const phi = v * Math.PI;
    const dirX = Math.sin(phi) * Math.cos(u * TWO_PI);
    const dirY = Math.cos(phi);
    const dirZ = Math.sin(phi) * Math.sin(u * TWO_PI);
    const d = dirX * planeX + dirY * planeY + dirZ * planeZ;
    const keepChance = 0.3 + 0.7 * Math.exp(-(d * 3.2) * (d * 3.2));
    if ((h2 & 0xff) / 255 > keepChance) continue;

    const px = Math.min(width - 1, Math.floor(u * width));
    const py = Math.min(heightPx - 1, Math.floor(v * heightPx));
    const brightness = 90 + ((h2 >>> 8) & 0xff) * 0.65;
    const spectral = spectralStarColor(((h2 >>> 16) & 0xff) / 255);
    const tint: Rgb = [spectral[0] * 255, spectral[1] * 255, spectral[2] * 255];
    const large = ((h2 >>> 24) & 0xff) > 249;

    const deposit = (x: number, y: number, energy: number) => {
      if (y < 0 || y >= heightPx) return;
      const wrapped = ((x % width) + width) % width;
      const offset = (y * width + wrapped) * 4;
      data[offset] = data[offset]! + (tint[0] / 255) * energy;
      data[offset + 1] = data[offset + 1]! + (tint[1] / 255) * energy;
      data[offset + 2] = data[offset + 2]! + (tint[2] / 255) * energy;
    };
    deposit(px, py, large ? brightness * 1.6 : brightness);
    const halo = brightness * (large ? 0.5 : 0.35);
    deposit(px - 1, py, halo);
    deposit(px + 1, py, halo);
    deposit(px, py - 1, halo);
    deposit(px, py + 1, halo);
    if (large) {
      const faint = brightness * 0.2;
      deposit(px - 1, py - 1, faint);
      deposit(px + 1, py - 1, faint);
      deposit(px - 1, py + 1, faint);
      deposit(px + 1, py + 1, faint);
    }
  }

  return { width, height: heightPx, data };
}

/* ------------------------------------------------------------------ */
/* Ring and glow sprites                                               */
/* ------------------------------------------------------------------ */

/** Banded ring alpha map for a planar-UV RingGeometry (r ≈ 0.66..1 used). */
export function generateRingMap(seed: string, size = 128): GeneratedTextureData {
  const s = textureSeed(`ring|${seed}`);
  const data = new Uint8ClampedArray(size * size * 4);
  for (let py = 0; py < size; py += 1) {
    const y = ((py + 0.5) / size) * 2 - 1;
    for (let px = 0; px < size; px += 1) {
      const x = ((px + 0.5) / size) * 2 - 1;
      const r = Math.sqrt(x * x + y * y);
      const offset = (py * size + px) * 4;
      if (r < 0.62 || r > 1) {
        data[offset + 3] = 0;
        continue;
      }
      const bands = valueNoise1(r * 30, s + 7) * 0.6 + valueNoise1(r * 90, s + 13) * 0.4;
      let alpha = smoothstep(0.32, 0.58, bands) * 200;
      alpha *= smoothstep(0.62, 0.68, r) * (1 - smoothstep(0.94, 1, r));
      const gap = (r - 0.85) * 34;
      alpha *= 1 - 0.85 * Math.exp(-gap * gap);
      const tone = 0.75 + bands * 0.35;
      data[offset] = 214 * tone;
      data[offset + 1] = 206 * tone;
      data[offset + 2] = 186 * tone;
      data[offset + 3] = alpha;
    }
  }
  return { width: size, height: size, data };
}

/** Soft radial glow — white RGB, shaped alpha; tint via material color. */
export function generateRadialGlow(options: {
  size?: number;
  exponent?: number;
  core?: number;
} = {}): GeneratedTextureData {
  const size = options.size ?? 64;
  const exponent = options.exponent ?? 2.2;
  const core = options.core ?? 0.4;
  const data = new Uint8ClampedArray(size * size * 4);
  const half = size / 2;
  for (let py = 0; py < size; py += 1) {
    for (let px = 0; px < size; px += 1) {
      const dx = (px + 0.5 - half) / half;
      const dy = (py + 0.5 - half) / half;
      const r = Math.sqrt(dx * dx + dy * dy);
      const falloff = Math.max(0, 1 - r);
      const kernel = Math.max(0, 1 - r / 0.3);
      const alpha = Math.min(1, falloff ** exponent + core * kernel * kernel);
      const offset = (py * size + px) * 4;
      data[offset] = 255;
      data[offset + 1] = 255;
      data[offset + 2] = 255;
      data[offset + 3] = alpha * 255;
    }
  }
  return { width: size, height: size, data };
}

/* ------------------------------------------------------------------ */
/* THREE texture factory                                               */
/* ------------------------------------------------------------------ */

export interface PlanetTexturePair {
  map: THREE.DataTexture;
  normalMap: THREE.DataTexture;
}

/** Evict beyond this many cached non-shared textures (FIFO). */
const MAX_CACHED_TEXTURES = 160;

/**
 * Owns every generated THREE.DataTexture: caches by deterministic key,
 * bounds the cache, and disposes everything exactly once. The scene checks
 * `owns()` before disposing any material map.
 */
export class StarfieldTextureFactory {
  private readonly cache = new Map<string, THREE.DataTexture>();
  private readonly owned = new Set<THREE.Texture>();
  private anisotropy = 1;

  setAnisotropy(value: number): void {
    this.anisotropy = Math.max(1, Math.floor(value));
  }

  owns(texture: THREE.Texture): boolean {
    return this.owned.has(texture);
  }

  glow(): THREE.DataTexture {
    return this.acquire('shared:glow', { srgb: true, wrapX: false }, () => generateRadialGlow());
  }

  dot(): THREE.DataTexture {
    return this.acquire('shared:dot', { srgb: true, wrapX: false }, () =>
      generateRadialGlow({ size: 32, exponent: 3.4, core: 0.85 }));
  }

  sun(seed: string): THREE.DataTexture {
    return this.acquire(`sun:${seed}`, { srgb: true, wrapX: true }, () => generateSunMap(seed));
  }

  star(): THREE.DataTexture {
    return this.acquire('shared:star', { srgb: true, wrapX: true }, () => generateStarMap());
  }

  sky(seed: string): THREE.DataTexture {
    return this.acquire(`sky:${seed}`, { srgb: true, wrapX: true }, () => generateSkyMap(seed));
  }

  /**
   * Quarter-area dome shown while the full sky is still being synthesised.
   * Nebulae and the milky-way band are smooth enough to survive the drop;
   * only star crispness waits for the upgrade.
   */
  skyPreview(seed: string): THREE.DataTexture {
    return this.acquire(`sky-preview:${seed}`, { srgb: true, wrapX: true }, () =>
      generateSkyMap(seed, SKY_PREVIEW_WIDTH));
  }

  cloud(seed: string, width = 256): THREE.DataTexture {
    return this.acquire(`cloud:${textureSeed(seed)}:${width}`, { srgb: true, wrapX: true }, () =>
      generateCloudMap(seed, width));
  }

  ring(seed: string): THREE.DataTexture {
    return this.acquire(`ring:${seed}`, { srgb: true, wrapX: false }, () => generateRingMap(seed));
  }

  planet(options: { seed: string; archetype: PlanetArchetype; baseColor: number; width: number }): PlanetTexturePair {
    const key = `planet:${options.archetype}:${options.baseColor.toString(16)}:${options.width}:${textureSeed(options.seed)}`;
    let maps: PlanetMaps | null = null;
    const generate = (): PlanetMaps => {
      maps ??= generatePlanetMaps(options);
      return maps;
    };
    return {
      map: this.acquire(`${key}:albedo`, { srgb: true, wrapX: true }, () => generate().albedo),
      normalMap: this.acquire(`${key}:normal`, { srgb: false, wrapX: true }, () => generate().normal),
    };
  }

  dispose(): void {
    for (const texture of this.cache.values()) texture.dispose();
    this.cache.clear();
    this.owned.clear();
  }

  private acquire(
    key: string,
    options: { srgb: boolean; wrapX: boolean },
    build: () => GeneratedTextureData,
  ): THREE.DataTexture {
    const cached = this.cache.get(key);
    if (cached) return cached;
    const generated = build();
    const texture = new THREE.DataTexture(
      new Uint8Array(generated.data.buffer, generated.data.byteOffset, generated.data.byteLength),
      generated.width,
      generated.height,
      THREE.RGBAFormat,
      THREE.UnsignedByteType,
    );
    texture.colorSpace = options.srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
    texture.wrapS = options.wrapX ? THREE.RepeatWrapping : THREE.ClampToEdgeWrapping;
    texture.wrapT = THREE.ClampToEdgeWrapping;
    texture.magFilter = THREE.LinearFilter;
    texture.minFilter = THREE.LinearMipmapLinearFilter;
    texture.generateMipmaps = true;
    texture.anisotropy = this.anisotropy;
    texture.needsUpdate = true;
    this.cache.set(key, texture);
    this.owned.add(texture);
    this.trim();
    return texture;
  }

  private trim(): void {
    if (this.cache.size <= MAX_CACHED_TEXTURES) return;
    for (const [key, texture] of this.cache) {
      if (key.startsWith('shared:')) continue;
      this.cache.delete(key);
      this.owned.delete(texture);
      texture.dispose();
      if (this.cache.size <= MAX_CACHED_TEXTURES) return;
    }
  }
}
