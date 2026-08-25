import { useEffect, useRef, type RefObject } from "react";
import type { ScrollAnchor } from "./usePinnedTranscript";

const memory = new Map<string, ScrollAnchor>();

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
