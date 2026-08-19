import { describe, expect, it } from 'vitest';
import { canonicalRoutePath, routeRegistry } from '@/app/route-registry';

describe('route registry', () => {
  it('contains every control-center route exactly once', () => {
    expect(routeRegistry).toHaveLength(19);
    expect(new Set(routeRegistry.map((route) => route.id)).size).toBe(19);
    expect(new Set(routeRegistry.map((route) => route.path)).size).toBe(19);
    expect(routeRegistry.some((route) => route.path === '/plugins')).toBe(false);
  });

  it('keeps the retired plugin address pointed at the merged settings page', () => {
    expect(canonicalRoutePath('/plugins')).toBe('/roles');
    expect(canonicalRoutePath('/roles')).toBe('/roles');
  });
});
