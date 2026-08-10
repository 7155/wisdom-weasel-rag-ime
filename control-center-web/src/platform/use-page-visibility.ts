import { useSyncExternalStore } from 'react';

function subscribe(listener: () => void): () => void {
  document.addEventListener('visibilitychange', listener);
  return () => document.removeEventListener('visibilitychange', listener);
}

function pageIsVisible(): boolean {
  return document.visibilityState === 'visible';
}

export function usePageVisibility(): boolean {
  return useSyncExternalStore(subscribe, pageIsVisible, () => true);
}
