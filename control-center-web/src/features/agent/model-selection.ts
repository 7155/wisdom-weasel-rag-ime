import type { ModelCatalog, ThinkingLevel } from './types';

export interface AgentModelSelection {
  provider: string;
  modelId: string;
  level: ThinkingLevel;
}

export function modelSelectionFromCatalog(
  catalog: ModelCatalog,
): AgentModelSelection | undefined {
  const selected = record(catalog.selected);
  const provider = text(selected.provider);
  const modelId = text(selected.id) || text(selected.modelId);
  if (!provider || !modelId) return undefined;
  return { provider, modelId, level: catalog.thinkingLevel };
}

export function catalogWithModelSelection(
  catalog: ModelCatalog,
  selection: AgentModelSelection,
): ModelCatalog {
  const model = catalog.providers
    .find((provider) => provider.id === selection.provider)
    ?.models.find((item) => item.id === selection.modelId);
  if (!model) return catalog;
  return {
    ...catalog,
    selected: {
      ...record(catalog.selected),
      provider: selection.provider,
      id: selection.modelId,
      modelId: selection.modelId,
      name: model.name,
    },
    thinkingLevel: selection.level,
  };
}

export function catalogWithConfigurationEvent(
  catalog: ModelCatalog,
  payload: Record<string, unknown>,
): ModelCatalog {
  const selected = record(payload.selected);
  const provider = text(selected.provider);
  const modelId = text(selected.id) || text(selected.modelId);
  const level = thinkingLevel(payload.thinkingLevel);
  let next = catalog;
  if (provider && modelId) {
    next = catalogWithModelSelection(next, {
      provider,
      modelId,
      level: level ?? next.thinkingLevel,
    });
  } else if (level) {
    next = { ...next, thinkingLevel: level };
  }
  return next;
}

export function sameModelSelection(
  left: AgentModelSelection | undefined,
  right: AgentModelSelection | undefined,
): boolean {
  return Boolean(
    left
    && right
    && left.provider === right.provider
    && left.modelId === right.modelId
    && left.level === right.level,
  );
}

function thinkingLevel(value: unknown): ThinkingLevel | undefined {
  return (
    value === 'off'
    || value === 'minimal'
    || value === 'low'
    || value === 'medium'
    || value === 'high'
    || value === 'xhigh'
    || value === 'max'
  ) ? value : undefined;
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
