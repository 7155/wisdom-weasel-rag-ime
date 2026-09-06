import * as THREE from 'three';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ProjectGalaxySurfaces } from './project-galaxy-surfaces';

const requests = vi.hoisted(() => [] as Array<{ url: string; ready(texture: import('three').Texture): void; fail(): void }>);
vi.mock('three', async (original) => {
  const actual = await original<typeof import('three')>();
  return { ...actual, TextureLoader: class {
    load(url: string, ready: (texture: THREE.Texture) => void, _progress: unknown, fail: () => void) {
      requests.push({ url, ready, fail });
      return new actual.Texture();
    }
  } };
});
afterEach(() => { requests.length = 0; });

describe('local project surface resources', () => {
  it('shares color and elevation maps without reloading or freeing another material’s textures', () => {
    const invalidate = vi.fn();
    const library = new ProjectGalaxySurfaces(invalidate);
    const first = library.material(2), second = library.material(2);
    expect(requests).toHaveLength(2);
    const color = new THREE.Texture(), height = new THREE.Texture();
    const colorDisposed = vi.fn(), heightDisposed = vi.fn();
    color.addEventListener('dispose', colorDisposed); height.addEventListener('dispose', heightDisposed);
    requests.find((request) => request.url.endsWith('moon-color-2k.jpg'))!.ready(color);
    requests.find((request) => request.url.endsWith('moon-height-1k.jpg'))!.ready(height);
    expect(first.map).toBe(second.map);
    expect(first.bumpMap).toBe(second.displacementMap);
    expect(color.colorSpace).toBe(THREE.SRGBColorSpace);
    expect(height.colorSpace).toBe(THREE.NoColorSpace);
    first.dispose();
    expect(colorDisposed).not.toHaveBeenCalled();
    expect(heightDisposed).not.toHaveBeenCalled();
    library.material(2).dispose();
    expect(requests).toHaveLength(2);
    library.dispose(); library.dispose(); second.dispose();
    expect(colorDisposed).toHaveBeenCalledOnce();
    expect(heightDisposed).toHaveBeenCalledOnce();
    expect(invalidate).toHaveBeenCalledTimes(2);
  });

  it('disposes late arrivals without reviving a closed renderer or removed material', () => {
    const invalidate = vi.fn(), library = new ProjectGalaxySurfaces(invalidate);
    const material = library.material(1);
    material.dispose(); library.dispose();
    const texture = new THREE.Texture(), disposed = vi.fn();
    texture.addEventListener('dispose', disposed);
    requests[0]!.ready(texture);
    expect(material.map).toBeNull();
    expect(disposed).toHaveBeenCalledOnce();
    expect(invalidate).not.toHaveBeenCalled();
  });

  it('keeps a usable matte material after a file error and does not loop retries', () => {
    const library = new ProjectGalaxySurfaces(vi.fn());
    const first = library.material(1);
    requests[0]!.fail();
    const second = library.material(1);
    expect(requests).toHaveLength(1);
    expect(first.map).toBeNull();
    expect(second.map).toBeNull();
    first.dispose(); second.dispose(); library.dispose();
  });
});
