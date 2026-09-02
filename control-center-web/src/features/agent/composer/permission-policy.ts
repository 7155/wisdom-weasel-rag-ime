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

/** These are the only policies exposed by new user-facing controls. */
export const PERMISSION_PRESETS: PermissionPreset[] = [
  {
    id: 'full-access',
    label: '全权限',
    description: '整个系统与所有 Tool 可用；有影响的操作逐项请求确认',
    mode: 'coordinator',
    toolProfileVersion: 'control-center-full-access-v1',
    executionMode: 'per_action',
  },
  {
    id: 'full-auto',
    label: '全自动',
    description: '整个系统与所有 Tool 可用；每个动作自动批准，仍受操作系统边界约束',
    mode: 'coordinator',
    toolProfileVersion: 'control-center-auto-approve-v1',
    executionMode: 'full_trust',
  },
];

/** Old/system Sessions remain readable without making their policies selectable. */
const LEGACY_PERMISSION_PRESETS: PermissionPreset[] = [
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
    description: '旧版全自动策略；仅用于显示现有 Session',
    mode: 'coordinator',
    toolProfileVersion: 'control-center-v1',
    executionMode: 'full_trust',
  },
];

export function permissionPreset(
  executionMode: SessionSummary['executionMode'] | undefined,
  profile: string,
): PermissionPreset {
  if (profile === 'control-center-full-access-v1') return PERMISSION_PRESETS[0]!;
  if (profile === 'control-center-auto-approve-v1') return PERMISSION_PRESETS[1]!;
  const legacyMode = executionMode
    ?? (profile === 'subagent-readonly-v1'
      ? 'read_only'
      : 'per_action');
  return LEGACY_PERMISSION_PRESETS.find((item) => item.executionMode === legacyMode)
    ?? LEGACY_PERMISSION_PRESETS[0]!;
}

export function permissionLabel(session: SessionSummary): string {
  return permissionPreset(
    session.executionMode,
    session.toolProfileVersion ?? 'control-center-v1',
  ).label;
}

export function unrestrictedWorkspaceRoots(...roots: string[]): string[] {
  return [...new Set(roots.map((root) => root.trim()).filter(Boolean).concat('/'))];
}
