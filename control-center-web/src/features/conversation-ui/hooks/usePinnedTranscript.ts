import { useCallback, useEffect, useLayoutEffect, useRef, useState, type RefObject } from 'react';
import {
  captureTranscriptAnchor,
  resolveAnchorScrollTop,
  type TranscriptAnchor,
  type TranscriptRowGeometry,
} from '@/features/agent/timeline/chat-ui-kit';

/* Vendored clean-room scroll behaviour. See ../ATTRIBUTION.md. */

export interface ScrollAnchor {
  pinned: boolean;
  /** Row anchor from the shared chat-ui-kit core; absent when pinned. */
  row?: TranscriptAnchor;
}

function messageRowGeometry(scroller: HTMLElement): TranscriptRowGeometry[] {
  const scrollerTop = scroller.getBoundingClientRect().top - scroller.scrollTop;
  return [...scroller.querySelectorAll<HTMLElement>('[data-message-id]')]
    .flatMap((element, index) => {
      const key = element.dataset.messageId;
      if (!key) return [];
      const box = element.getBoundingClientRect();
      return [{ key, top: box.top - scrollerTop, height: box.height, index }];
    });
}

/**
 * Pin-to-latest that a reader can always win. Growth keeps the view at the
 * bottom only while the reader is already there; any scroll, wheel, touch or
 * pointer intent above the fold releases the pin until they come back.
 */
export function usePinnedTranscript(
  scrollRef: RefObject<HTMLElement | null>,
  contentRef: RefObject<HTMLElement | null>,
  conversationId = '',
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
    const row = captureTranscriptAnchor({
      conversationId,
      rows: messageRowGeometry(scroller),
      scrollTop: scroller.scrollTop,
    });
    return row ? { pinned: false, row } : { pinned: false };
  }, [conversationId, scrollRef]);

  const restoreAnchor = useCallback((anchor: ScrollAnchor) => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    if (anchor.pinned) {
      scrollToBottom('auto');
      return;
    }
    updatePinned(false);
    const row = anchor.row;
    if (!row) return;
    const apply = () => {
      /* Resolved against live geometry: an anchored message that was retried,
         forked or pruned away restores to the row that took its position
         rather than to a pixel offset that no longer means anything. */
      const restored = resolveAnchorScrollTop({
        anchor: row,
        rows: messageRowGeometry(scroller),
        maxScrollTop: Math.max(0, scroller.scrollHeight - scroller.clientHeight),
      });
      scroller.scrollTop = restored.scrollTop;
    };
    apply();
    // Rows measured before the transcript settles are still estimates.
    requestAnimationFrame(() => requestAnimationFrame(apply));
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
