const BARE_LIST_MARKER = /^[ \t]*(?:[-*+]|\d{1,9}[.)]?)$/;
const BARE_HEADING_MARKER = /^ {0,3}#{1,6}[ \t]*$/;
const WORD_CHAR = /[\w-]/;
/** CJK ideographs/kana are complete display units; the "do not show half a
 * word" space-seek below is meaningless for them (PAW adaptation). */
const CJK_TAIL = /[\u2e80-\u303f\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\uff00-\uffef]/;

function avoidBrokenSurrogate(text: string, offset: number): number {
  if (offset <= 0 || offset >= text.length) return offset;
  const code = text.charCodeAt(offset);
  return (code & 0xfc00) === 0xdc00 ? offset - 1 : offset;
}

/** Return a conservative display boundary at or before limit. */
export function findSafeInlineBoundary(
  text: string,
  limit = text.length,
): number {
  if (limit <= 0) return 0;
  const boundedLimit = Math.min(limit, text.length);
  const lineStart = text.lastIndexOf("\n", boundedLimit - 1) + 1;
  const line = text.slice(lineStart, boundedLimit);

  if (BARE_LIST_MARKER.test(line)) return lineStart;

  let openBacktickAt = -1;
  let backtickRunLength = 0;
  let unresolvedBracketAt = -1;
  const openEmphasis = new Map<string, number>();
  let lastClosedBoundary = lineStart;
  let index = lineStart;

  while (index < boundedLimit) {
    const char = text[index] ?? "";

    if (char === "`") {
      let run = 1;
      while (index + run < boundedLimit && text[index + run] === "`") {
        run += 1;
      }
      if (openBacktickAt < 0) {
        openBacktickAt = index;
        backtickRunLength = run;
      } else if (run === backtickRunLength) {
        openBacktickAt = -1;
        lastClosedBoundary = index + run;
      }
      index += run;
      continue;
    }

    if (openBacktickAt >= 0) {
      index += 1;
      continue;
    }

    if (
      char === ":" &&
      unresolvedBracketAt < 0 &&
      text.startsWith("ant", index + 1)
    ) {
      let probe = index + 4;
      while (probe < text.length && WORD_CHAR.test(text[probe] ?? "")) {
        probe += 1;
      }
      if (text[probe] === "[") unresolvedBracketAt = index;
    }

    if (char === "[" || (char === "!" && text[index + 1] === "[")) {
      if (unresolvedBracketAt < 0) unresolvedBracketAt = index;
      index += char === "!" ? 2 : 1;
      continue;
    }

    if (char === "]" && unresolvedBracketAt >= 0) {
      if (text[index + 1] === "(") {
        const close = text.indexOf(")", index + 2);
        if (close < 0 || close >= boundedLimit) break;
        index = close + 1;
      } else if (text[index + 1] === "{") {
        const close = text.indexOf("}", index + 2);
        if (close < 0 || close >= boundedLimit) break;
        index = close + 1;
      } else {
        index += 1;
      }
      unresolvedBracketAt = -1;
      lastClosedBoundary = index;
      continue;
    }

    if (char === "*" || char === "_" || char === "~") {
      let run = 1;
      while (index + run < boundedLimit && text[index + run] === char) {
        run += 1;
      }
      const before = index > lineStart ? text[index - 1] ?? "" : "";
      const after = index + run < boundedLimit ? text[index + run] ?? "" : "";
      const canOpen = after.length > 0 && !/\s/.test(after);
      const canClose = before.length > 0 && !/\s/.test(before);
      const keys: string[] = [];
      if (run >= 2) keys.push(char + char);
      if (char !== "~" && run % 2 === 1) keys.push(char);
      for (const key of keys) {
        if (openEmphasis.has(key)) {
          if (canClose) {
            openEmphasis.delete(key);
            lastClosedBoundary = index + run;
          }
        } else if (canOpen) {
          openEmphasis.set(key, index);
        }
      }
      index += run;
      continue;
    }

    index += 1;
  }

  let boundary = boundedLimit;
  if (openBacktickAt >= 0) boundary = Math.min(boundary, openBacktickAt);
  if (unresolvedBracketAt >= 0) {
    boundary = Math.min(boundary, unresolvedBracketAt);
  }
  for (const opener of openEmphasis.values()) {
    boundary = Math.min(boundary, opener);
  }

  if (
    boundary === boundedLimit &&
    boundary > Math.max(lineStart, lastClosedBoundary) &&
    text[boundary - 1] !== " " &&
    text[boundary - 1] !== "\t"
  ) {
    const space = text.lastIndexOf(" ", boundary - 1);
    if (
      space >= Math.max(lineStart, lastClosedBoundary) &&
      boundary - space <= 24 &&
      !CJK_TAIL.test(text.slice(space + 1, boundary))
    ) {
      boundary = space + 1;
    }
  }

  if (boundary > lineStart && BARE_HEADING_MARKER.test(text.slice(lineStart, boundary))) {
    boundary = lineStart;
  }

  return avoidBrokenSurrogate(text, boundary);
}

