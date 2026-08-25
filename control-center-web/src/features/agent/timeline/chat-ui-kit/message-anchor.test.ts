import { describe, expect, it } from 'vitest';
import {
  captureTranscriptAnchor,
  resolveAnchorRowIndex,
  resolveAnchorScrollTop,
  type TranscriptRowGeometry,
} from './index';

function rows(...heights: readonly number[]): TranscriptRowGeometry[] {
  let top = 0;
  return heights.map((height, index) => {
    const row = { key: `turn-${index}`, top, height, index };
    top += height;
    return row;
  });
}

describe('transcript row anchor', () => {
  it('anchors the topmost row the reader can see, with how far it scrolled past', () => {
    const anchor = captureTranscriptAnchor({
      conversationId: 'session-a',
      rows: rows(100, 200, 150),
      scrollTop: 250,
    });

    expect(anchor).toEqual({
      conversationId: 'session-a',
      rowKey: 'turn-1',
      rowIndex: 1,
      offsetFromViewportTopPx: -150,
      fallbackScrollTop: 250,
    });
  });

  it('remembers the whole-transcript position, not the position in the rendered window', () => {
    // A virtualizer only hands out geometry for its window.
    const windowed: TranscriptRowGeometry[] = [
      { key: 'turn-40', top: 4_000, height: 100, index: 40 },
      { key: 'turn-41', top: 4_100, height: 100, index: 41 },
    ];
    const anchor = captureTranscriptAnchor({
      conversationId: 'session-a',
      rows: windowed,
      scrollTop: 4_050,
    });

    expect(anchor?.rowKey).toBe('turn-40');
    expect(anchor?.rowIndex).toBe(40);
  });

  it('returns nothing when every row sits above the viewport', () => {
    expect(captureTranscriptAnchor({
      conversationId: 'session-a',
      rows: rows(100),
      scrollTop: 500,
    })).toBeNull();
  });

  it('restores an unchanged row exactly, even after everything above it grew', () => {
    const anchor = captureTranscriptAnchor({
      conversationId: 'session-a',
      rows: rows(100, 200, 150),
      scrollTop: 250,
    })!;
    // Streaming re-measured the first turn from 100px to 600px.
    const restored = resolveAnchorScrollTop({
      anchor,
      rows: rows(600, 200, 150),
      maxScrollTop: 10_000,
    });

    expect(restored.source).toBe('row');
    expect(restored.rowKey).toBe('turn-1');
    // The anchored row is back under the same pixel of the viewport, which the
    // remembered scrollTop of 250 would not have achieved.
    expect(restored.scrollTop).toBe(750);
  });

  it('falls back to the row that took the position when the anchor was pruned', () => {
    const anchor = captureTranscriptAnchor({
      conversationId: 'session-a',
      rows: rows(100, 200, 150),
      scrollTop: 250,
    })!;
    const survivors: TranscriptRowGeometry[] = [
      { key: 'kept-0', top: 0, height: 100, index: 0 },
      { key: 'retried-1', top: 100, height: 300, index: 1 },
    ];
    const restored = resolveAnchorScrollTop({
      anchor,
      rows: survivors,
      maxScrollTop: 10_000,
    });

    // A raw pixel offset would have been meaningless here; the row that took
    // the position is the honest answer.
    expect(restored.source).toBe('nearest-row');
    expect(restored.rowKey).toBe('retried-1');
    expect(restored.scrollTop).toBe(250);
  });

  it('clamps a restore to the scrollable range', () => {
    const anchor = captureTranscriptAnchor({
      conversationId: 'session-a',
      rows: rows(100, 200),
      scrollTop: 150,
    })!;
    expect(resolveAnchorScrollTop({
      anchor,
      rows: rows(100, 200),
      maxScrollTop: 40,
    }).scrollTop).toBe(40);
  });

  it('hands a virtualizer an index and the offset the row had already scrolled', () => {
    const anchor = captureTranscriptAnchor({
      conversationId: 'session-a',
      rows: rows(100, 200, 150),
      scrollTop: 250,
    })!;
    const restore = resolveAnchorRowIndex({
      anchor,
      rowKeys: ['turn-0', 'turn-1', 'turn-2', 'turn-3'],
    });

    expect(restore).toEqual({ index: 1, offsetPx: 150, source: 'row' });
  });

  it('keeps a virtualizer restore in range when the anchored turn is gone', () => {
    const anchor = captureTranscriptAnchor({
      conversationId: 'session-a',
      rows: rows(100, 200, 150),
      scrollTop: 250,
    })!;

    expect(resolveAnchorRowIndex({ anchor, rowKeys: ['only-turn'] }))
      .toEqual({ index: 0, offsetPx: 150, source: 'nearest-row' });
    expect(resolveAnchorRowIndex({ anchor, rowKeys: [] })).toBeNull();
  });
});
