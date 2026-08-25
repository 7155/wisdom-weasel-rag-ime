/**
 * 星空 render budget — pure quality/performance decisions for the WebGL
 * stage, kept renderer-free so they stay unit-testable in Node:
 *
 * - device pixel ratio is capped by a hard ceiling *and* a total pixel
 *   budget, so a fullscreen retina sky never renders 8M+ pixels per frame;
 * - sphere geometry LOD levels whose switch distances scale with body size,
 *   so far-away moons cost a fraction of the vertices;
 * - surface texture resolutions bounded per body size, so a Session with
 *   fifty moons stays within a few megabytes of texture memory.
 */

/**
 * Hard DPR ceiling. A deep-space scene is dominated by smooth gradients and
 * additive glows, so anything beyond 1.5 spends GPU time on pixels the eye
 * cannot separate — the fill-rate saving at 1.5 vs 2 is ~44% per frame.
 */
export const MAX_PIXEL_RATIO = 1.5;

/** Total pixel budget per frame ≈ 1080p × 1.5² supersample, minus headroom. */
export const MAX_RENDER_PIXELS = 4_200_000;

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

/**
 * Effective renderer pixel ratio: clamp to [1, MAX_PIXEL_RATIO], then shrink
 * further whenever width × height × ratio² would exceed the pixel budget.
 */
export function starfieldPixelRatio(devicePixelRatio: number, width: number, height: number): number {
  const capped = Math.min(Math.max(devicePixelRatio || 1, 1), MAX_PIXEL_RATIO);
  const area = Math.max(width * height, 1);
  if (area * capped * capped <= MAX_RENDER_PIXELS) return round2(capped);
  return round2(Math.max(1, Math.sqrt(MAX_RENDER_PIXELS / area)));
}

export type SphereDetail = 'high' | 'medium' | 'low';

/** Width/height segment pairs for the three shared unit-sphere geometries. */
export const SPHERE_SEGMENTS: Record<SphereDetail, readonly [number, number]> = {
  high: [48, 28],
  medium: [24, 16],
  low: [12, 8],
};

export interface SphereLodLevel {
  detail: SphereDetail;
  /** World distance at which this level becomes active. */
  distance: number;
}

/**
 * LOD switch distances scale with the square root of body size: a small moon
 * drops detail much closer to the camera than a large planet, because its
 * screen footprint shrinks faster.
 */
export function sphereLodLevels(size: number): SphereLodLevel[] {
  const scale = Math.sqrt(Math.min(Math.max(size, 0.2), 2));
  return [
    { detail: 'high', distance: 0 },
    { detail: 'medium', distance: round2(15 * scale) },
    { detail: 'low', distance: round2(30 * scale) },
  ];
}

export interface SurfaceTextureSize {
  width: number;
  height: number;
}

/** Equirect surface resolution per body size — bounded at 512×256. */
export function surfaceTextureSize(bodySize: number): SurfaceTextureSize {
  const width = bodySize < 0.45 ? 128 : bodySize < 1 ? 256 : 512;
  return { width, height: width / 2 };
}
