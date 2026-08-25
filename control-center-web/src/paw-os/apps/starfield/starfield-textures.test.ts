import * as THREE from 'three';
import { describe, expect, it, vi } from 'vitest';
import { sceneTextureKeyForCelestial } from './starfield-scene-model';
import {
  STARFIELD_TEXTURE_MANIFEST,
  StarfieldTextureSet,
  starfieldTextureUrl,
  type RawTextureLoad,
} from './starfield-textures';

/** Manual-resolve fake loader so tests control async arrival order. */
function fakeLoader() {
  const pending: Array<{ url: string; onLoad: (t: THREE.Texture) => void; onError: () => void }> = [];
  const load: RawTextureLoad = (url, onLoad, onError) => {
    pending.push({ url, onLoad, onError });
  };
  return { pending, load };
}

describe('starfield texture budget', () => {
  it('ships every map downscaled to the 1k budget (moon 512) under paw-media/starfield', () => {
    for (const [key, asset] of Object.entries(STARFIELD_TEXTURE_MANIFEST)) {
      expect(asset.file, key).toMatch(/^paw-media\/starfield\//);
      if (key === 'saturnRing') continue; // 12 KB alpha strip, not a surface map
      expect(asset.width, key).toBeLessThanOrEqual(1024);
      expect(asset.height, key).toBeLessThanOrEqual(512);
    }
    expect(STARFIELD_TEXTURE_MANIFEST.moon.width).toBe(512);
    expect(starfieldTextureUrl('earth')).toContain('paw-media/starfield/earth-1k.jpg');
  });

  it('maps Room celestial names onto real planet maps and unknown names onto the procedural fallback', () => {
    expect(sceneTextureKeyForCelestial('Earth')).toBe('earth');
    expect(sceneTextureKeyForCelestial('Saturn')).toBe('saturn');
    expect(sceneTextureKeyForCelestial('Planet 9')).toBeNull();
    expect(sceneTextureKeyForCelestial('Sol')).toBeNull();
  });
});

describe('StarfieldTextureSet', () => {
  it('loads each key once, fans out to all subscribers and answers later gets synchronously', () => {
    const { pending, load } = fakeLoader();
    const set = new StarfieldTextureSet(load);
    const first = vi.fn();
    const second = vi.fn();

    set.get('mars', first);
    set.get('mars', second);
    expect(pending).toHaveLength(1);

    const texture = new THREE.Texture();
    pending[0]!.onLoad(texture);
    expect(first).toHaveBeenCalledWith(texture);
    expect(second).toHaveBeenCalledWith(texture);
    expect(texture.userData.sfOwnedBySet).toBe(true);

    const third = vi.fn();
    set.get('mars', third);
    expect(third).toHaveBeenCalledWith(texture);
    expect(pending).toHaveLength(1);
    set.dispose();
  });

  it('keeps the procedural fallback silently when a map fails to load', () => {
    const { pending, load } = fakeLoader();
    const set = new StarfieldTextureSet(load);
    const onReady = vi.fn();

    set.get('venus', onReady);
    pending[0]!.onError();
    expect(onReady).not.toHaveBeenCalled();
    set.dispose();
  });

  it('disposes ready textures on exit and frees in-flight arrivals — no leaks after leaving 星空', () => {
    const { pending, load } = fakeLoader();
    const set = new StarfieldTextureSet(load);
    const ready = new THREE.Texture();
    const readyDispose = vi.spyOn(ready, 'dispose');

    set.get('jupiter', vi.fn());
    set.get('moon', vi.fn());
    pending[0]!.onLoad(ready);

    set.dispose();
    expect(readyDispose).toHaveBeenCalledTimes(1);

    // The in-flight moon map arrives after exit: it must be freed immediately.
    const late = new THREE.Texture();
    const lateDispose = vi.spyOn(late, 'dispose');
    pending[1]!.onLoad(late);
    expect(lateDispose).toHaveBeenCalledTimes(1);

    // A disposed set never starts new loads.
    set.get('earth', vi.fn());
    expect(pending).toHaveLength(2);
  });
});
