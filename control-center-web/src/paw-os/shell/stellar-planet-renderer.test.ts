import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createStellarPlanetRenderer } from './stellar-planet-renderer';

const frames = new Map<number, FrameRequestCallback>();
let nextFrame = 0;
function advance(now: number) {
  const pending = [...frames.values()];
  frames.clear();
  pending.forEach((callback) => callback(now));
}
function material() {
  const calls = {
    drawArrays: vi.fn(), uniform1f: vi.fn(), deleteTexture: vi.fn(),
    deleteBuffer: vi.fn(), deleteProgram: vi.fn(), deleteShader: vi.fn(),
    createProgram: () => ({}), createBuffer: () => ({}), createTexture: () => ({}),
    createShader: () => ({}), getShaderParameter: () => true, getProgramParameter: () => true,
  };
  const gl = new Proxy(calls, { get: (target, key) => key in target ? target[key as keyof typeof calls] : () => {} });
  const canvas = document.createElement('canvas');
  Object.defineProperty(canvas, 'clientWidth', { value: 1200 });
  vi.spyOn(canvas, 'getContext').mockReturnValue(gl as unknown as WebGLRenderingContext);
  const unavailable = vi.fn();
  const renderer = createStellarPlanetRenderer(canvas, document.createElement('img'), unavailable)!;
  return { canvas, renderer, calls, unavailable };
}

beforeEach(() => {
  frames.clear(); nextFrame = 0;
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { frames.set(++nextFrame, callback); return nextFrame; });
  vi.stubGlobal('cancelAnimationFrame', (id: number) => frames.delete(id));
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('optional stellar planet material', () => {
  it('bounds resolution and material paints, and stops scheduling while the desktop is covered', () => {
    const { canvas, renderer, calls } = material();
    expect([canvas.width, canvas.height]).toEqual([960, 640]);
    expect(frames.size).toBe(0);
    renderer.setPaused(false);
    advance(0); advance(16); advance(32);
    expect(calls.drawArrays).toHaveBeenCalledTimes(1);
    advance(50);
    expect(calls.drawArrays).toHaveBeenCalledTimes(2);
    renderer.setPaused(true);
    expect(frames.size).toBe(0);
    advance(100_000);
    expect(calls.drawArrays).toHaveBeenCalledTimes(2);
    renderer.setPaused(false);
    advance(200_000); advance(200_050);
    // Hidden wall time must not jump the material phase on return.
    expect(calls.uniform1f.mock.calls.at(-1)?.[1]).toBe(.1);
    renderer.dispose();
    expect(frames.size).toBe(0);
  });

  it('returns to the image on context loss and releases resources exactly once', () => {
    const { canvas, renderer, calls, unavailable } = material();
    renderer.setPaused(false);
    canvas.dispatchEvent(new Event('webglcontextlost', { cancelable: true }));
    expect(unavailable).toHaveBeenCalledOnce();
    expect(frames.size).toBe(0);
    renderer.setPaused(false); renderer.resize(); renderer.dispose();
    expect(calls.deleteTexture).toHaveBeenCalledOnce();
    expect(calls.deleteBuffer).toHaveBeenCalledOnce();
    expect(calls.deleteProgram).toHaveBeenCalledOnce();
    expect(calls.deleteShader).toHaveBeenCalledTimes(2);
    expect(frames.size).toBe(0);
  });

  it('leaves the original image available when WebGL cannot be created', () => {
    const canvas = document.createElement('canvas');
    vi.spyOn(canvas, 'getContext').mockReturnValue(null);
    expect(createStellarPlanetRenderer(canvas, document.createElement('img'), vi.fn())).toBeNull();
    expect(frames.size).toBe(0);
  });
});
