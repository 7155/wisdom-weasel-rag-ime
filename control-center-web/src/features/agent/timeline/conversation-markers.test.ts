import { describe, expect, it } from 'vitest';

import {
  MAX_CONVERSATION_MARKERS,
  conversationMarkerIndexes,
} from './conversation-markers';

describe('conversationMarkerIndexes', () => {
  it('keeps a 1,000-turn navigator bounded while retaining useful landmarks', () => {
    const indexes = conversationMarkerIndexes(1_000, 742);

    expect(indexes).toHaveLength(MAX_CONVERSATION_MARKERS);
    expect(indexes[0]).toBe(0);
    expect(indexes.at(-1)).toBe(999);
    expect(indexes).toContain(742);
    expect(new Set(indexes).size).toBe(indexes.length);
    expect(indexes).toEqual([...indexes].sort((left, right) => left - right));
  });

  it('keeps every turn available when the conversation is already small', () => {
    expect(conversationMarkerIndexes(5, 3)).toEqual([0, 1, 2, 3, 4]);
  });
});
