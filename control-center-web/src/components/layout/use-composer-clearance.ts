import { useEffect, type RefObject } from 'react';

const CLEARANCE_PROPERTY = '--workspace-composer-clearance';
const DOCK_SELECTOR = '.agent-composer-dock, .room-composer-dock';

/**
 * Publishes the floating composer dock or in-place question card's real
 * rendered height onto its host surface so the timeline can reserve exactly
 * that much footer space.
 *
 * The clearance used to be a hardcoded constant per workspace, which meant the
 * dock silently grew past it whenever composer typography, an attachment row,
 * the edit banner, the Room execution-phase strip or a breakpoint's padding
 * changed — covering the last message and its hover actions. Measuring removes
 * the whole class of bug: every one of those inputs is already reflected in
 * the dock's box.
 *
 * Deliberately writes straight to the host's inline style rather than React
 * state. The textarea uses `field-sizing: content`, so the observer fires while
 * the user types; re-rendering the timeline on those callbacks would cost far
 * more than it is worth, especially mid-stream.
 */
export function useComposerClearance(hostRef: RefObject<HTMLElement | null>): void {
  useEffect(() => {
    const host = hostRef.current;
    if (!host || typeof ResizeObserver !== 'function') return undefined;

    let dock: Element | null = null;

    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries.at(-1);
      if (!entry) return;
      const height = entry.borderBoxSize?.[0]?.blockSize ?? entry.contentRect.height;
      if (height > 0) host.style.setProperty(CLEARANCE_PROPERTY, `${Math.ceil(height)}px`);
    });

    // The dock element is swapped when the composer switches between its real
    // and pending forms, so re-target instead of observing a stale node.
    const retarget = () => {
      const next = host.querySelector(DOCK_SELECTOR);
      if (next === dock) return;
      if (dock) resizeObserver.unobserve(dock);
      dock = next;
      if (dock) resizeObserver.observe(dock);
      else host.style.removeProperty(CLEARANCE_PROPERTY);
    };

    retarget();
    // childList only, no subtree: the dock is a direct child, and a subtree
    // observer here would fire on every streamed transcript mutation.
    const mutationObserver = new MutationObserver(retarget);
    mutationObserver.observe(host, { childList: true });

    return () => {
      mutationObserver.disconnect();
      resizeObserver.disconnect();
      host.style.removeProperty(CLEARANCE_PROPERTY);
    };
  }, [hostRef]);
}
