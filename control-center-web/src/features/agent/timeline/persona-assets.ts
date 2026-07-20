export type PersonaPresence = 'idle' | 'listening' | 'thinking' | 'done' | 'warning';

type PersonaAssetStates = Readonly<Record<PersonaPresence, string>>;
type PersonaTimeline = 'legacy-state' | 'past' | 'present' | 'future' | 'flash';

type PersonaAssetRecord = Readonly<{
  personaId: string;
  timeline: PersonaTimeline;
  phaseLabel: string;
  states: PersonaAssetStates;
}>;

const legacyCompanionStates: PersonaAssetStates = {
  idle: '/companions/RagImeCompanionIdle.png',
  listening: '/companions/RagImeCompanionListening.png',
  thinking: '/companions/RagImeCompanionThinking.png',
  done: '/companions/RagImeCompanionDone.png',
  warning: '/companions/RagImeCompanionWarning.png',
};

const portraitAssets = {
  flash: '/companions/personas/wisdom-weasel-flash-v1.webp',
  luna: '/companions/personas/wisdom-weasel-luna-v1.webp',
  sol: '/companions/personas/wisdom-weasel-sol-v1.webp',
  terra: '/companions/personas/wisdom-weasel-terra-v1.webp',
} as const;

export const personaAssetManifest = {
  schemaVersion: 'rag-ime.persona-assets.v4',
  fallbackAssetId: 'rag-ime-timeline-present-v1',
  assets: {
    'rag-ime-companion-v1': assetRecord('zhiyou-v1', 'legacy-state', '经典形象', legacyCompanionStates),
    'rag-ime-timeline-past-v1': assetRecord('hermes-v1', 'past', '初识阶段', singlePortrait(portraitAssets.luna)),
    'rag-ime-timeline-present-v1': assetRecord('zhiyou-v1', 'present', '此刻阶段', singlePortrait(portraitAssets.terra)),
    'rag-ime-timeline-future-v1': assetRecord('vcp-v1', 'future', '构筑阶段', singlePortrait(portraitAssets.sol)),
    'rag-ime-timeline-flash-v1': assetRecord('flash-v1', 'flash', '闪念阶段', singlePortrait(portraitAssets.flash)),
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
  phaseLabel: string,
  states: PersonaAssetStates,
): PersonaAssetRecord {
  return { personaId, timeline, phaseLabel, states };
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
