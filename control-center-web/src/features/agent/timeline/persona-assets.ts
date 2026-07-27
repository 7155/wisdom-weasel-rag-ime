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
  flash: '/companions/personas/companion-flash-v9.webp',
  luna: '/companions/personas/companion-firstlight-v9.webp',
  sol: '/companions/personas/companion-future-v9.webp',
  terra: '/companions/personas/companion-present-v9.webp',
} as const;

const presentReactions: PersonaAssetStates = {
  idle: portraitAssets.terra,
  listening: portraitAssets.terra,
  thinking: '/companions/personas/companion-present-thinking-v9.webp',
  done: '/companions/personas/companion-present-done-v9.webp',
  warning: '/companions/personas/companion-present-warning-v9.webp',
};

export const personaAssetManifest = {
  schemaVersion: 'rag-ime.persona-assets.v12',
  fallbackAssetId: 'rag-ime-timeline-present-v1',
  assets: {
    'rag-ime-presence-v2': assetRecord('companion-present-v1', 'presence', '运行状态', presentReactions),
    'rag-ime-timeline-past-v1': assetRecord('companion-firstlight-v1', 'past', '初识阶段', singlePortrait(portraitAssets.luna)),
    'rag-ime-timeline-present-v1': assetRecord('companion-present-v1', 'present', '此刻阶段', presentReactions),
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
