import type { KnownAgentBlockType } from '@/contracts/ui-events';
import {
  CodeBlockRenderer,
  DiffBlockRenderer,
} from './CodeDiffRenderers';
import {
  ArtifactBlockRenderer,
  AudioBlockRenderer,
  CitationBlockRenderer,
  FileBlockRenderer,
  ImageBlockRenderer,
  StickerBlockRenderer,
} from './MediaRenderers';
import { TextBlockRenderer } from './MarkdownRenderer';
import type { AgentBlockRenderer } from './renderer-contract';
import {
  ApprovalBlockRenderer,
  CardBlockRenderer,
  ChecklistBlockRenderer,
  ErrorBlockRenderer,
  ProgressBlockRenderer,
  ReasoningSummaryBlockRenderer,
  StatusBlockRenderer,
  TableBlockRenderer,
  TaskPlanBlockRenderer,
  ToolCallBlockRenderer,
  ToolResultBlockRenderer,
} from './StructuredRenderers';

export type AgentRendererIsolation =
  | 'native-sanitized'
  | 'managed-receipt'
  | 'bundled-asset';

export interface AgentRendererPolicy {
  Renderer: AgentBlockRenderer;
  isolation: AgentRendererIsolation;
  streaming: 'incremental' | 'replace';
  interactive: boolean;
  executableContent: false;
}

type TrustedAgentBlockType = Exclude<KnownAgentBlockType, 'unknown'>;

/**
 * This registry is the executable-content boundary for conversation blocks.
 * Adding a contract type does not make it renderable until it is explicitly
 * assigned a non-executable policy and one renderer here. BlockRenderer only
 * composes this registry; it never grows a second type-dispatch path.
 */
export const TRUSTED_AGENT_RENDERERS = Object.freeze({
  text: policy(TextBlockRenderer, 'native-sanitized', 'incremental'),
  card: policy(CardBlockRenderer, 'native-sanitized', 'replace'),
  checklist: policy(ChecklistBlockRenderer, 'native-sanitized', 'replace'),
  table: policy(TableBlockRenderer, 'native-sanitized', 'replace'),
  code: policy(CodeBlockRenderer, 'native-sanitized', 'replace', true),
  artifact: policy(ArtifactBlockRenderer, 'managed-receipt', 'replace', true),
  reference: policy(CitationBlockRenderer, 'native-sanitized', 'replace', true),
  status: policy(StatusBlockRenderer, 'native-sanitized', 'replace'),
  reasoning_summary: policy(ReasoningSummaryBlockRenderer, 'native-sanitized', 'replace', true),
  progress: policy(ProgressBlockRenderer, 'native-sanitized', 'replace', true),
  tool_call: policy(ToolCallBlockRenderer, 'native-sanitized', 'replace', true),
  tool_result: policy(ToolResultBlockRenderer, 'native-sanitized', 'replace', true),
  citation: policy(CitationBlockRenderer, 'native-sanitized', 'replace', true),
  image: policy(ImageBlockRenderer, 'managed-receipt', 'replace'),
  audio: policy(AudioBlockRenderer, 'managed-receipt', 'replace', true),
  file: policy(FileBlockRenderer, 'managed-receipt', 'replace', true),
  sticker: policy(StickerBlockRenderer, 'bundled-asset', 'replace'),
  task_plan: policy(TaskPlanBlockRenderer, 'native-sanitized', 'replace'),
  diff: policy(DiffBlockRenderer, 'native-sanitized', 'replace', true),
  approval: policy(ApprovalBlockRenderer, 'native-sanitized', 'replace', true),
  error: policy(ErrorBlockRenderer, 'native-sanitized', 'replace'),
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
  Renderer: AgentBlockRenderer,
  isolation: AgentRendererIsolation,
  streaming: AgentRendererPolicy['streaming'],
  interactive = false,
): AgentRendererPolicy {
  return {
    Renderer,
    isolation,
    streaming,
    interactive,
    executableContent: false,
  };
}
