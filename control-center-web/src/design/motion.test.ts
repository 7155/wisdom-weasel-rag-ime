import { describe, expect, it } from 'vitest';
import { motionTokens } from './motion';

describe('comfort motion contract', () => {
  it('keeps press feedback subtle and route or panel movement brief', () => {
    expect(motionTokens.scale.press).toBeGreaterThanOrEqual(0.98);
    expect(motionTokens.scale.press).toBeLessThanOrEqual(0.99);
    expect(motionTokens.duration.enter).toBeGreaterThanOrEqual(0.16);
    expect(motionTokens.duration.enter).toBeLessThanOrEqual(0.24);
    expect(motionTokens.duration.panel).toBeGreaterThanOrEqual(0.16);
    expect(motionTokens.duration.panel).toBeLessThanOrEqual(0.24);
  });

  it('bounds companion status breathing instead of looping forever', () => {
    expect(motionTokens.statusPulse.iterations).toBeGreaterThan(0);
    expect(motionTokens.statusPulse.iterations).toBeLessThanOrEqual(3);
  });
});
