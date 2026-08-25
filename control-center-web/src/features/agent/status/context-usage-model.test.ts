import { describe, expect, it } from 'vitest';
import type { ContextXraySnapshot } from './ContextXrayPanel';
import {
  buildContextUsageView,
  formatContextTokenCount,
} from './context-usage-model';

describe('context usage model', () => {
  it('builds a Cursor-style segmented view from telemetry and xray layers', () => {
    const snapshot: ContextXraySnapshot = {
      available: true,
      layers: [
        layer('system', 'System prompt', 1_700),
        layer('tools', 'Tools', 11_100),
        layer('project-context', 'Rules', 4_200),
        layer('skills', 'Skills', 433),
        layer('lifecycle-hook', 'MCP', 2_500),
        layer('role-book', 'Subagents', 945),
        layer('history', 'Summarized', 2_700),
        layer('timeline', 'Conversation', 109_200),
      ],
      contextTokens: 132_778,
      contextWindow: 200_000,
      cacheHitPercent: null,
      compaction: { count: 0, status: '', tokensBefore: null, tokensAfter: null },
      providerStatus: 200,
      providerCaptured: true,
      updatedAtMs: 1,
    };

    const view = buildContextUsageView({
      telemetry: { tokens: 132_778, contextWindow: 200_000, percent: 66.4 },
      snapshot,
    });

    expect(view.available).toBe(true);
    expect(view.percent).toBeCloseTo(66.389, 2);
    expect(view.segments.map((segment) => segment.id)).toEqual([
      'system',
      'tools',
      'rules',
      'skills',
      'mcp',
      'subagents',
      'summarized',
      'conversation',
    ]);
    expect(view.segments.find((segment) => segment.id === 'conversation')?.tokens).toBe(109_200);
    expect(formatContextTokenCount(132_778)).toBe('132.8K');
    expect(formatContextTokenCount(200_000)).toBe('200K');
  });

  it('falls back to a single conversation segment when only telemetry is known', () => {
    const view = buildContextUsageView({
      telemetry: { tokens: 40_000, contextWindow: 100_000, percent: 40 },
      snapshot: null,
    });
    expect(view.segments).toEqual([
      { id: 'conversation', label: 'Conversation', tokens: 40_000, color: '#e85a3c' },
    ]);
    expect(view.freeTokens).toBe(60_000);
  });
});

function layer(
  id: ContextXraySnapshot['layers'][number]['id'],
  label: string,
  estimatedTokens: number,
): ContextXraySnapshot['layers'][number] {
  return {
    id,
    label,
    source: 'test',
    state: 'present',
    characters: estimatedTokens * 4,
    estimatedTokens,
    providerDelivery: 'delivered',
    content: 'x'.repeat(Math.max(1, estimatedTokens)),
  };
}
