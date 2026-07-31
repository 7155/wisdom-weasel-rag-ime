import { useEffect, useRef, useState, type RefObject } from 'react';

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  'summary',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => mediaMatches(query));

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const media = window.matchMedia(query);
    const update = () => setMatches(media.matches);
    update();
    if (typeof media.addEventListener === 'function') {
      media.addEventListener('change', update);
      return () => media.removeEventListener('change', update);
    }
    media.addListener?.(update);
    return () => media.removeListener?.(update);
  }, [query]);

  return matches;
}

export function useModalPanel({
  active,
  panelRef,
  returnFocusRef,
  onClose,
  initialFocusSelector,
}: {
  active: boolean;
  panelRef: RefObject<HTMLElement | null>;
  returnFocusRef: RefObject<HTMLElement | null>;
  onClose: () => void;
  initialFocusSelector?: string;
}): void {
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    if (!active) return;
    const panel = panelRef.current;
    if (!panel) return;
    const activePanel = panel;
    const previousFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const frame = requestAnimationFrame(() => {
      const preferred = initialFocusSelector
        ? activePanel.querySelector<HTMLElement>(initialFocusSelector)
        : null;
      (preferred ?? focusableElements(activePanel)[0] ?? activePanel).focus();
    });

    function handleKeyDown(event: KeyboardEvent): void {
      const eventTarget = event.target instanceof Element ? event.target : document.activeElement;
      const nestedLayer = eventTarget?.closest<HTMLElement>(
        '[role="dialog"][aria-modal="true"], [role="menu"][data-state="open"], [role="listbox"][data-state="open"], .ui-popover[data-state="open"]',
      );
      if (nestedLayer && nestedLayer !== activePanel) return;
      if (event.key === 'Escape' && !event.defaultPrevented) {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key !== 'Tab' || event.defaultPrevented) return;
      const focusable = focusableElements(activePanel);
      if (!focusable.length) {
        event.preventDefault();
        activePanel.focus();
        return;
      }
      const first = focusable[0]!;
      const last = focusable.at(-1)!;
      if (event.shiftKey && (document.activeElement === first || !activePanel.contains(document.activeElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !activePanel.contains(document.activeElement))) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener('keydown', handleKeyDown, true);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener('keydown', handleKeyDown, true);
      const target = returnFocusRef.current ?? previousFocus;
      if (target?.isConnected) requestAnimationFrame(() => target.focus());
    };
  }, [active, initialFocusSelector, panelRef, returnFocusRef]);
}

function mediaMatches(query: string): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia(query).matches;
}

function focusableElements(panel: HTMLElement): HTMLElement[] {
  return [...panel.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((element) => (
    !element.hasAttribute('hidden')
    && element.getAttribute('aria-hidden') !== 'true'
    && !element.closest('[inert]')
    && !isInsideCollapsedDetails(element)
  ));
}

function isInsideCollapsedDetails(element: HTMLElement): boolean {
  const details = element.closest<HTMLDetailsElement>('details:not([open])');
  return Boolean(details && details.querySelector(':scope > summary') !== element);
}
