import { describe, expect, it } from 'vitest';
import motionCss from './tokens.css?raw';
import { motionTokens, resolveReduceMotion } from './motion';

describe('comfort motion contract', () => {
  it('keeps press feedback subtle and route or panel movement brief', () => {
    expect(motionTokens.duration.enter).toBeGreaterThanOrEqual(0.16);
    expect(motionTokens.duration.enter).toBeLessThanOrEqual(0.24);
    expect(motionTokens.duration.panel).toBeGreaterThanOrEqual(0.16);
    expect(motionTokens.duration.panel).toBeLessThanOrEqual(0.24);
    expect(motionTokens.easing.press[1]).toBeLessThanOrEqual(1);
  });

  it('bounds companion status breathing instead of looping forever', () => {
    expect(motionTokens.statusPulse.iterations).toBeGreaterThan(0);
    expect(motionTokens.statusPulse.iterations).toBeLessThanOrEqual(3);
  });

  it('treats the operating-system comfort setting as a floor', () => {
    expect(resolveReduceMotion('system', true)).toBe(true);
    expect(resolveReduceMotion('full', true)).toBe(true);
    expect(resolveReduceMotion('full', false)).toBe(false);
    expect(resolveReduceMotion('reduce', false)).toBe(true);
  });

  it('retains brief feedback while removing repeated motion globally', () => {
    expect(motionCss).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*?animation-duration:\s*1ms !important;/);
    expect(motionCss).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*?transition-duration:\s*120ms !important;/);
    expect(motionCss).toMatch(/:root\[data-reduce-motion='true'\][\s\S]*?transition-duration:\s*120ms !important;/);
  });
});
