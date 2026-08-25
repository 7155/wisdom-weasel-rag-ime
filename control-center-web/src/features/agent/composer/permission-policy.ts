import type {
  AgentPermissionSelection,
  SessionSummary,
} from '../types';

/** The visual identity of a preset now comes from `PermissionMark`, keyed on
 *  `executionMode`, so a preset no longer names an icon of its own. */
export type PermissionPreset = AgentPermissionSelection & {
  id: string;
  label: string;
  description: string;
};

export const PERMISSION_PRESETS: PermissionPreset[] = [
  {
    id: 'controlled',
    label: '写入与命令确认',
    description: '读取、搜索和预览自动；写入、Shell 与应用动作逐项批准',
    mode: 'assistant',
    toolProfileVersion: 'control-center-v1',
    executionMode: 'per_action',
  },
  {
    id: 'readonly',
    label: '只读',
    description: '只读自动，写入与 Shell 全部阻止',
    mode: 'assistant',
    toolProfileVersion: 'subagent-readonly-v1',
    executionMode: 'read_only',
  },
  {
    id: 'managed',
    label: '工作区托管',
    description: '启动时批准范围，范围内自动，越界再问',
    mode: 'coordinator',
    toolProfileVersion: 'control-center-v1',
    executionMode: 'workspace_managed',
  },
  {
    id: 'dangerous',
    label: '全自动',
    description: '所有待审批操作由独立审批 Agent（Luna Max）自动判定',
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
