import type { AgentModelCatalogV1 } from '@/contracts/generated/agent-model-catalog.v1';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import type { AgentSessionV1 } from '@/contracts/generated/agent-session.v1';
import type { ControlToolManifestV1 } from '@/contracts/generated/control-tool-manifest.v1';
import type { PickedFile } from '@/platform/transport';

export type SessionSummary = Pick<
  AgentSessionV1,
  | 'id'
  | 'title'
  | 'mode'
  | 'status'
  | 'roleId'
  | 'roleVersion'
  | 'updatedAtMs'
  | 'workspaceRoots'
> &
  Partial<Pick<AgentSessionV1, 'lastMessagePreview' | 'messageCount' | 'modelProfile'>>;

export interface AgentSessionListResponse {
  ok: boolean;
  items?: SessionSummary[];
  sessions?: SessionSummary[];
  activeSessionId?: string | null;
}

export interface AgentRoleListResponse {
  ok: boolean;
  items?: AgentPersonaV1[];
  roles?: AgentPersonaV1[];
}

export interface ComposerAttachment extends PickedFile {
  source: 'picker' | 'clipboard' | 'path';
}

export type ThinkingLevel = AgentModelCatalogV1['thinkingLevel'];
export type ModelCatalog = AgentModelCatalogV1;
export type ToolManifest = ControlToolManifestV1;

export type AgentCommandSource = 'extension' | 'prompt' | 'skill';

export type AgentProductCommandName =
  | 'new'
  | 'name'
  | 'compact'
  | 'model'
  | 'thinking'
  | 'tools'
  | 'status'
  | 'stop'
  | 'help';

export interface AgentCommand {
  name: string;
  invocation: string;
  description: string;
  source: AgentCommandSource;
}

export function sessionItems(value: unknown): SessionSummary[] {
  if (!isRecord(value)) return [];
  const source = Array.isArray(value.items)
    ? value.items
    : Array.isArray(value.sessions)
      ? value.sessions
      : [];
  return source.filter(isSessionSummary);
}

export function activeSessionId(value: unknown): string {
  if (!isRecord(value)) return '';
  return typeof value.activeSessionId === 'string' ? value.activeSessionId : '';
}

export function roleItems(value: unknown): AgentPersonaV1[] {
  if (!isRecord(value)) return [];
  const source = Array.isArray(value.items)
    ? value.items
    : Array.isArray(value.roles)
      ? value.roles
      : [];
  return source.filter(isPersona);
}

export function toolItems(value: unknown): ToolManifest[] {
  if (!isRecord(value)) return [];
  const source = Array.isArray(value.items) ? value.items : [];
  return source.filter(isToolManifest);
}

export function commandItems(value: unknown): AgentCommand[] {
  if (!isRecord(value) || value.schemaVersion !== 'rag-ime.agent-command-catalog.v1') return [];
  const source = Array.isArray(value.items) ? value.items : [];
  return source.filter(isAgentCommand).slice(0, 200);
}

export function isModelCatalog(value: unknown): value is ModelCatalog {
  return (
    isRecord(value) &&
    value.schemaVersion === 'rag-ime.agent-model-catalog.v1' &&
    Array.isArray(value.providers)
  );
}

function isSessionSummary(value: unknown): value is SessionSummary {
  return (
    isRecord(value) &&
    typeof value.id === 'string' &&
    typeof value.title === 'string' &&
    typeof value.updatedAtMs === 'number'
  );
}

function isAgentCommand(value: unknown): value is AgentCommand {
  if (!isRecord(value)) return false;
  const source = value.source;
  const name = typeof value.name === 'string' ? value.name : '';
  return (
    (source === 'extension' || source === 'prompt' || source === 'skill')
    && typeof value.description === 'string'
    && typeof value.invocation === 'string'
    && value.invocation === `/${name}`
    && name.length > 0
    && name.length <= 80
    && !/[\s/\\]/u.test(name)
  );
}

function isPersona(value: unknown): value is AgentPersonaV1 {
  return (
    isRecord(value) &&
    value.schemaVersion === 'rag-ime.agent-persona.v1' &&
    typeof value.roleId === 'string' &&
    typeof value.displayName === 'string'
  );
}

function isToolManifest(value: unknown): value is ToolManifest {
  return (
    isRecord(value) &&
    value.schemaVersion === 'rag-ime.control-tool-manifest.v1' &&
    typeof value.id === 'string' &&
    typeof value.displayName === 'string' &&
    typeof value.description === 'string' &&
    Array.isArray(value.sessionModes) &&
    Array.isArray(value.operations)
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
