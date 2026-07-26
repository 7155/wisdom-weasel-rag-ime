import type {
  AgentPermissionSelection,
  SessionSummary,
  ToolManifest,
} from '../types';

export function toolAvailableForPolicy(
  tool: ToolManifest,
  mode: SessionSummary['mode'],
  profile: AgentPermissionSelection['toolProfileVersion'],
): boolean {
  if (tool.availability !== 'online' || !tool.sessionModes.includes(mode)) return false;
  const operationsByProfile = record(tool.profileOperations);
  const operations = operationsByProfile[profile];
  return !Array.isArray(operations) || operations.length > 0;
}

export function toolAvailableForCurrentSession(
  tool: ToolManifest,
  session?: SessionSummary,
): boolean {
  if (!session) return false;
  const profile = session.toolProfileVersion === 'subagent-readonly-v1'
    ? 'subagent-readonly-v1'
    : session.toolProfileVersion === 'control-center-auto-approve-v1'
      ? 'control-center-auto-approve-v1'
      : 'control-center-v1';
  return toolAvailableForPolicy(tool, session.mode, profile) && tool.enabled !== false;
}

export function riskLabel(value: string): string {
  return ({
    R0: '只查看',
    R1: '会改数据',
    R2: '文件或命令',
    R3: '不可使用',
  } as Record<string, string>)[value] ?? '受权限保护';
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}
