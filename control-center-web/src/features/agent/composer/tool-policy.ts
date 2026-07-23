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
    R0: '只读',
    R1: '需确认',
    R2: '高风险确认',
    R3: '禁止',
  } as Record<string, string>)[value] ?? '受控';
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}
