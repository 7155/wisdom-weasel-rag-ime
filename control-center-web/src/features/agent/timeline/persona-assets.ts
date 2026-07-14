export type PersonaPresence = 'idle' | 'listening' | 'thinking' | 'done' | 'warning';

type PersonaAssetStates = Readonly<Record<PersonaPresence, string>>;
type PersonaTimeline = 'legacy-state' | 'past' | 'present' | 'future';

type PersonaAssetRecord = Readonly<{
  personaId: string;
  timeline: PersonaTimeline;
  modelAffinity: string;
  states: PersonaAssetStates;
}>;

const legacyCompanionStates: PersonaAssetStates = {
  idle: '/companions/RagImeCompanionIdle.png',
  listening: '/companions/RagImeCompanionListening.png',
  thinking: '/companions/RagImeCompanionThinking.png',
  done: '/companions/RagImeCompanionDone.png',
  warning: '/companions/RagImeCompanionWarning.png',
};

export const personaAssetManifest = {
  schemaVersion: 'rag-ime.persona-assets.v2',
  fallbackAssetId: 'rag-ime-timeline-present-v1',
  assets: {
    'rag-ime-companion-v1': assetRecord('zhiyou-v1', 'legacy-state', 'session-selected', legacyCompanionStates),
    'rag-ime-timeline-past-v1': assetRecord('hermes-v1', 'past', '5.6 Luna', singlePortrait('/companions/timeline-past.png')),
    'rag-ime-timeline-present-v1': assetRecord('zhiyou-v1', 'present', '5.6 Terra', singlePortrait('/companions/timeline-present.png')),
    'rag-ime-timeline-future-v1': assetRecord('vcp-v1', 'future', '5.6 Sol', singlePortrait('/companions/timeline-future.png')),
  },
} as const;

export function resolvePersonaAsset(
  assetId: string | null | undefined,
  presence: PersonaPresence,
): string {
  const assets = personaAssetManifest.assets;
  const record = assetId && Object.prototype.hasOwnProperty.call(assets, assetId)
    ? assets[assetId as keyof typeof assets]
    : assets[personaAssetManifest.fallbackAssetId];
  return record.states[presence];
}

function assetRecord(
  personaId: string,
  timeline: PersonaTimeline,
  modelAffinity: string,
  states: PersonaAssetStates,
): PersonaAssetRecord {
  return { personaId, timeline, modelAffinity, states };
}

function singlePortrait(source: string): PersonaAssetStates {
  return {
    idle: source,
    listening: source,
    thinking: source,
    done: source,
    warning: source,
  };
}
