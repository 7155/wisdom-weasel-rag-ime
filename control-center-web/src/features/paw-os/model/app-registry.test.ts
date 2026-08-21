import { describe, expect, it } from 'vitest';
import { routeRegistry } from '@/app/route-registry';
import {
  pawOsAppForRoute,
  pawOsAppRegistry,
  primaryDockAppIds,
  wayfinderRouteId,
} from './app-registry';

describe('pawOsAppRegistry', () => {
  it('keeps Project Field as the windowless Wayfinder home', () => {
    expect(wayfinderRouteId).toBe('project-field');
    expect(pawOsAppForRoute('project-field')).toBeNull();
  });

  it('groups legacy routes into the accepted PAWOS Apps', () => {
    expect(pawOsAppRegistry.map((app) => app.id)).toEqual([
      'project-workbench',
      'agent',
      'rooms',
      'memory',
      'knowledge',
      'input-studio',
      'app-center',
      'system-monitor',
      'system-settings',
      'files',
      'browser',
      'terminal',
    ]);
    expect(pawOsAppForRoute('planning')?.id).toBe('project-workbench');
    expect(pawOsAppForRoute('work-documents')?.id).toBe('project-workbench');
    expect(pawOsAppForRoute('roles')?.id).toBe('agent');
    expect(pawOsAppForRoute('voice')?.id).toBe('input-studio');
    expect(pawOsAppForRoute('history')?.id).toBe('input-studio');
    expect(pawOsAppForRoute('diagnostics')?.id).toBe('system-monitor');
    expect(pawOsAppForRoute('governance')?.id).toBe('system-settings');
  });

  it('maps every old route exactly once, except the Wayfinder home', () => {
    const appRoutes = pawOsAppRegistry.flatMap((app) => app.routeIds);
    const expected = routeRegistry.map((route) => route.id).filter((id) => id !== wayfinderRouteId);

    expect(appRoutes).toHaveLength(new Set(appRoutes).size);
    expect(appRoutes.sort()).toEqual(expected.sort());
  });

  it('keeps system utilities out of the focused work Dock', () => {
    expect(primaryDockAppIds).toEqual([
      'project-workbench',
      'agent',
      'rooms',
      'memory',
      'knowledge',
      'input-studio',
      'files',
      'browser',
      'terminal',
    ]);
    expect(primaryDockAppIds.length).toBeLessThan(pawOsAppRegistry.length);
  });
});
