import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import {
  advanceToSafeBoundary,
  computeReleaseCeiling,
  remapVisibleOffsetAfterEdit,
} from "./safeInlineBoundary";

const useBrowserLayoutEffect =
  typeof window === "undefined" ? useEffect : useLayoutEffect;

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

export interface SafeTextReleaseOptions {
  readonly enabled: boolean;
  readonly stepChars?: number | undefined;
  readonly minimumIntervalMs?: number | undefined;
  readonly maximumIntervalMs?: number | undefined;
  readonly backlogBudgetMs?: number | undefined;
  readonly maximumHoldBackChars?: number | undefined;
}

/** The reveal is a courtesy animation; anyone who asked for reduced motion
 * gets delivered text the moment the transport has it (PAW adaptation). */
function revealMotionDisabled(): boolean {
  if (typeof window === 'undefined' || typeof document === 'undefined') return true;
  if (document.documentElement.getAttribute('data-reduce-motion') === 'true') return true;
  return typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * Releases streaming text at Markdown-safe inline boundaries. The rAF loop is
 * a display scheduler, not a replacement for transport/event batching.
 *
 * PAW adaptation: mounting starts fully flushed rather than at zero, so a
 * Virtuoso item remount or a restored mid-stream snapshot never replays the
 * whole reveal; only text appended after mount animates. A hidden document
 * and reduced motion both flush instantly.
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

  const [visibleEnd, setVisibleEnd] = useState(text.length);
  const visibleEndRef = useRef(visibleEnd);
  const sourceRef = useRef(text);
  const ceilingRef = useRef(text.length);

  useBrowserLayoutEffect(() => {
    const previousText = sourceRef.current;
    const previousVisibleEnd = visibleEndRef.current;
    const ceiling = enabled && !revealMotionDisabled()
      ? computeReleaseCeiling(text, maximumHoldBackChars)
      : text.length;

    let nextVisibleEnd = previousVisibleEnd;
    if (!enabled || revealMotionDisabled()) {
      nextVisibleEnd = text.length;
    } else if (!text.startsWith(previousText.slice(0, previousVisibleEnd))) {
      nextVisibleEnd = remapVisibleOffsetAfterEdit(
        previousText,
        text,
        previousVisibleEnd,
      );
    }

    nextVisibleEnd = Math.min(nextVisibleEnd, ceiling, text.length);
    sourceRef.current = text;
    ceilingRef.current = ceiling;
    visibleEndRef.current = nextVisibleEnd;
    if (nextVisibleEnd !== visibleEnd) setVisibleEnd(nextVisibleEnd);
  }, [enabled, maximumHoldBackChars, text, visibleEnd]);

  useEffect(() => {
    if (!enabled || typeof window === "undefined") return undefined;

    let frame = 0;
    // requestAnimationFrame owns the reveal clock. Its callback timestamp is
    // not guaranteed to share a time origin with performance.now() in every
    // host (notably embedded WebViews and test DOMs), so mixing the two can
    // leave appended text waiting forever behind a negative elapsed value.
    let lastAdvanceAt: number | undefined;

    const tick = (now: number): void => {
      frame = window.requestAnimationFrame(tick);
      const source = sourceRef.current;
      const ceiling = ceilingRef.current;
      const current = visibleEndRef.current;
      const backlog = ceiling - current;
      // Compare timestamps from the same rAF clock. Hosts can expose a
      // different time origin through performance.now().
      if (lastAdvanceAt === undefined) lastAdvanceAt = now;
      if (backlog <= 0) {
        lastAdvanceAt = now;
        return;
      }

      if (revealMotionDisabled()) {
        visibleEndRef.current = ceiling;
        setVisibleEnd(ceiling);
        return;
      }

      const interval = clamp(
        backlogBudgetMs / backlog,
        minimumIntervalMs,
        maximumIntervalMs,
      );
      if (lastAdvanceAt === undefined) {
        lastAdvanceAt = now;
        return;
      }
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

    const flushOnVisibilityChange = (): void => {
      // A hidden document gets no animation frames; parking the full ceiling
      // keeps the transcript truthful when the user returns.
      const ceiling = ceilingRef.current;
      if (ceiling > visibleEndRef.current) {
        visibleEndRef.current = ceiling;
        setVisibleEnd(ceiling);
      }
    };

    frame = window.requestAnimationFrame(tick);
    document.addEventListener("visibilitychange", flushOnVisibilityChange);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("visibilitychange", flushOnVisibilityChange);
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
