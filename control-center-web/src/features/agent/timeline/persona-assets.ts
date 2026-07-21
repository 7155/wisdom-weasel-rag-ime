export type PersonaPresence = 'idle' | 'listening' | 'thinking' | 'done' | 'warning';

type PersonaAssetStates = Readonly<Record<PersonaPresence, string>>;
type PersonaTimeline = 'presence' | 'past' | 'present' | 'future' | 'flash';

type PersonaAssetRecord = Readonly<{
  personaId: string;
  timeline: PersonaTimeline;
  phaseLabel: string;
  states: PersonaAssetStates;
}>;

const portraitAssets = {
  flash: '/companions/personas/companion-flash-v2.webp',
  luna: '/companions/personas/companion-firstlight-v2.webp',
  sol: '/companions/personas/companion-future-v2.webp',
  terra: '/companions/personas/companion-present-v2.webp',
} as const;

export const personaAssetManifest = {
  schemaVersion: 'rag-ime.persona-assets.v6',
  fallbackAssetId: 'rag-ime-timeline-present-v1',
  assets: {
    'rag-ime-presence-v2': assetRecord('companion-present-v1', 'presence', '运行状态', singlePortrait(portraitAssets.terra)),
    'rag-ime-timeline-past-v1': assetRecord('companion-firstlight-v1', 'past', '初识阶段', singlePortrait(portraitAssets.luna)),
    'rag-ime-timeline-present-v1': assetRecord('companion-present-v1', 'present', '此刻阶段', singlePortrait(portraitAssets.terra)),
    'rag-ime-timeline-future-v1': assetRecord('companion-future-v1', 'future', '构筑阶段', singlePortrait(portraitAssets.sol)),
    'rag-ime-timeline-flash-v1': assetRecord('companion-flash-v1', 'flash', '闪念阶段', singlePortrait(portraitAssets.flash)),
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
