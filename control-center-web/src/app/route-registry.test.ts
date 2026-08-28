import { describe, expect, it } from 'vitest';
import { routeRegistry } from '@/app/route-registry';

describe('route registry', () => {
  it('contains every control-center route exactly once', () => {
    expect(routeRegistry).toHaveLength(20);
    expect(new Set(routeRegistry.map((route) => route.id)).size).toBe(20);
    expect(new Set(routeRegistry.map((route) => route.path)).size).toBe(20);
    expect(routeRegistry).toContainEqual(
      expect.objectContaining({ id: 'trace-agent', path: '/trace-agent' }),
    );
  });
});
