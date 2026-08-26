import type { PiModelOption } from '../model-catalog-options';
import type { ModelCatalog } from '../types';

/**
 * One neutral shape for "which model", so the Session composer and the
 * Settings sheet cannot drift into two different ways of asking the same
 * question. The projection is pure: it carries provider identity, the model's
 * own name and a single line of reasoning capability, and nothing about how a
 * surface chooses to lay that out.
 */
export interface ModelChoiceOption {
  /** Stable identity across a re-read of the catalog. */
  key: string;
  providerId: string;
  providerName: string;
  modelId: string;
  name: string;
  /** One line naming the model's reasoning capability. */
  detail: string;
}

export interface ModelChoiceGroup {
  providerId: string;
  displayName: string;
  options: ModelChoiceOption[];
}

export function modelChoiceKey(providerId: string, modelId: string): string {
  return `${providerId}::${modelId}`;
}

export function modelChoiceGroupsFromCatalog(
  catalog: ModelCatalog | undefined,
): ModelChoiceGroup[] {
  return (catalog?.providers ?? []).map((provider) => ({
    providerId: provider.id,
    displayName: provider.displayName || provider.id,
    options: provider.models.map((model) => ({
      key: modelChoiceKey(provider.id, model.id),
      providerId: provider.id,
      providerName: provider.displayName || provider.id,
      modelId: model.id,
      name: model.name || model.id,
      detail: reasoningDetail(model.reasoning, model.thinkingLevels.length),
    })),
  }));
}

/**
 * The Settings catalog arrives flat, keyed by `provider/model` reference.
 * Grouping here — rather than in the sheet — keeps both surfaces reading the
 * same provider order Runtime reported, with no second sort to disagree about.
 */
export function modelChoiceGroupsFromPiOptions(
  models: readonly PiModelOption[],
): ModelChoiceGroup[] {
  const groups: ModelChoiceGroup[] = [];
  const byProvider = new Map<string, ModelChoiceGroup>();
  for (const model of models) {
    let group = byProvider.get(model.provider);
    if (!group) {
      group = { providerId: model.provider, displayName: model.provider, options: [] };
      byProvider.set(model.provider, group);
      groups.push(group);
    }
    const reasoningLevels = model.thinkingLevels.filter((level) => level !== 'off');
    group.options.push({
      key: model.reference,
      providerId: model.provider,
      providerName: model.provider,
      modelId: model.id,
      name: model.name || model.id,
      detail: reasoningDetail(reasoningLevels.length > 0, reasoningLevels.length),
    });
  }
  return groups;
}

export function firstModelChoiceKey(groups: readonly ModelChoiceGroup[]): string {
  for (const group of groups) {
    const option = group.options[0];
    if (option) return option.key;
  }
  return '';
}

export function countModelChoices(groups: readonly ModelChoiceGroup[]): number {
  return groups.reduce((total, group) => total + group.options.length, 0);
}

/**
 * Narrow a Runtime-ordered catalog without re-sorting it. A provider match
 * keeps that provider's complete group; a model match keeps only matching
 * rows. Blank search returns the original projection so consumers do not
 * churn an otherwise stable list while the picker opens.
 */
export function filterModelChoiceGroups(
  groups: readonly ModelChoiceGroup[],
  query: string,
): readonly ModelChoiceGroup[] {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  if (!normalizedQuery) return groups;

  return groups.flatMap((group) => {
    const providerMatches = `${group.displayName} ${group.providerId}`
      .toLocaleLowerCase()
      .includes(normalizedQuery);
    const options = providerMatches
      ? group.options
      : group.options.filter((option) => (
        `${option.name} ${option.modelId} ${option.providerName} ${option.providerId}`
          .toLocaleLowerCase()
          .includes(normalizedQuery)
      ));
    return options.length > 0 ? [{ ...group, options }] : [];
  });
}

function reasoningDetail(reasoning: boolean | undefined, levels: number): string {
  return reasoning && levels > 0 ? `${levels} 档推理` : '直接生成';
}
