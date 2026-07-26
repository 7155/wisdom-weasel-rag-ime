import type { SessionSummary } from './types';

export type ContextResourceProfileId = 'core' | 'project' | 'extended' | 'custom';

export interface ContextResourceSelection {
  projectContextEnabled: boolean;
  piSkillsEnabled: boolean;
  codexSkillsEnabled: boolean;
}

export const CONTEXT_RESOURCE_PROFILES: ReadonlyArray<{
  id: Exclude<ContextResourceProfileId, 'custom'>;
  label: string;
  description: string;
  selection: ContextResourceSelection;
}> = [
  {
    id: 'core',
    label: '内置',
    description: '仅使用产品自带的工作指令、技能与工具',
    selection: {
      projectContextEnabled: false,
      piSkillsEnabled: false,
      codexSkillsEnabled: false,
    },
  },
  {
    id: 'project',
    label: '当前项目',
    description: '再读取工作区里的 AGENTS.md / CLAUDE.md',
    selection: {
      projectContextEnabled: true,
      piSkillsEnabled: false,
      codexSkillsEnabled: false,
    },
  },
  {
    id: 'extended',
    label: '本机扩展',
    description: '再发现本机已安装的 Pi、Codex 与 Agents Skills',
    selection: {
      projectContextEnabled: true,
      piSkillsEnabled: true,
      codexSkillsEnabled: true,
    },
  },
];

export function contextResourceSelection(
  session: SessionSummary | undefined,
): ContextResourceSelection {
  return {
    projectContextEnabled: session?.projectContextEnabled === true,
    piSkillsEnabled: session?.piSkillsEnabled === true,
    codexSkillsEnabled: session?.codexSkillsEnabled === true,
  };
}

export function contextResourceProfileId(
  selection: ContextResourceSelection,
): ContextResourceProfileId {
  return CONTEXT_RESOURCE_PROFILES.find(
    (profile) => sameContextResourceSelection(profile.selection, selection),
  )?.id ?? 'custom';
}

export function contextResourceProfileLabel(
  selection: ContextResourceSelection,
): string {
  const profileId = contextResourceProfileId(selection);
  return profileId === 'custom'
    ? '自定义'
    : CONTEXT_RESOURCE_PROFILES.find((profile) => profile.id === profileId)?.label ?? '内置';
}

export function sameContextResourceSelection(
  left: ContextResourceSelection | undefined,
  right: ContextResourceSelection | undefined,
): boolean {
  return Boolean(
    left
    && right
    && left.projectContextEnabled === right.projectContextEnabled
    && left.piSkillsEnabled === right.piSkillsEnabled
    && left.codexSkillsEnabled === right.codexSkillsEnabled,
  );
}

export function sessionWithContextResources(
  session: SessionSummary,
  selection: ContextResourceSelection,
): SessionSummary {
  return { ...session, ...selection };
}
