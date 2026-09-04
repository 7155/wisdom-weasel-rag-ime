import { useEffect, useRef, type RefObject } from 'react';
import type { ScrollAnchor } from './usePinnedTranscript';

/* Vendored clean-room scroll memory. See ../ATTRIBUTION.md.
 *
 * Reading position survives switching away and back, so a long transcript is
 * not silently reset to the bottom by window navigation. */

const memory = new Map<string, ScrollAnchor>();

/** Read the previous anchor before the transcript's first DOM commit. This
 * lets the virtualizer mount the remembered row directly instead of briefly
 * materialising the entire history or flashing the newest tail first. */
export function readSessionScrollMemory(sessionKey: string): ScrollAnchor | undefined {
  return memory.get(sessionKey);
}

export function useSessionScrollMemory(
  sessionKey: string,
  captureAnchor: () => ScrollAnchor,
  restoreAnchor: (anchor: ScrollAnchor) => void,
  scrollRef: RefObject<HTMLElement | null>,
) {
  const previousKey = useRef(sessionKey);

  useEffect(() => {
    const stored = memory.get(sessionKey);
    if (stored) restoreAnchor(stored);
    previousKey.current = sessionKey;
    return () => {
      memory.set(sessionKey, captureAnchor());
    };
  }, [captureAnchor, restoreAnchor, scrollRef, sessionKey]);

  return {
    saveNow() {
      memory.set(sessionKey, captureAnchor());
    },
    clear() {
      memory.delete(sessionKey);
    },
  };
}

/** Test/host escape hatch: forget every remembered reading position. */
export function clearConversationScrollMemory(): void {
  memory.clear();
}
