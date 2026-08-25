/* Vendored from paw-agent-chat-ui-kit `src/core/interaction/messageAnchor.ts`,
 * extended with the index-based restore a virtualizer needs.
 * See ./ATTRIBUTION.md. */

export interface TranscriptRowGeometry {
  /** Stable row identity — a turn id, not a list position. */
  readonly key: string;
  /** Row top in scroll-content coordinates. */
  readonly top: number;
  readonly height: number;
  /**
   * Position in the whole transcript. A virtualizer only hands out geometry
   * for the rendered window, so the position within `rows` is not the position
   * the anchor has to remember.
   */
  readonly index?: number;
}

export interface TranscriptAnchor {
  readonly conversationId: string;
  readonly rowKey: string;
  readonly rowIndex: number;
  /** Where the anchored row sat relative to the viewport top, in px. */
  readonly offsetFromViewportTopPx: number;
  /** Geometry fallback for a transcript whose rows all changed identity. */
  readonly fallbackScrollTop: number;
}

/**
 * Remember the topmost row the reader can actually see, plus how far it had
 * already scrolled past the viewport top. A pixel offset alone is meaningless
 * once streaming or a re-measure changes the height of anything above it.
 */
export function captureTranscriptAnchor(input: {
  conversationId: string;
  rows: readonly TranscriptRowGeometry[];
  scrollTop: number;
  viewportTopInset?: number;
}): TranscriptAnchor | null {
  const viewportLine = input.scrollTop + (input.viewportTopInset ?? 0);
  const position = input.rows.findIndex(
    (candidate) => candidate.top + candidate.height > viewportLine,
  );
  if (position < 0) return null;
  const row = input.rows[position]!;
  return {
    conversationId: input.conversationId,
    rowKey: row.key,
    rowIndex: row.index ?? position,
    offsetFromViewportTopPx: row.top - input.scrollTop,
    fallbackScrollTop: input.scrollTop,
  };
}

export type AnchorRestoreSource = 'row' | 'nearest-row' | 'fallback';

export interface AnchorScrollRestore {
  readonly scrollTop: number;
  readonly source: AnchorRestoreSource;
  readonly rowKey: string | null;
}

/** Restore for a scroller whose row geometry the caller can measure directly. */
export function resolveAnchorScrollTop(input: {
  anchor: TranscriptAnchor;
  rows: readonly TranscriptRowGeometry[];
  maxScrollTop: number;
}): AnchorScrollRestore {
  const exact = input.rows.find(
    (candidate) => candidate.key === input.anchor.rowKey,
  );
  const nearest =
    exact
    ?? (input.rows.length > 0
      ? input.rows[
          Math.max(0, Math.min(input.anchor.rowIndex, input.rows.length - 1))
        ]
      : undefined);
  const raw = nearest
    ? nearest.top - input.anchor.offsetFromViewportTopPx
    : input.anchor.fallbackScrollTop;
  return {
    scrollTop: Math.max(0, Math.min(input.maxScrollTop, raw)),
    source: exact ? 'row' : nearest ? 'nearest-row' : 'fallback',
    rowKey: nearest?.key ?? null,
  };
}

export interface AnchorRowRestore {
  readonly index: number;
  /** Pixels the anchored row had already scrolled above the viewport top. */
  readonly offsetPx: number;
  readonly source: AnchorRestoreSource;
}

/**
 * Restore for a virtualizer that owns geometry: the caller supplies the
 * ordered row keys and receives an index it can scroll to. Falling back to the
 * remembered index rather than to the bottom is what keeps a reader roughly in
 * place when the anchored turn was edited, retried or forked away.
 */
export function resolveAnchorRowIndex(input: {
  anchor: TranscriptAnchor;
  rowKeys: readonly string[];
}): AnchorRowRestore | null {
  if (input.rowKeys.length === 0) return null;
  const exact = input.rowKeys.indexOf(input.anchor.rowKey);
  const index =
    exact >= 0
      ? exact
      : Math.max(0, Math.min(input.anchor.rowIndex, input.rowKeys.length - 1));
  return {
    index,
    // A row already scrolled past the viewport top has a negative offset;
    // the restore has to re-apply that, not clamp it away.
    offsetPx: -input.anchor.offsetFromViewportTopPx,
    source: exact >= 0 ? 'row' : 'nearest-row',
  };
}
