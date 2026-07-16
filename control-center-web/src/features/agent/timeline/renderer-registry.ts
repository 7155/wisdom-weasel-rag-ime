import type { KnownAgentBlockType } from '@/contracts/ui-events';

export type AgentRendererIsolation =
  | 'native-sanitized'
  | 'managed-receipt'
  | 'bundled-asset';

export interface AgentRendererPolicy {
  isolation: AgentRendererIsolation;
  streaming: 'incremental' | 'replace';
  interactive: boolean;
  executableContent: false;
}

type TrustedAgentBlockType = Exclude<KnownAgentBlockType, 'unknown'>;

/**
 * This registry is the executable-content boundary for conversation blocks.
 * Adding a contract type does not make it renderable until it is explicitly
 * assigned a non-executable policy here and handled by BlockRenderer.
 */
export const TRUSTED_AGENT_RENDERERS = Object.freeze({
  text: policy('native-sanitized', 'incremental'),
  code: policy('native-sanitized', 'replace', true),
  reasoning_summary: policy('native-sanitized', 'replace', true),
  progress: policy('native-sanitized', 'replace', true),
  tool_call: policy('native-sanitized', 'replace', true),
  tool_result: policy('native-sanitized', 'replace', true),
  citation: policy('native-sanitized', 'replace', true),
  image: policy('managed-receipt', 'replace'),
  audio: policy('managed-receipt', 'replace', true),
  file: policy('managed-receipt', 'replace', true),
  sticker: policy('bundled-asset', 'replace'),
  task_plan: policy('native-sanitized', 'replace'),
  diff: policy('native-sanitized', 'replace', true),
  approval: policy('native-sanitized', 'replace', true),
  error: policy('native-sanitized', 'replace'),
} satisfies Record<TrustedAgentBlockType, AgentRendererPolicy>);

export function agentRendererPolicy(
  type: string,
): AgentRendererPolicy | undefined {
  if (!Object.prototype.hasOwnProperty.call(TRUSTED_AGENT_RENDERERS, type)) {
    return undefined;
  }
  return TRUSTED_AGENT_RENDERERS[type as TrustedAgentBlockType];
}

function policy(
  isolation: AgentRendererIsolation,
  streaming: AgentRendererPolicy['streaming'],
  interactive = false,
): AgentRendererPolicy {
  return {
    isolation,
    streaming,
    interactive,
    executableContent: false,
  };
}
