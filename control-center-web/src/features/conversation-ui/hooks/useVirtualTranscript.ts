import { useCallback, useLayoutEffect, useMemo, useRef, useState, type RefObject } from 'react';

/* Vendored clean-room virtualizer. See ../ATTRIBUTION.md. */

export interface VirtualRow {
  key: string;
  index: number;
  start: number;
  size: number;
}

export interface UseVirtualTranscriptOptions<T> {
  items: readonly T[];
  getKey(item: T, index: number): string;
  estimateSize(item: T, index: number): number;
  scrollRef: RefObject<HTMLElement | null>;
  overscanTop?: number;
  overscanBottom?: number;
}

/**
 * Small variable-height virtualizer designed for chat timelines.
 * It keeps measured row sizes by stable key and uses asymmetric overscan:
 * substantially more history above, because readers scroll upward.
 */
export function useVirtualTranscript<T>({
  items,
  getKey,
  estimateSize,
  scrollRef,
  overscanTop = 1_400,
  overscanBottom = 600,
}: UseVirtualTranscriptOptions<T>) {
  const sizeCache = useRef(new Map<string, number>());
  const elementToKey = useRef(new WeakMap<Element, string>());
  const observerRef = useRef<ResizeObserver | null>(null);
  const layoutRef = useRef<{ rows: VirtualRow[]; totalSize: number }>({ rows: [], totalSize: 0 });
  const [measurementEpoch, setMeasurementEpoch] = useState(0);
  const [viewport, setViewport] = useState({ top: 0, height: 0 });

  const layout = useMemo(() => {
    const rows: VirtualRow[] = [];
    let start = 0;
    items.forEach((item, index) => {
      const key = getKey(item, index);
      const size = sizeCache.current.get(key) ?? estimateSize(item, index);
      rows.push({ key, index, start, size });
      start += size;
    });
    return { rows, totalSize: start };
  // measurementEpoch intentionally invalidates cached geometry when ResizeObserver reports a row size.
  }, [items, getKey, estimateSize, measurementEpoch]);
  layoutRef.current = layout;

  useLayoutEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    let frame = 0;
    const read = () => {
      frame = 0;
      setViewport((previous) => {
        const next = { top: scroller.scrollTop, height: scroller.clientHeight };
        return previous.top === next.top && previous.height === next.height ? previous : next;
      });
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(read);
    };
    read();
    scroller.addEventListener('scroll', schedule, { passive: true });
    const resize = typeof ResizeObserver === 'function' ? new ResizeObserver(schedule) : null;
    resize?.observe(scroller);
    return () => {
      scroller.removeEventListener('scroll', schedule);
      resize?.disconnect();
      if (frame) cancelAnimationFrame(frame);
    };
  }, [scrollRef]);

  useLayoutEffect(() => {
    if (typeof ResizeObserver !== 'function') return;
    observerRef.current = new ResizeObserver((entries) => {
      let changed = false;
      let scrollAdjustment = 0;
      const scroller = scrollRef.current;
      const geometry = layoutRef.current;
      for (const entry of entries) {
        const key = elementToKey.current.get(entry.target);
        if (!key) continue;
        const next = Math.max(1, Math.ceil(entry.borderBoxSize?.[0]?.blockSize ?? entry.contentRect.height));
        const row = geometry.rows.find((candidate) => candidate.key === key);
        const previous = sizeCache.current.get(key) ?? row?.size;
        if (previous === next) continue;
        // If a fully-above row changes height, compensate scrollTop by the same
        // delta so the first visible content keeps its screen position.
        if (scroller && row && previous !== undefined && row.start + previous <= scroller.scrollTop) {
          scrollAdjustment += next - previous;
        }
        sizeCache.current.set(key, next);
        changed = true;
      }
      if (scrollAdjustment && scroller) scroller.scrollTop += scrollAdjustment;
      if (changed) setMeasurementEpoch((epoch) => epoch + 1);
    });
    return () => observerRef.current?.disconnect();
  }, [scrollRef]);

  const measureElement = useCallback((key: string) => (element: HTMLElement | null) => {
    if (!element) return;
    elementToKey.current.set(element, key);
    observerRef.current?.observe(element);
  }, []);

  const virtualRows = useMemo(() => {
    const rows = layout.rows;
    if (rows.length === 0) return [];
    /* No measurable viewport means no honest window to cull against — a
     * headless or not-yet-laid-out scroller renders the whole transcript
     * rather than an arbitrary slice of it. */
    if (viewport.height <= 0) return rows;

    const from = Math.max(0, viewport.top - overscanTop);
    const to = viewport.top + viewport.height + overscanBottom;
    let low = 0;
    let high = rows.length - 1;
    let startIndex = rows.length - 1;
    while (low <= high) {
      const mid = (low + high) >> 1;
      const row = rows[mid]!;
      if (row.start + row.size < from) low = mid + 1;
      else {
        startIndex = mid;
        high = mid - 1;
      }
    }

    const visible: VirtualRow[] = [];
    for (let index = startIndex; index < rows.length; index += 1) {
      const row = rows[index]!;
      if (row.start > to) break;
      visible.push(row);
    }
    return visible;
  }, [layout.rows, overscanBottom, overscanTop, viewport]);

  const scrollToIndex = useCallback((index: number, align: 'start' | 'center' | 'end' = 'center') => {
    const scroller = scrollRef.current;
    const row = layout.rows[index];
    if (!scroller || !row) return;
    const top = align === 'start'
      ? row.start
      : align === 'end'
        ? row.start + row.size - scroller.clientHeight
        : row.start + row.size / 2 - scroller.clientHeight / 2;
    scroller.scrollTop = Math.max(0, top);
  }, [layout.rows, scrollRef]);

  return {
    totalSize: layout.totalSize,
    virtualRows,
    measureElement,
    scrollToIndex,
    sizeCache: sizeCache.current,
  };
}
