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
    label: '核心',
    description: '产品内置指令、Skills 与 Tools',
    selection: {
      projectContextEnabled: false,
      piSkillsEnabled: false,
      codexSkillsEnabled: false,
    },
  },
  {
    id: 'project',
    label: '项目',
    description: '核心资源 + 工作区 AGENTS.md / CLAUDE.md',
    selection: {
      projectContextEnabled: true,
      piSkillsEnabled: false,
      codexSkillsEnabled: false,
    },
  },
  {
    id: 'extended',
    label: '扩展',
    description: '项目资源 + 已检测到的 Pi、Codex 与 Agents Skills',
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
    : CONTEXT_RESOURCE_PROFILES.find((profile) => profile.id === profileId)?.label ?? '核心';
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
