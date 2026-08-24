import {
  useCallback,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type Dispatch,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type SetStateAction,
  type UIEvent as ReactUIEvent,
} from 'react';
import { flushSync } from 'react-dom';

/** One disclosure contract for every rich result. Native `details` behaviour
 * is not consistent once React owns `open`, especially for Space in WebKit.
 * This hook keeps pointer and keyboard activation on the same state path and
 * exposes the real controlled content through aria-controls. */
export function useDisclosureControl(initialOpen = false) {
  const [open, setOpen] = useState(initialOpen);
  const contentId = `agent-disclosure-${useId().replace(/:/gu, '')}`;
  return {
    contentId,
    open,
    setOpen,
    summaryProps: {
      'aria-controls': contentId,
      'aria-expanded': open,
      onClick: (event: ReactMouseEvent<HTMLElement>) => {
        toggleDisclosurePreservingAnchor(event, setOpen);
      },
      onKeyDown: (event: ReactKeyboardEvent<HTMLElement>) => {
        toggleDisclosureOnKeyPreservingAnchor(event, setOpen);
      },
    },
  };
}

/**
 * Toggles an inline disclosure without letting its virtualized row move the
 * summary the user just activated. Pointer and keyboard activation share the
 * same click path, and focus remains on the summary for the next command.
 */
export function toggleDisclosurePreservingAnchor(
  event: ReactMouseEvent<HTMLElement>,
  setOpen: Dispatch<SetStateAction<boolean>>,
) {
  event.preventDefault();
  toggleDisclosureFromTrigger(event.currentTarget, setOpen);
}

/** Native summary activation differs between WebKit and Chromium. Handling
 * Enter/Space directly prevents Space from scrolling the page and keeps the
 * controlled `details` state on one deterministic activation path. */
export function toggleDisclosureOnKeyPreservingAnchor(
  event: ReactKeyboardEvent<HTMLElement>,
  setOpen: Dispatch<SetStateAction<boolean>>,
) {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  event.preventDefault();
  toggleDisclosureFromTrigger(event.currentTarget, setOpen);
}

function toggleDisclosureFromTrigger(
  trigger: HTMLElement,
  setOpen: Dispatch<SetStateAction<boolean>>,
) {
  const scrollport = nearestScrollableAncestor(trigger);
  const anchorTop = trigger.getBoundingClientRect().top;
  const restoreAnchor = () => {
    if (!trigger.isConnected || !scrollport?.isConnected) return;
    const offset = trigger.getBoundingClientRect().top - anchorTop;
    if (offset) scrollport.scrollTop += offset;
  };

  flushSync(() => setOpen((current) => !current));
  trigger.focus({ preventScroll: true });
  restoreAnchor();
  // Virtuoso observes the changed row height after React commits. Correct once
  // more on the next frame so its measurement cannot move the chosen summary.
  window.requestAnimationFrame(restoreAnchor);
}

function nearestScrollableAncestor(element: HTMLElement): HTMLElement {
  for (let current = element.parentElement; current; current = current.parentElement) {
    const overflowY = window.getComputedStyle(current).overflowY;
    if (/(auto|scroll|overlay)/u.test(overflowY) && current.scrollHeight > current.clientHeight) {
      return current;
    }
  }
  const root = document.scrollingElement;
  return root instanceof HTMLElement ? root : document.documentElement;
}

/**
 * Keeps a bounded live region pinned only while its reader is already at the
 * end. Assigning `scrollTop` is intentionally motion-free: frequent Provider
 * deltas cannot queue animations, and reduced-motion users get the same stable
 * behavior without a second code path.
 */
export function useAutoFollowScroll<T extends HTMLElement>(
  contentKey: string,
  enabled = true,
) {
  const scrollRef = useRef<T>(null);
  const followingRef = useRef(true);
  const onScroll = useCallback((event: ReactUIEvent<T>) => {
    const scrollport = event.currentTarget;
    followingRef.current = (
      scrollport.scrollHeight - scrollport.clientHeight - scrollport.scrollTop
    ) <= 24;
    scrollport.dataset.following = String(followingRef.current);
  }, []);

  useLayoutEffect(() => {
    const scrollport = scrollRef.current;
    if (!scrollport || !enabled || !followingRef.current) return;
    scrollport.scrollTop = scrollport.scrollHeight;
    scrollport.dataset.following = 'true';
  }, [contentKey, enabled]);

  return { onScroll, scrollRef };
}
