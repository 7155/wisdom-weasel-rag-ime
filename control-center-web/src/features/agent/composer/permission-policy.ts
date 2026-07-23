import type {
  AgentPermissionSelection,
  SessionSummary,
} from '../types';

export type PermissionPreset = AgentPermissionSelection & {
  id: string;
  label: string;
  description: string;
  icon: 'shield' | 'lock' | 'network' | 'danger';
};

export const PERMISSION_PRESETS: PermissionPreset[] = [
  {
    id: 'controlled',
    label: '每次确认',
    description: '只读自动，写入与 Shell 逐项批准',
    icon: 'shield',
    mode: 'assistant',
    toolProfileVersion: 'control-center-v1',
    executionMode: 'per_action',
  },
  {
    id: 'readonly',
    label: '只读',
    description: '只读自动，写入与 Shell 全部阻止',
    icon: 'lock',
    mode: 'assistant',
    toolProfileVersion: 'subagent-readonly-v1',
    executionMode: 'read_only',
  },
  {
    id: 'managed',
    label: '工作区托管',
    description: '启动时批准范围，范围内自动，越界再问',
    icon: 'network',
    mode: 'coordinator',
    toolProfileVersion: 'control-center-v1',
    executionMode: 'workspace_managed',
  },
  {
    id: 'dangerous',
    label: '完全信任',
    description: '范围内自动，保留取消、审计与危险动作禁区',
    icon: 'danger',
    mode: 'coordinator',
    toolProfileVersion: 'control-center-v1',
    executionMode: 'full_trust',
  },
];

export function permissionPreset(
  executionMode: SessionSummary['executionMode'] | undefined,
  profile: string,
): PermissionPreset {
  const legacyMode = executionMode
    ?? (profile === 'control-center-auto-approve-v1'
      ? 'full_trust'
      : profile === 'subagent-readonly-v1'
        ? 'read_only'
        : 'per_action');
  return PERMISSION_PRESETS.find((item) => item.executionMode === legacyMode)
    ?? PERMISSION_PRESETS[0]!;
}

export function permissionLabel(session: SessionSummary): string {
  return permissionPreset(
    session.executionMode,
    session.toolProfileVersion ?? 'control-center-v1',
  ).label;
}
