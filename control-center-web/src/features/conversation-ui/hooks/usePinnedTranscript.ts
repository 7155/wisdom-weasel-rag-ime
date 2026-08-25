import { useCallback, useEffect, useLayoutEffect, useRef, useState, type RefObject } from 'react';

/* Vendored clean-room scroll behaviour. See ../ATTRIBUTION.md. */

export interface ScrollAnchor {
  pinned: boolean;
  messageId?: string;
  offsetFromViewportTop?: number;
  fallbackScrollTop?: number;
}

/**
 * Pin-to-latest that a reader can always win. Growth keeps the view at the
 * bottom only while the reader is already there; any scroll, wheel, touch or
 * pointer intent above the fold releases the pin until they come back.
 */
export function usePinnedTranscript(
  scrollRef: RefObject<HTMLElement | null>,
  contentRef: RefObject<HTMLElement | null>,
) {
  const [isPinned, setPinned] = useState(true);
  const [showJumpToBottom, setShowJumpToBottom] = useState(false);
  const pinnedRef = useRef(true);
  const programmatic = useRef(false);

  const updatePinned = useCallback((next: boolean) => {
    pinnedRef.current = next;
    setPinned(next);
  }, []);

  const gapToBottom = useCallback(() => {
    const scroller = scrollRef.current;
    if (!scroller) return 0;
    return Math.max(0, scroller.scrollHeight - scroller.clientHeight - scroller.scrollTop);
  }, [scrollRef]);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = 'auto') => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    updatePinned(true);
    setShowJumpToBottom(false);
    /* Only the reader's explicit jump animates, and only that animation needs
     * the guard below: its own intermediate scroll events would otherwise read
     * as the reader scrolling away. Staying pinned while content arrives is an
     * instant assignment, so it lands in the same frame the content does. */
    if (behavior === 'smooth' && typeof scroller.scrollTo === 'function') {
      programmatic.current = true;
      scroller.scrollTo({ top: scroller.scrollHeight, behavior });
    } else {
      programmatic.current = false;
      scroller.scrollTop = scroller.scrollHeight;
    }
  }, [scrollRef, updatePinned]);

  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    const onScroll = () => {
      const gap = gapToBottom();
      if (gap <= 16) {
        programmatic.current = false;
        updatePinned(true);
      } else if (gap > 24 && !programmatic.current) {
        updatePinned(false);
      }
      setShowJumpToBottom(gap > 48 && !programmatic.current);
    };
    /* Wheel, touch or pointer is the reader taking the scroller back, which
     * ends any animation we started on their behalf. */
    const onIntent = () => {
      programmatic.current = false;
      if (gapToBottom() > 24) updatePinned(false);
    };
    scroller.addEventListener('scroll', onScroll, { passive: true });
    scroller.addEventListener('wheel', onIntent, { passive: true });
    scroller.addEventListener('touchstart', onIntent, { passive: true });
    scroller.addEventListener('pointerdown', onIntent, { passive: true });
    onScroll();
    return () => {
      scroller.removeEventListener('scroll', onScroll);
      scroller.removeEventListener('wheel', onIntent);
      scroller.removeEventListener('touchstart', onIntent);
      scroller.removeEventListener('pointerdown', onIntent);
    };
  }, [gapToBottom, scrollRef, updatePinned]);

  useLayoutEffect(() => {
    const content = contentRef.current;
    if (!content || typeof ResizeObserver !== 'function') return;
    let frame = 0;
    const observer = new ResizeObserver(() => {
      if (!pinnedRef.current) return;
      if (frame) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => scrollToBottom('auto'));
    });
    observer.observe(content);
    return () => {
      observer.disconnect();
      if (frame) cancelAnimationFrame(frame);
    };
  }, [contentRef, scrollToBottom]);

  const captureAnchor = useCallback((): ScrollAnchor => {
    const scroller = scrollRef.current;
    if (!scroller || pinnedRef.current) return { pinned: pinnedRef.current };
    const viewportTop = scroller.getBoundingClientRect().top;
    const rows = [...scroller.querySelectorAll<HTMLElement>('[data-message-id]')];
    const row = rows.find((element) => element.getBoundingClientRect().bottom > viewportTop);
    if (!row?.dataset.messageId) return { pinned: false };
    return {
      pinned: false,
      messageId: row.dataset.messageId,
      offsetFromViewportTop: row.getBoundingClientRect().top - viewportTop,
      fallbackScrollTop: scroller.scrollTop,
    };
  }, [scrollRef]);

  const restoreAnchor = useCallback((anchor: ScrollAnchor) => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    if (anchor.pinned) {
      scrollToBottom('auto');
      return;
    }
    updatePinned(false);
    if (anchor.fallbackScrollTop !== undefined) scroller.scrollTop = anchor.fallbackScrollTop;
    const messageId = anchor.messageId;
    if (!messageId) return;
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const row = scroller.querySelector<HTMLElement>(`[data-message-id="${CSS.escape(messageId)}"]`);
      if (!row) return;
      const viewportTop = scroller.getBoundingClientRect().top;
      const actualOffset = row.getBoundingClientRect().top - viewportTop;
      scroller.scrollTop += actualOffset - (anchor.offsetFromViewportTop ?? 0);
    }));
  }, [scrollRef, scrollToBottom, updatePinned]);

  return {
    isPinned,
    isPinnedRef: pinnedRef,
    showJumpToBottom,
    setPinned: updatePinned,
    scrollToBottom,
    captureAnchor,
    restoreAnchor,
  };
}
