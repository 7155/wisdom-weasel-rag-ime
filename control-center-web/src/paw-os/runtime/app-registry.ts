import {
  pawOsAppRegistry,
  primaryDockAppIds,
  routePath as canonicalRoutePath,
  type PawOsAppId,
  type PawOsAppPresentation,
} from '@/features/paw-os/model/app-registry';

export type PawAppId = PawOsAppId;

export type PawAppDefinition = {
  id: PawAppId;
  label: string;
  shortLabel: string;
  tagline: string;
  route: string;
  kind: 'work' | 'agent' | 'system' | 'tool';
};

export const pawApps: readonly PawAppDefinition[] = pawOsAppRegistry.map((app) => ({
  id: app.id,
  label: app.label,
  shortLabel: app.shortLabel,
  tagline: app.tagline,
  route: app.id === 'system-settings'
    ? '/appearance'
    : app.defaultRouteId ? canonicalRoutePath(app.defaultRouteId) : `/${app.id}`,
  kind: appKind(app.presentation),
}));

const appById = new Map(pawApps.map((app) => [app.id, app]));

export function pawApp(id: PawAppId): PawAppDefinition {
  const app = appById.get(id);
  if (!app) throw new Error(`Unknown PAWOS App: ${id}`);
  return app;
}

export function pawAppForPath(path: string): PawAppDefinition | null {
  const normalized = normalizePath(path);
  if (normalized === '/' || normalized === canonicalRoutePath('project-field')) return null;
  if (normalized === '/appearance') return pawApp('system-settings');
  const canonical = pawOsAppRegistry.find((app) => (
    app.routeIds.some((routeId) => canonicalRoutePath(routeId) === normalized)
    || (app.defaultRouteId === null && `/${app.id}` === normalized)
  ));
  return canonical ? pawApp(canonical.id) : null;
}

export const pawDockAppIds: readonly PawAppId[] = primaryDockAppIds;

function normalizePath(path: string): string {
  const pathname = path.split(/[?#]/, 1)[0] || '/';
  return pathname.startsWith('/') ? pathname : `/${pathname}`;
}

function appKind(presentation: PawOsAppPresentation): PawAppDefinition['kind'] {
  if (presentation === 'conversation' || presentation === 'collaboration') return 'agent';
  if (presentation === 'system') return 'system';
  if (presentation === 'utility' || presentation === 'studio') return 'tool';
  return 'work';
}
