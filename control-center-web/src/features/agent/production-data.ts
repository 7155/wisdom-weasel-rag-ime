import type { AgentSnapshot } from '@/contracts/agent-reducer';
import type { AgentPersonaV1 } from '@/contracts/generated/agent-persona.v1';
import type { AgentTemplateV1 } from '@/contracts/generated/agent-template.v1';
import type { UiAgentEvent } from '@/contracts/ui-events';
import type { ModelCatalog, SessionSummary } from './types';

export const previewPersonas: AgentPersonaV1[] = [];
export const previewTemplates: AgentTemplateV1[] = [];
export const previewSessions: SessionSummary[] = [];

export function previewModelCatalog(_sessionId: string): ModelCatalog {
  return unavailable();
}

export function previewAgentSnapshot(_sessionId: string): AgentSnapshot {
  return unavailable();
}

export function previewAgentEvents(_sessionId: string): UiAgentEvent[] {
  return unavailable();
}

function unavailable(): never {
  throw new Error('Development sample data is unavailable in production.');
}
