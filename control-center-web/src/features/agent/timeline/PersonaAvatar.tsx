import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import { resolvePersonaAsset, type PersonaPresence } from './persona-assets';
import './persona-avatar.css';

export type { PersonaPresence } from './persona-assets';

export function PersonaAvatar({
  fallbackName = 'Agent',
  persona,
  presence = 'idle',
  size = 'medium',
}: {
  fallbackName?: string;
  persona?: AgentPersonaV1;
  presence?: PersonaPresence;
  size?: 'small' | 'medium' | 'large' | 'hero';
}) {
  const name = persona?.displayName ?? fallbackName;
  const accent = persona?.visualProfile.accentToken ?? 'teal';
  const source = resolvePersonaAsset(persona?.visualProfile.avatarAssetId, presence);
  return (
    <span
      className="agent-persona-avatar"
      data-accent={accent}
      data-presence={presence}
      data-size={size}
      title={`${name} · ${presenceLabel(presence)}`}
    >
      <img src={source} alt={`${name}头像`} draggable={false} />
      <i aria-hidden="true" />
    </span>
  );
}

export function stickerAsset(assetId: string): string | null {
  const normalized = assetId.toLowerCase();
  if (normalized.includes('done')) return resolvePersonaAsset('rag-ime-presence-v2', 'done');
  if (normalized.includes('warning')) return resolvePersonaAsset('rag-ime-presence-v2', 'warning');
  if (normalized.includes('thinking')) return resolvePersonaAsset('rag-ime-presence-v2', 'thinking');
  if (normalized.includes('listening')) return resolvePersonaAsset('rag-ime-presence-v2', 'listening');
  if (normalized.includes('idle')) return resolvePersonaAsset('rag-ime-presence-v2', 'idle');
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