/**
 * Do not let hold-back grow without bound. A very long unresolved construct is
 * eventually shown as plain/incomplete text rather than freezing the UI.
 */
export function computeReleaseCeiling(
  text: string,
  maxHoldBackChars = 600,
): number {
  const safe = findSafeInlineBoundary(text);
  return avoidBrokenSurrogate(
    text,
    Math.max(safe, text.length - maxHoldBackChars),
  );
}

/**
 * Advance the reveal by at least stepChars, and by a quarter of the backlog
 * when the transport is further ahead than that. A fixed step turns a fast
 * burst into a reveal that visibly trails the delivered answer; scaling the
 * step to the backlog keeps the pacing a courtesy rather than a throttle.
 */
export function advanceToSafeBoundary(
  text: string,
  current: number,
  ceiling: number,
  stepChars = 40,
): number {
  if (current >= ceiling) return ceiling;
  const step = Math.max(stepChars, Math.ceil((ceiling - current) / 4));
  let probe = Math.min(current + step, ceiling);
  let next = findSafeInlineBoundary(text, probe);
  while (next <= current && probe < ceiling) {
    probe = Math.min(probe + stepChars, ceiling);
    next = findSafeInlineBoundary(text, probe);
  }
  return avoidBrokenSurrogate(text, next > current ? next : ceiling);
}

/**
 * Map the visible offset across a source replacement (retry, edit, rewrite).
 *
 * The reveal is append-only, so any non-prefix change previously collapsed the
 * visible window back to the common prefix and replayed everything after it.
 * When the replacement only rewrote a leading region — the common case for an
 * edit that regenerates the same answer — the reader's position is preserved
 * by measuring from the end instead, and only a genuine divergence falls back
 * to the prefix.
 */
export function remapVisibleOffsetAfterEdit(
  previousText: string,
  nextText: string,
  previousOffset: number,
): number {
  let prefix = 0;
  const prefixLimit = Math.min(
    previousText.length,
    nextText.length,
    previousOffset,
  );
  while (prefix < prefixLimit && previousText[prefix] === nextText[prefix]) {
    prefix += 1;
  }
  if (prefix >= previousOffset) return previousOffset;

  let suffix = 0;
  const suffixLimit = Math.min(previousText.length, nextText.length) - prefix;
  while (
    suffix < suffixLimit
    && previousText[previousText.length - 1 - suffix]
      === nextText[nextText.length - 1 - suffix]
  ) {
    suffix += 1;
  }
  const mapped = previousOffset >= previousText.length - suffix
    ? nextText.length - (previousText.length - previousOffset)
    : prefix;
  return avoidBrokenSurrogate(
    nextText,
    Math.max(0, Math.min(mapped, nextText.length)),
  );
}
