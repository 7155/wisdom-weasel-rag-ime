import { useSyncExternalStore } from 'react';
import { routeRegistry, type RouteDefinition } from '@/app/route-registry';

function subscribe(callback: () => void) {
  window.addEventListener('hashchange', callback);
  window.addEventListener('popstate', callback);
  return () => {
    window.removeEventListener('hashchange', callback);
    window.removeEventListener('popstate', callback);
  };
}

function getPath(): string {
  if (typeof window === 'undefined') return '/overview';
  const raw = window.location.hash.replace(/^#/, '').split('?')[0];
  return raw || '/overview';
}

export function useHashRoute(): RouteDefinition {
  const path = useSyncExternalStore(subscribe, getPath, () => '/overview');
  return routeRegistry.find((route) => route.path === path) ?? routeRegistry[0];
}
