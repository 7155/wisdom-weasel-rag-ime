export type PiModelOption = {
  id: string;
  name: string;
  provider: string;
  reference: string;
  thinkingLevels: string[];
};

export type PiModelCatalogOptions = {
  models: PiModelOption[];
  selectedReference: string;
};

const thinkingLevelOrder = ['off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'] as const;

export function parsePiModelCatalogOptions(value: unknown): PiModelCatalogOptions {
  const envelope = record(value);
  const selected = record(envelope.selected);
  const selectedProvider = text(selected.provider);
  const selectedId = text(selected.id) || text(selected.modelId);
  const models = records(envelope.providers).flatMap((provider) => (
    records(provider.models).map((model) => {
      const providerId = text(model.provider) || text(provider.id);
      const id = text(model.id);
      return {
        id,
        name: text(model.name) || id,
        provider: providerId,
        reference: providerId && id ? `${providerId}/${id}` : '',
        thinkingLevels: Array.isArray(model.thinkingLevels)
          ? model.thinkingLevels.map(String)
          : [],
      };
    })
  )).filter((model) => model.reference);
  return {
    models,
    selectedReference: selectedProvider && selectedId
      ? `${selectedProvider}/${selectedId}`
      : '',
  };
}

export function supportedPiThinkingLevels(
  model: PiModelOption | undefined,
  { includeOff = false }: { includeOff?: boolean } = {},
): string[] {
  if (!model) return includeOff ? ['off'] : [];
  return thinkingLevelOrder.filter(
    (level) => (includeOff || level !== 'off') && model.thinkingLevels.includes(level),
  );
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map(record) : [];
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
