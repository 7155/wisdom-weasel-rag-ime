import { describe, expect, it } from 'vitest';
import type { ContextXraySnapshot } from './ContextXrayPanel';
import {
  buildContextUsageView,
  formatContextTokenCount,
} from './context-usage-model';

describe('context usage model', () => {
  it('projects the requested context layers with honest exact, estimated, and unknown values', () => {
    const snapshot: ContextXraySnapshot = {
      available: true,
      prompt: 'CURRENT_INPUT',
      layers: [
        layer('system', 'System', 1_000),
        layer('skills', 'Skills', 400),
        layer('tools', 'Tools', 2_000),
        layer('project-context', 'Project', 3_000),
        layer('workflow-control', 'Workflow', 200),
        layer('session-memory', 'Session Memory', 700),
        layer('memory-recall', 'Memory recall', 500),
        layer('knowledge-rag', 'Knowledge/RAG', 600),
        layer('timeline', 'Timeline', 4_000),
        layer('user-messages', 'User', 1_000),
        layer('assistant-messages', 'Assistant', 1_500),
        layer('tool-calls', 'Tool calls', 300),
        layer('tool-results', 'Tool results', 700),
      ],
      contextTokens: 18_000,
      contextWindow: 100_000,
      cacheHitPercent: 68,
      cache: {
        inputTokens: 18_000,
        outputTokens: 500,
        cacheReadTokens: 4_250,
        cacheWriteTokens: 0,
        prefixBytes: null,
        duplicateBytes: null,
        capability: 'reported',
      },
      compaction: { count: 2, status: 'completed', tokensBefore: 80_000, tokensAfter: 20_000 },
      providerStatus: 200,
      providerCaptured: true,
      updatedAtMs: 1,
    };

    const view = buildContextUsageView({ snapshot });

    expect(view.layers.map((item) => item.id)).toEqual([
      'systemPrompt',
      'skillsTools',
      'projectContext',
      'conversationHistory',
      'memory',
      'knowledge',
      'currentInput',
      'cache',
      'compaction',
    ]);
    expect(view.layers.find((item) => item.id === 'systemPrompt')).toMatchObject({
      characters: 1_000,
      tokens: null,
      tokenQuality: 'unknown',
    });
    expect(view.layers.find((item) => item.id === 'memory')).toMatchObject({
      characters: 5_200,
      tokens: null,
      tokenQuality: 'unknown',
    });
    expect(view.layers.find((item) => item.id === 'currentInput')).toMatchObject({
      characters: 'CURRENT_INPUT'.length,
      tokenQuality: 'unknown',
    });
    expect(view.layers.find((item) => item.id === 'cache')).toMatchObject({
      tokens: 4_250,
      tokenQuality: 'exact',
    });
    expect(view.layers.find((item) => item.id === 'compaction')).toMatchObject({
      tokens: 20_000,
      tokenQuality: 'estimated',
    });
    expect(view.layers.find((item) => item.id === 'knowledge')).toMatchObject({
      characters: 600,
      tokenQuality: 'unknown',
    });
  });

  it('keeps semantic layers explicitly unknown when the Runtime did not expose their contents', () => {
    const view = buildContextUsageView({
      telemetry: { tokens: 40_000, contextWindow: 100_000, percent: 40 },
      snapshot: null,
    });

    expect(view.layers).toHaveLength(9);
    expect(view.layers.every((item) => item.characters === null || item.id === 'cache')).toBe(true);
    expect(view.layers.find((item) => item.id === 'memory')).toMatchObject({
      characters: null,
      tokens: null,
      tokenQuality: 'unknown',
      state: 'unknown',
    });
    expect(view.unclassifiedTokens).toBe(40_000);
  });

  it('keeps exact captured characters separate from aggregate Runtime tokens', () => {
    const snapshot: ContextXraySnapshot = {
      available: true,
      layers: [
        layer('system', 'System prompt', 1_700),
        layer('tools', 'Tools', 11_100),
        layer('project-context', 'Rules', 4_200),
        layer('skills', 'Skills', 433),
        layer('lifecycle-hook', 'MCP', 2_500),
        layer('role-book', 'Subagents', 945),
        layer('compaction-summary', 'Compaction summary', 2_700),
        layer('user-messages', 'User messages', 56_000),
        layer('assistant-messages', 'Assistant messages', 50_000),
        layer('tool-calls', 'Tool calls', 1_400),
        layer('tool-results', 'Tool results', 3_200),
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
      'user',
      'assistant',
      'toolCalls',
      'toolResults',
    ]);
    expect(view.segments.find((segment) => segment.id === 'user')?.characters).toBe(56_000);
    expect(view.segments.find((segment) => segment.id === 'assistant')?.characters).toBe(50_000);
    expect(view.segments.find((segment) => segment.id === 'toolCalls')?.characters).toBe(1_400);
    expect(view.segments.find((segment) => segment.id === 'toolResults')?.characters).toBe(3_200);
    expect(view.unclassifiedTokens).toBe(132_778);
    expect(formatContextTokenCount(132_778)).toBe('132.8K');
    expect(formatContextTokenCount(200_000)).toBe('200K');
  });

  it('keeps telemetry-only usage unclassified instead of inventing a semantic segment', () => {
    const view = buildContextUsageView({
      telemetry: { tokens: 40_000, contextWindow: 100_000, percent: 40 },
      snapshot: null,
    });
    expect(view.segments).toEqual([]);
    expect(view.unclassifiedTokens).toBe(40_000);
    expect(view.freeTokens).toBe(60_000);
  });

  it('does not subtract captured characters from aggregate token usage', () => {
    const snapshot: ContextXraySnapshot = {
      available: true,
      layers: [layer('system', 'System prompt', 10_000)],
      contextTokens: 12_000,
      contextWindow: 100_000,
      cacheHitPercent: null,
      compaction: { count: 0, status: '', tokensBefore: null, tokensAfter: null },
      providerStatus: 200,
      providerCaptured: true,
      updatedAtMs: 1,
    };

    const view = buildContextUsageView({ snapshot });
    expect(view.segments).toEqual([
      { id: 'system', label: '系统提示词', characters: 10_000, color: '#8b919a' },
    ]);
    expect(view.unclassifiedTokens).toBe(12_000);
  });

  it('never scales character measurements into token buckets and exposes estimated compaction size honestly', () => {
    const snapshot: ContextXraySnapshot = {
      available: true,
      layers: [
        layer('system', 'System prompt', 20_000),
        layer('tools', 'Tools', 40_000),
        layer('timeline', 'Conversation', 140_000),
      ],
      contextTokens: 100_000,
      contextWindow: 200_000,
      cacheHitPercent: null,
      compaction: { count: 2, status: 'completed', tokensBefore: 128_000, tokensAfter: 29_000 },
      providerStatus: 200,
      providerCaptured: true,
      updatedAtMs: 1,
    };

    const view = buildContextUsageView({ snapshot });
    expect(view.segments.reduce((sum, segment) => sum + segment.characters, 0)).toBe(200_000);
    expect(view.segments.find((segment) => segment.id === 'system')).toMatchObject({
      label: '系统提示词',
      characters: 20_000,
    });
    expect(view.unclassifiedTokens).toBe(100_000);
    expect(view.compaction).toEqual({
      count: 2,
      status: 'completed',
      tokensBefore: 128_000,
      tokensAfter: 29_000,
    });
  });
});

function layer(
  id: ContextXraySnapshot['layers'][number]['id'],
  label: string,
  characters: number,
): ContextXraySnapshot['layers'][number] {
  return {
    id,
    label,
    source: 'test',
    state: 'present',
    characters,
    tokens: null,
    providerDelivery: 'delivered',
    content: 'x'.repeat(Math.max(1, characters)),
  };
}
