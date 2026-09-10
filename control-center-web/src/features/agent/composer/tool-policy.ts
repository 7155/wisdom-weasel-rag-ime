import type {
  AgentPermissionSelection,
  SessionSummary,
  ToolManifest,
} from '../types';
import type { CapabilityCatalog } from '@/features/plugins/capability-policy';

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
      : session.toolProfileVersion === 'control-center-full-access-v1'
        ? 'control-center-full-access-v1'
        : 'control-center-v1';
  if (!toolAvailableForPolicy(tool, session.mode, profile) || tool.enabled === false) return false;
  // The session-scoped manifest is allowed to carry the effective operation
  // list as an additive field. An empty list means that the tool is present in
  // the catalogue for explanation, but cannot be sent to the Runtime.
  const effectiveOperations = record(tool).effectiveOperations;
  return !Array.isArray(effectiveOperations) || effectiveOperations.length > 0;
}

/**
 * The capability catalogue is the disclosure authority for a live Session.
 * Keep the raw manifest visible in the picker so a disabled capability can be
 * explained, but never count or offer it as an executable tool.
 */
export function toolAvailableForConversation(
  tool: ToolManifest,
  session: SessionSummary | undefined,
  capabilityCatalog?: CapabilityCatalog,
  sessionId = session?.id,
): boolean {
  if (capabilityCatalog?.sessionPolicy) {
    // This response already applies the backend's mode, profile and allowlist.
    // A provisional display record must not reinterpret that confirmed result.
    if (!sessionId || capabilityCatalog.sessionPolicy.sessionId !== sessionId) return false;
    const item = capabilityCatalog.items.find(
      (candidate) => candidate.kind === 'tool' && candidate.id === tool.id,
    );
    const effectiveOperations = record(tool).effectiveOperations;
    if (!item) return false;
    return tool.availability === 'online'
      && tool.enabled !== false
      && (!Array.isArray(effectiveOperations) || effectiveOperations.length > 0)
      && item.authorization.state !== 'denied'
      && item.disclosure.effective === 'enabled';
  }
  if (!toolAvailableForCurrentSession(tool, session)) return false;
  const item = capabilityCatalog?.items.find(
    (candidate) => candidate.kind === 'tool' && candidate.id === tool.id,
  );
  return !item || (item.authorization.state !== 'denied' && item.disclosure.effective === 'enabled');
}

/** Count distinct executable tools, keeping the UI and Runtime vocabulary aligned. */
export function countAvailableTools(
  tools: readonly ToolManifest[],
  session: SessionSummary | undefined,
  capabilityCatalog?: CapabilityCatalog,
  sessionId = session?.id,
): number {
  const ids = new Set<string>();
  for (const tool of tools) {
    const id = tool.id.trim();
    if (!id || ids.has(id)) continue;
    if (!toolAvailableForConversation(tool, session, capabilityCatalog, sessionId)) continue;
    ids.add(id);
  }
  return ids.size;
}

/** Count distinct tool ids returned by the Runtime, including disabled rows. */
export function countRegisteredTools(tools: readonly ToolManifest[]): number {
  const ids = new Set<string>();
  for (const tool of tools) {
    const id = tool.id.trim();
    if (id) ids.add(id);
  }
  return ids.size;
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
