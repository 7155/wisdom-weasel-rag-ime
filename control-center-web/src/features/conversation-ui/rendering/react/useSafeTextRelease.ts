import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import {
  advanceToSafeBoundary,
  computeReleaseCeiling,
} from "../core/safeInlineBoundary";

const useBrowserLayoutEffect =
  typeof window === "undefined" ? useEffect : useLayoutEffect;

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function commonPrefixLength(
  left: string,
  right: string,
  maximum = Math.min(left.length, right.length),
): number {
  let index = 0;
  const upper = Math.min(maximum, left.length, right.length);
  while (index < upper && left.charCodeAt(index) === right.charCodeAt(index)) {
    index += 1;
  }
  // Avoid splitting a surrogate pair.
  if (
    index > 0 &&
    index < right.length &&
    (right.charCodeAt(index) & 0xfc00) === 0xdc00
  ) {
    index -= 1;
  }
  return index;
}

export interface SafeTextReleaseOptions {
  readonly enabled: boolean;
  readonly stepChars?: number | undefined;
  readonly minimumIntervalMs?: number | undefined;
  readonly maximumIntervalMs?: number | undefined;
  readonly backlogBudgetMs?: number | undefined;
  readonly maximumHoldBackChars?: number | undefined;
}

/**
 * Releases streaming text at Markdown-safe inline boundaries. The rAF loop is
 * a display scheduler, not a replacement for transport/event batching.
 */
export function useSafeTextRelease(
  text: string,
  options: SafeTextReleaseOptions,
): string {
  const {
    enabled,
    stepChars = 40,
    minimumIntervalMs = 25,
    maximumIntervalMs = 150,
    backlogBudgetMs = 12_000,
    maximumHoldBackChars = 600,
  } = options;

  const [visibleEnd, setVisibleEnd] = useState(enabled ? 0 : text.length);
  const visibleEndRef = useRef(visibleEnd);
  const sourceRef = useRef(text);
  const ceilingRef = useRef(
    enabled ? computeReleaseCeiling(text, maximumHoldBackChars) : text.length,
  );

  useBrowserLayoutEffect(() => {
    const previousText = sourceRef.current;
    const previousVisibleEnd = visibleEndRef.current;
    const ceiling = enabled
      ? computeReleaseCeiling(text, maximumHoldBackChars)
      : text.length;

    let nextVisibleEnd = previousVisibleEnd;
    if (!enabled) {
      nextVisibleEnd = text.length;
    } else if (!text.startsWith(previousText.slice(0, previousVisibleEnd))) {
      nextVisibleEnd = commonPrefixLength(
        previousText,
        text,
        previousVisibleEnd,
      );
    }

    nextVisibleEnd = Math.min(nextVisibleEnd, ceiling, text.length);
    if (enabled && nextVisibleEnd === 0 && ceiling > 0) {
      nextVisibleEnd = advanceToSafeBoundary(
        text,
        0,
        ceiling,
        Math.min(120, Math.max(stepChars, ceiling)),
      );
    }
    sourceRef.current = text;
    ceilingRef.current = ceiling;
    visibleEndRef.current = nextVisibleEnd;
    if (nextVisibleEnd !== visibleEnd) setVisibleEnd(nextVisibleEnd);
  }, [enabled, maximumHoldBackChars, stepChars, text, visibleEnd]);

  useEffect(() => {
    if (!enabled || typeof window === "undefined") return undefined;

    let frame = 0;
    let lastAdvanceAt = performance.now();

    const tick = (now: number): void => {
      frame = window.requestAnimationFrame(tick);
      const source = sourceRef.current;
      const ceiling = ceilingRef.current;
      const current = visibleEndRef.current;
      const backlog = ceiling - current;
      if (backlog <= 0) {
        lastAdvanceAt = now;
        return;
      }

      const interval = clamp(
        backlogBudgetMs / backlog,
        minimumIntervalMs,
        maximumIntervalMs,
      );
      if (now - lastAdvanceAt < interval) return;
      lastAdvanceAt = now;

      const next = advanceToSafeBoundary(
        source,
        current,
        ceiling,
        stepChars,
      );
      if (next > current) {
        visibleEndRef.current = next;
        setVisibleEnd(next);
      }
    };

    const flushWhenVisible = (): void => {
      if (document.hidden) return;
      const ceiling = ceilingRef.current;
      if (ceiling > visibleEndRef.current) {
        visibleEndRef.current = ceiling;
        setVisibleEnd(ceiling);
      }
    };

    frame = window.requestAnimationFrame(tick);
    document.addEventListener("visibilitychange", flushWhenVisible);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("visibilitychange", flushWhenVisible);
    };
  }, [
    backlogBudgetMs,
    enabled,
    maximumIntervalMs,
    minimumIntervalMs,
    stepChars,
  ]);

  return enabled ? text.slice(0, Math.min(visibleEnd, text.length)) : text;
}
