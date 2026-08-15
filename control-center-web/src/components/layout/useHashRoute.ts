import { useSyncExternalStore } from 'react';
import { routeRegistry, type RouteDefinition } from '@/app/route-registry';
import { router } from '@/app/router';

function subscribe(callback: () => void) {
  const unsubscribeRouter = router.subscribe(callback);
  window.addEventListener('hashchange', callback);
  window.addEventListener('popstate', callback);
  return () => {
    unsubscribeRouter();
    window.removeEventListener('hashchange', callback);
    window.removeEventListener('popstate', callback);
  };
}

function getPath(): string {
  if (typeof window === 'undefined') return '/agent';
  const raw = window.location.hash.replace(/^#/, '').split('?')[0];
  return raw || '/agent';
}

export function useHashRoute(): RouteDefinition {
  const path = useSyncExternalStore(subscribe, getPath, () => '/agent');
  return routeRegistry.find((route) => route.path === path)
    ?? routeRegistry.find((route) => route.id === 'agent')!;
}
