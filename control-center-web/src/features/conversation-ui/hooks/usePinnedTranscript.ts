import { useCallback, useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";

export interface ScrollAnchor {
  pinned: boolean;
  messageId?: string;
  offsetFromViewportTop?: number;
  fallbackScrollTop?: number;
}

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

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "instant") => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    programmatic.current = true;
    updatePinned(true);
    scroller.scrollTo({ top: scroller.scrollHeight, behavior });
    requestAnimationFrame(() => {
      programmatic.current = false;
      setShowJumpToBottom(false);
    });
  }, [scrollRef, updatePinned]);

  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    const onScroll = () => {
      const gap = gapToBottom();
      setShowJumpToBottom(gap > 48);
      if (programmatic.current) return;
      if (gap <= 16) updatePinned(true);
      else if (gap > 24) updatePinned(false);
    };
    const onIntent = () => {
      if (programmatic.current) return;
      if (gapToBottom() > 24) updatePinned(false);
    };
    scroller.addEventListener("scroll", onScroll, { passive: true });
    scroller.addEventListener("wheel", onIntent, { passive: true });
    scroller.addEventListener("touchstart", onIntent, { passive: true });
    scroller.addEventListener("pointerdown", onIntent, { passive: true });
    onScroll();
    return () => {
      scroller.removeEventListener("scroll", onScroll);
      scroller.removeEventListener("wheel", onIntent);
      scroller.removeEventListener("touchstart", onIntent);
      scroller.removeEventListener("pointerdown", onIntent);
    };
  }, [gapToBottom, scrollRef, updatePinned]);

  useLayoutEffect(() => {
    const content = contentRef.current;
    if (!content) return;
    let frame = 0;
    const observer = new ResizeObserver(() => {
      if (!pinnedRef.current) return;
      if (frame) cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => scrollToBottom("instant"));
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
    const rows = Array.from(scroller.querySelectorAll<HTMLElement>("[data-message-id]"));
    const row = rows.find(element => element.getBoundingClientRect().bottom > viewportTop);
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
      scrollToBottom("instant");
      return;
    }
    updatePinned(false);
    if (anchor.fallbackScrollTop !== undefined) scroller.scrollTop = anchor.fallbackScrollTop;
    if (!anchor.messageId) return;
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const row = scroller.querySelector<HTMLElement>(`[data-message-id="${CSS.escape(anchor.messageId!)}"]`);
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
