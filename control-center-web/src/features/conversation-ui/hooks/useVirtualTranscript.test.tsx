import { cleanup, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { useVirtualTranscript } from './useVirtualTranscript';

afterEach(cleanup);

describe('useVirtualTranscript cold-open window', () => {
  it('mounts the remembered full-transcript index before a scroller can be measured', () => {
    const items = Array.from({ length: 100 }, (_value, index) => ({
      id: `message-${index}`,
    }));
    const scrollRef = { current: null };
    const { result } = renderHook(() => useVirtualTranscript({
      items,
      getKey: (item) => item.id,
      estimateSize: () => 100,
      scrollRef,
      initialScrollKey: 'room:remembered',
      initialAnchor: {
        key: 'message-50',
        index: 50,
        offsetFromViewportTopPx: 0,
      },
    }));

    const visibleIndexes = result.current.virtualRows.map((row) => row.index);
    expect(visibleIndexes).toContain(50);
    expect(visibleIndexes[0]).toBeGreaterThan(0);
    expect(visibleIndexes.at(-1)).toBeLessThan(99);
  });
});
