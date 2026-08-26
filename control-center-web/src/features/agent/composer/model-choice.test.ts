import { describe, expect, it } from 'vitest';

import type { PiModelOption } from '../model-catalog-options';
import type { ModelCatalog } from '../types';
import {
  countModelChoices,
  filterModelChoiceGroups,
  firstModelChoiceKey,
  modelChoiceGroupsFromCatalog,
  modelChoiceGroupsFromPiOptions,
} from './model-choice';

function catalog(): ModelCatalog {
  return {
    schemaVersion: 'rag-ime.agent-model-catalog.v1',
    ok: true,
    thinkingLevel: 'medium',
    providers: [
      {
        id: 'openai-codex',
        displayName: 'OpenAI Codex',
        models: [
          {
            provider: 'openai-codex',
            id: 'gpt-5.6-terra',
            name: 'GPT-5.6 Terra',
            api: 'responses',
            reasoning: true,
            thinkingLevels: ['off', 'medium', 'high'],
            supportsImages: true,
            contextWindow: 128_000,
            maxTokens: 32_000,
          },
          {
            provider: 'openai-codex',
            id: 'gpt-5.6-swift',
            name: 'GPT-5.6 Swift',
            api: 'responses',
            reasoning: false,
            thinkingLevels: [],
            supportsImages: false,
            contextWindow: 64_000,
            maxTokens: 16_000,
          },
        ],
      },
    ],
  } as unknown as ModelCatalog;
}

describe('model choice projection', () => {
  it('keeps the composer catalog grouped by provider with a reasoning line per model', () => {
    const groups = modelChoiceGroupsFromCatalog(catalog());

    expect(groups).toHaveLength(1);
    expect(groups[0].displayName).toBe('OpenAI Codex');
    expect(groups[0].options.map((option) => [option.name, option.detail])).toEqual([
      ['GPT-5.6 Terra', '3 档推理'],
      ['GPT-5.6 Swift', '直接生成'],
    ]);
    expect(firstModelChoiceKey(groups)).toBe('openai-codex::gpt-5.6-terra');
    expect(countModelChoices(groups)).toBe(2);
  });

  it('groups the flat Settings catalog without resorting the order Runtime reported', () => {
    const models: PiModelOption[] = [
      { id: 'a', name: 'Model A', provider: 'zeta', reference: 'zeta/a', thinkingLevels: ['off', 'high'] },
      { id: 'b', name: 'Model B', provider: 'alpha', reference: 'alpha/b', thinkingLevels: [] },
      { id: 'c', name: 'Model C', provider: 'zeta', reference: 'zeta/c', thinkingLevels: ['off'] },
    ];

    const groups = modelChoiceGroupsFromPiOptions(models);

    expect(groups.map((group) => group.providerId)).toEqual(['zeta', 'alpha']);
    expect(groups[0].options.map((option) => option.key)).toEqual(['zeta/a', 'zeta/c']);
    // `off` is the absence of reasoning, so it never counts as a reasoning tier.
    expect(groups[0].options.map((option) => option.detail)).toEqual(['1 档推理', '直接生成']);
    expect(groups[1].options[0].detail).toBe('直接生成');
    expect(countModelChoices(groups)).toBe(3);
  });

  it('reports an empty catalog instead of a phantom first choice', () => {
    expect(modelChoiceGroupsFromCatalog(undefined)).toEqual([]);
    expect(firstModelChoiceKey([])).toBe('');
    expect(countModelChoices([])).toBe(0);
  });

  it('filters the model list by model or provider without changing Runtime order', () => {
    const groups = modelChoiceGroupsFromCatalog(catalog());

    expect(filterModelChoiceGroups(groups, 'swift')[0]?.options.map((option) => option.modelId))
      .toEqual(['gpt-5.6-swift']);
    expect(filterModelChoiceGroups(groups, 'openai codex')).toEqual(groups);
    expect(filterModelChoiceGroups(groups, 'missing')).toEqual([]);
    expect(filterModelChoiceGroups(groups, '   ')).toBe(groups);
  });
});
