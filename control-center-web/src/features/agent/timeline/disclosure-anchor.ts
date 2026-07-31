import type { Dispatch, MouseEvent as ReactMouseEvent, SetStateAction } from 'react';
import { flushSync } from 'react-dom';

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
  const trigger = event.currentTarget;
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

function nearestScrollableAncestor(element: HTMLElement): HTMLElement | null {
  for (let current = element.parentElement; current; current = current.parentElement) {
    const overflowY = window.getComputedStyle(current).overflowY;
    if (/(auto|scroll|overlay)/u.test(overflowY) && current.scrollHeight > current.clientHeight) {
      return current;
    }
  }
  return null;
}
