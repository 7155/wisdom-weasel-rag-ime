import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';

export type PersonaPresence = 'idle' | 'listening' | 'thinking' | 'done' | 'warning';

const companionAssets: Record<PersonaPresence, string> = {
  idle: '/companions/RagImeCompanionIdle.png',
  listening: '/companions/RagImeCompanionListening.png',
  thinking: '/companions/RagImeCompanionThinking.png',
  done: '/companions/RagImeCompanionDone.png',
  warning: '/companions/RagImeCompanionWarning.png',
};

export function PersonaAvatar({
  persona,
  presence = 'idle',
  size = 'medium',
}: {
  persona?: AgentPersonaV1;
  presence?: PersonaPresence;
  size?: 'small' | 'medium' | 'large' | 'hero';
}) {
  const name = persona?.displayName ?? '智鼬';
  const accent = persona?.visualProfile.accentToken ?? 'teal';
  return (
    <span
      className="agent-persona-avatar"
      data-accent={accent}
      data-presence={presence}
      data-size={size}
      title={`${name} · ${presenceLabel(presence)}`}
    >
      <img src={companionAssets[presence]} alt={`${name}头像`} draggable={false} />
      <i aria-hidden="true" />
    </span>
  );
}

export function stickerAsset(assetId: string): string | null {
  const normalized = assetId.toLowerCase();
  if (normalized.includes('done')) return companionAssets.done;
  if (normalized.includes('warning')) return companionAssets.warning;
  if (normalized.includes('thinking')) return companionAssets.thinking;
  if (normalized.includes('listening')) return companionAssets.listening;
  if (normalized.includes('idle')) return companionAssets.idle;
  return null;
}

function presenceLabel(value: PersonaPresence): string {
  switch (value) {
    case 'listening':
      return '正在聆听';
    case 'thinking':
      return '正在处理';
    case 'done':
      return '已完成';
    case 'warning':
      return '需要注意';
    case 'idle':
      return '空闲';
  }
}
