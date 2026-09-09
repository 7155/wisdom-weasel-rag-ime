import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createStellarStopMotion } from './stellar-stop-motion';

const originalDecode = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'decode');
const originalAnimate = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'animate');
let running: { finish: () => void; pause: ReturnType<typeof vi.fn>; play: ReturnType<typeof vi.fn>; cancel: ReturnType<typeof vi.fn> }[];
const animate = vi.fn(() => {
  let finish!: () => void;
  const finished = new Promise<void>((resolve) => { finish = resolve; });
  const animation = { finished, finish, pause: vi.fn(), play: vi.fn(), cancel: vi.fn() };
  running.push(animation);
  return animation;
});
beforeEach(() => {
  running = []; animate.mockClear();
  Object.defineProperty(HTMLImageElement.prototype, 'decode', { configurable: true, value: vi.fn().mockResolvedValue(undefined) });
  Object.defineProperty(HTMLElement.prototype, 'animate', { configurable: true, value: animate });
});
afterEach(() => {
  document.body.replaceChildren();
  if (originalDecode) Object.defineProperty(HTMLImageElement.prototype, 'decode', originalDecode);
  else Reflect.deleteProperty(HTMLImageElement.prototype, 'decode');
  if (originalAnimate) Object.defineProperty(HTMLElement.prototype, 'animate', originalAnimate);
  else Reflect.deleteProperty(HTMLElement.prototype, 'animate');
});
const settle = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };

it('dissolves slowly, freezes both layers while paused, and resumes the same blend', async () => {
  const image = document.createElement('img');
  document.body.append(image);
  const player = createStellarStopMotion(image);
  player.setEnabled(true);
  await settle();
  const overlay = document.querySelector<HTMLImageElement>('[data-crossfade-layer]')!;
  expect(image.src).toContain('/00.png');
  expect(overlay.src).toContain('/01.png');
  expect(animate).toHaveBeenCalledWith([{ opacity: 0 }, { opacity: 1 }], { duration: 2000, easing: 'linear', fill: 'forwards' });
  player.setEnabled(false);
  expect(running.slice(0, 2).every((a) => a.pause.mock.calls.length === 1)).toBe(true);
  player.setEnabled(true);
  expect(running.slice(0, 2).every((a) => a.play.mock.calls.length === 1)).toBe(true);
  expect(animate).toHaveBeenCalledTimes(2);
  for (let index = 1; index <= 10; index++) {
    running.slice(-2).forEach((a) => a.finish());
    await settle();
    expect(image.src).toContain(`/${String(index <= 9 ? index : 8).padStart(2, '0')}.png`);
  }
  player.dispose();
  expect(document.querySelector('[data-crossfade-layer]')).toBeNull();
  expect(running.every((a) => a.cancel.mock.calls.length === 1)).toBe(true);
});

it('retains the fallback when decoding fails', async () => {
  vi.mocked(HTMLImageElement.prototype.decode).mockRejectedValue(new Error('unavailable'));
  const image = document.createElement('img');
  image.src = '/fallback.png';
  const player = createStellarStopMotion(image);
  player.setEnabled(true);
  await settle();
  expect(image.src).toContain('/fallback.png');
  expect(animate).not.toHaveBeenCalled();
  player.dispose();
});

it('does not insert a layer or start motion after unmount during decoding', async () => {
  const image = document.createElement('img');
  document.body.append(image);
  const player = createStellarStopMotion(image);
  player.setEnabled(true);
  player.dispose();
  await settle();
  expect(document.querySelector('[data-crossfade-layer]')).toBeNull();
  expect(animate).not.toHaveBeenCalled();
});
