/**
 * 星空 real-surface catalog — which celestial bodies get a photographic
 * NASA-style texture, and how it is loaded without ever taxing boot.
 *
 * Craft ported from the MIT reference q-jade/solar-system (textureLoader.js):
 * real equirect surface maps with a graceful fallback. Adapted to PAWOS
 * constraints:
 *
 * - assets are downscaled 1k copies served from `public/paw-media/starfield/`
 *   (attribution in that directory) — never a CDN, never 2k originals;
 * - the procedural surface stays on screen until the photo arrives, so the
 *   sky is complete from the first frame and offline mode simply keeps the
 *   procedural look (async load + procedural fallback);
 * - only *prominent named* bodies get photos: Room partner planets carry the
 *   real planet names (Earth, Mars, …), Sol is the Room center, Session
 *   moons share one moon map. Galaxy mode stays fully procedural — dozens of
 *   tiny tinted stars gain nothing from a photo;
 * - `StarfieldSurfaceLoader` caches one THREE.Texture per key, remembers
 *   failures so an offline session never retries in a loop, and disposes
 *   everything exactly once on stage teardown.
 */

import * as THREE from 'three';
import type { SceneBody, SceneCenter, SceneMode } from './starfield-scene-model';

export type SurfaceKey =
  | 'sun'
  | 'mercury'
  | 'venus'
  | 'earth'
  | 'mars'
  | 'jupiter'
  | 'saturn'
  | 'uranus'
  | 'neptune'
  | 'moon'
  | 'saturn-ring';

/** Every shippable surface asset, relative to the app's public root. */
export const SURFACE_TEXTURE_FILES: Record<SurfaceKey, string> = {
  sun: 'paw-media/starfield/sun-1k.jpg',
  mercury: 'paw-media/starfield/mercury-1k.jpg',
  venus: 'paw-media/starfield/venus-1k.jpg',
  earth: 'paw-media/starfield/earth-1k.jpg',
  mars: 'paw-media/starfield/mars-1k.jpg',
  jupiter: 'paw-media/starfield/jupiter-1k.jpg',
  saturn: 'paw-media/starfield/saturn-1k.jpg',
  uranus: 'paw-media/starfield/uranus-1k.jpg',
  neptune: 'paw-media/starfield/neptune-1k.jpg',
  moon: 'paw-media/starfield/moon-512.jpg',
  'saturn-ring': 'paw-media/starfield/saturn-ring-1k.png',
};

/** Room partner celestial names (roomFocusCelestialName) → surface key. */
const PLANET_NAME_KEYS: Record<string, SurfaceKey> = {
  mercury: 'mercury',
  venus: 'venus',
  earth: 'earth',
  mars: 'mars',
  jupiter: 'jupiter',
  saturn: 'saturn',
  uranus: 'uranus',
  neptune: 'neptune',
};

export function surfaceTextureUrl(key: SurfaceKey): string {
  const base = import.meta.env?.BASE_URL ?? '/';
  return `${base.endsWith('/') ? base : `${base}/`}${SURFACE_TEXTURE_FILES[key]}`;
}

/**
 * Photo surface for an orbiting body, or null to stay procedural.
 * Only Room partner planets (named after real planets) and Session subagent
 * moons qualify; galaxy star systems keep their tinted procedural surface.
 */
export function bodySurfaceKey(
  mode: SceneMode,
  body: Pick<SceneBody, 'kind' | 'title'>,
): SurfaceKey | null {
  if (mode === 'room' && body.kind === 'planet') {
    return PLANET_NAME_KEYS[body.title.trim().toLowerCase()] ?? null;
  }
  if (mode === 'session' && body.kind === 'moon') return 'moon';
  return null;
}

/**
 * Photo surface for the stage center. Sol gets the real sun; the Session
 * core planet reads as the home planet, so it gets the earth day map.
 */
export function centerSurfaceKey(
  mode: SceneMode,
  center: Pick<SceneCenter, 'kind'>,
): SurfaceKey | null {
  if (center.kind === 'sun') return 'sun';
  if (mode === 'session' && center.kind === 'planet') return 'earth';
  return null;
}

/** Only the Room planet actually named Saturn carries the real ring strip. */
export function bodyRingSurfaceKey(
  mode: SceneMode,
  body: Pick<SceneBody, 'kind' | 'title'>,
): SurfaceKey | null {
  return mode === 'room' && body.kind === 'planet' && body.title.trim().toLowerCase() === 'saturn'
    ? 'saturn-ring'
    : null;
}

/**
 * Async, cached, failure-remembering texture loader for the catalog.
 * Load only starts when a body on stage asks for its surface, so opening
 * a Session sky never fetches Room planet maps and the galaxy fetches
 * nothing at all.
 */
export class StarfieldSurfaceLoader {
  private readonly loader = new THREE.TextureLoader();
  private readonly cache = new Map<SurfaceKey, THREE.Texture>();
  /** Keys that failed to load this stage lifetime — never retried. */
  private readonly failed = new Set<SurfaceKey>();
  private readonly waiting = new Map<SurfaceKey, Array<(texture: THREE.Texture) => void>>();
  private anisotropy = 1;
  private disposed = false;

  setAnisotropy(value: number): void {
    this.anisotropy = Math.max(1, Math.floor(value));
  }

  owns(texture: THREE.Texture): boolean {
    for (const owned of this.cache.values()) {
      if (owned === texture) return true;
    }
    return false;
  }

  /**
   * Deliver the texture for `key` to `onReady` — synchronously when cached,
   * otherwise once the fetch completes. Failures are silent: the procedural
   * surface simply remains.
   */
  load(key: SurfaceKey, onReady: (texture: THREE.Texture) => void): void {
    if (this.disposed || this.failed.has(key)) return;
    const cached = this.cache.get(key);
    if (cached) {
      onReady(cached);
      return;
    }
    const queue = this.waiting.get(key);
    if (queue) {
      queue.push(onReady);
      return;
    }
    this.waiting.set(key, [onReady]);
    this.loader.load(
      surfaceTextureUrl(key),
      (texture) => {
        if (this.disposed) {
          texture.dispose();
          return;
        }
        texture.colorSpace = THREE.SRGBColorSpace;
        texture.anisotropy = this.anisotropy;
        if (key === 'saturn-ring') {
          // Ring strip UVs: u = radial band, v = angle around the ring —
          // the angular direction is cyclic, so it must repeat.
          texture.wrapS = THREE.ClampToEdgeWrapping;
          texture.wrapT = THREE.RepeatWrapping;
        } else {
          // Equirect surface: horizontal wrap keeps the seam invisible.
          texture.wrapS = THREE.RepeatWrapping;
          texture.wrapT = THREE.ClampToEdgeWrapping;
        }
        this.cache.set(key, texture);
        const listeners = this.waiting.get(key) ?? [];
        this.waiting.delete(key);
        for (const listener of listeners) listener(texture);
      },
      undefined,
      () => {
        this.failed.add(key);
        this.waiting.delete(key);
      },
    );
  }

  dispose(): void {
    this.disposed = true;
    for (const texture of this.cache.values()) texture.dispose();
    this.cache.clear();
    this.waiting.clear();
    this.failed.clear();
  }
}
