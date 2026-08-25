import { existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import {
  bodyRingSurfaceKey,
  bodySurfaceKey,
  centerSurfaceKey,
  StarfieldSurfaceLoader,
  SURFACE_TEXTURE_FILES,
  surfaceTextureUrl,
  type SurfaceKey,
} from './starfield-surface-catalog';
import type { SceneBody, SceneCenter } from './starfield-scene-model';

type BodyIdentity = Pick<SceneBody, 'kind' | 'title'>;

function body(kind: SceneBody['kind'], title: string): BodyIdentity {
  return { kind, title };
}

describe('starfield surface catalog', () => {
  it('serves every asset from the app bundle, never a CDN', () => {
    for (const [key, file] of Object.entries(SURFACE_TEXTURE_FILES)) {
      expect(file.startsWith('paw-media/starfield/')).toBe(true);
      const url = surfaceTextureUrl(key as SurfaceKey);
      expect(url).not.toMatch(/^https?:/);
      expect(url.endsWith(file)).toBe(true);
    }
  });

  it('actually ships every cataloged asset in the public starfield directory', () => {
    const here = dirname(fileURLToPath(import.meta.url));
    for (const file of Object.values(SURFACE_TEXTURE_FILES)) {
      const onDisk = resolve(here, '../../../../public', file);
      expect(existsSync(onDisk), `missing shipped texture: ${file}`).toBe(true);
    }
  });

  it('never delivers a texture after dispose', () => {
    const loader = new StarfieldSurfaceLoader();
    loader.dispose();
    let delivered = false;
    loader.load('earth', () => {
      delivered = true;
    });
    expect(delivered).toBe(false);
  });

  it('gives Room partner planets the map of the planet they are named after', () => {
    expect(bodySurfaceKey('room', body('planet', 'Mars'))).toBe('mars');
    // Casing and stray whitespace come from user-facing partner names.
    expect(bodySurfaceKey('room', body('planet', '  jupiter '))).toBe('jupiter');
  });

  it('leaves every other body procedural', () => {
    // A partner without a planet name has no photo to wear.
    expect(bodySurfaceKey('room', body('planet', 'Reviewer'))).toBeNull();
    // Galaxy star systems are tiny and numerous: photos buy nothing.
    expect(bodySurfaceKey('galaxy', body('star', 'Earth'))).toBeNull();
    expect(bodySurfaceKey('room', body('star', 'Earth'))).toBeNull();
  });

  it('shares one moon map across Session subagents', () => {
    expect(bodySurfaceKey('session', body('moon', 'subagent-1'))).toBe('moon');
    expect(bodySurfaceKey('session', body('moon', 'subagent-2'))).toBe('moon');
  });

  it('gives the stage center the sun or the home planet', () => {
    const sun: Pick<SceneCenter, 'kind'> = { kind: 'sun' };
    const planet: Pick<SceneCenter, 'kind'> = { kind: 'planet' };
    expect(centerSurfaceKey('room', sun)).toBe('sun');
    expect(centerSurfaceKey('session', planet)).toBe('earth');
    // A galaxy has no single home world.
    expect(centerSurfaceKey('galaxy', planet)).toBeNull();
  });

  it('reserves the real ring strip for the planet actually named Saturn', () => {
    expect(bodyRingSurfaceKey('room', body('planet', 'Saturn'))).toBe('saturn-ring');
    expect(bodyRingSurfaceKey('room', body('planet', 'Jupiter'))).toBeNull();
    expect(bodyRingSurfaceKey('session', body('moon', 'Saturn'))).toBeNull();
  });
});
