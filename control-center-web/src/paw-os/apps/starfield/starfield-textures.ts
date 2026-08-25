/**
 * 星空 surface-map budget and loader.
 *
 * Real NASA-style maps (ported from the MIT q-jade/solar-system reference,
 * see public/paw-media/starfield/ATTRIBUTION.md) are served as downscaled
 * 1k JPEGs (moon 512) so the whole set stays under ~0.6 MB. Loading is:
 * - lazy — only requested once the WebGL stage exists, and only the keys the
 *   current scene actually uses;
 * - non-blocking — bodies render with their procedural color immediately and
 *   swap the map in when it arrives;
 * - leak-free — a `StarfieldTextureSet` is owned by one stage and disposes
 *   every GPU texture (including in-flight arrivals) when the stage exits.
 */

import * as THREE from 'three';
import type { SceneTextureKey } from './starfield-scene-model';

/** All loadable maps: body surfaces plus the Saturn ring alpha strip. */
export type StarfieldMapKey = SceneTextureKey | 'saturnRing';

export interface StarfieldTextureAsset {
  /** Path under the Vite public root, joined with BASE_URL at runtime. */
  file: string;
  /** Shipped pixel size — the documented download budget. */
  width: number;
  height: number;
}

export const STARFIELD_TEXTURE_MANIFEST: Record<StarfieldMapKey, StarfieldTextureAsset> = {
  sun: { file: 'paw-media/starfield/sun-1k.jpg', width: 1024, height: 512 },
  mercury: { file: 'paw-media/starfield/mercury-1k.jpg', width: 1024, height: 512 },
  venus: { file: 'paw-media/starfield/venus-1k.jpg', width: 1024, height: 512 },
  earth: { file: 'paw-media/starfield/earth-1k.jpg', width: 1024, height: 512 },
  mars: { file: 'paw-media/starfield/mars-1k.jpg', width: 1024, height: 512 },
  jupiter: { file: 'paw-media/starfield/jupiter-1k.jpg', width: 1024, height: 512 },
  saturn: { file: 'paw-media/starfield/saturn-1k.jpg', width: 1024, height: 512 },
  uranus: { file: 'paw-media/starfield/uranus-1k.jpg', width: 1024, height: 512 },
  neptune: { file: 'paw-media/starfield/neptune-1k.jpg', width: 1024, height: 512 },
  moon: { file: 'paw-media/starfield/moon-512.jpg', width: 512, height: 256 },
  saturnRing: { file: 'paw-media/starfield/saturn-ring-1k.png', width: 2048, height: 125 },
};

export function starfieldTextureUrl(key: StarfieldMapKey): string {
  return `${import.meta.env.BASE_URL}${STARFIELD_TEXTURE_MANIFEST[key].file}`;
}

/** Raw async image → texture loader, injectable so tests never touch DOM I/O. */
export type RawTextureLoad = (
  url: string,
  onLoad: (texture: THREE.Texture) => void,
  onError: () => void,
) => void;

function defaultRawLoad(
  url: string,
  onLoad: (texture: THREE.Texture) => void,
  onError: () => void,
): void {
  new THREE.TextureLoader().load(url, onLoad, undefined, onError);
}

interface TextureEntry {
  state: 'loading' | 'ready' | 'failed';
  texture: THREE.Texture | null;
  subscribers: Array<(texture: THREE.Texture) => void>;
}

/**
 * One stage's texture pool. `get` never blocks: callers keep their procedural
 * material and receive the texture asynchronously exactly once. Failed loads
 * stay silent — the procedural fallback simply remains. `dispose` frees every
 * ready texture and guarantees in-flight arrivals are disposed on arrival.
 */
export class StarfieldTextureSet {
  private readonly entries = new Map<StarfieldMapKey, TextureEntry>();
  private disposed = false;

  constructor(private readonly rawLoad: RawTextureLoad = defaultRawLoad) {}

  get(key: StarfieldMapKey, onReady: (texture: THREE.Texture) => void): void {
    if (this.disposed) return;
    const existing = this.entries.get(key);
    if (existing) {
      if (existing.state === 'ready' && existing.texture) onReady(existing.texture);
      else if (existing.state === 'loading') existing.subscribers.push(onReady);
      return;
    }
    const entry: TextureEntry = { state: 'loading', texture: null, subscribers: [onReady] };
    this.entries.set(key, entry);
    this.rawLoad(
      starfieldTextureUrl(key),
      (texture) => {
        if (this.disposed) {
          texture.dispose();
          return;
        }
        texture.colorSpace = THREE.SRGBColorSpace;
        texture.anisotropy = 4;
        // The set owns disposal; material teardown must not double-free.
        texture.userData.sfOwnedBySet = true;
        entry.state = 'ready';
        entry.texture = texture;
        const subscribers = entry.subscribers;
        entry.subscribers = [];
        for (const subscriber of subscribers) subscriber(texture);
      },
      () => {
        entry.state = 'failed';
        entry.subscribers = [];
      },
    );
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    for (const entry of this.entries.values()) {
      entry.texture?.dispose();
      entry.texture = null;
      entry.subscribers = [];
    }
    this.entries.clear();
  }
}
