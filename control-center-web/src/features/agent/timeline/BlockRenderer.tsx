import { memo } from 'react';
import type { UiAgentBlock } from '@/contracts/ui-events';
import { UnknownBlockRenderer } from './MediaRenderers';
import { agentRendererPolicy } from './renderer-registry';

export {
  MarkdownBody,
  markdownFoldThresholds,
  partitionStreamingMarkdown,
  partitionStreamingMarkdownFragments,
} from './MarkdownRenderer';
export { SafeFieldList } from './StructuredRenderers';

interface AgentBlocksProps {
  blocks: UiAgentBlock[];
  onApprovalDecision?: (
    approvalId: string,
    decision: 'approved' | 'rejected',
    hash: string,
  ) => void;
  sessionId?: string;
  streaming?: boolean;
}

export function AgentBlocks({
  blocks,
  onApprovalDecision,
  sessionId = '',
  streaming = false,
}: AgentBlocksProps) {
  const tailIndex = streaming ? findLastTextBlock(blocks) : -1;
  return (
    <div className="agent-blocks" data-has-stream-tail={tailIndex >= 0 || undefined}>
      {blocks.map((block, index) => (
        <AgentBlock
          key={block.id}
          block={block}
          onApprovalDecision={onApprovalDecision}
          sessionId={sessionId}
          streamingTail={index === tailIndex}
        />
      ))}
    </div>
  );
}

export const AgentBlock = memo(function AgentBlock({
  block,
  onApprovalDecision,
  sessionId = '',
  streamingTail = false,
}: {
  block: UiAgentBlock;
  onApprovalDecision?: AgentBlocksProps['onApprovalDecision'];
  sessionId?: string;
  streamingTail?: boolean;
}) {
  const descriptor = agentRendererPolicy(block.type);
  const Renderer = descriptor?.Renderer ?? UnknownBlockRenderer;
  return (
    <Renderer
      block={block}
      onApprovalDecision={onApprovalDecision}
      sessionId={sessionId}
      streamingTail={streamingTail}
    />
  );
});

function findLastTextBlock(blocks: readonly UiAgentBlock[]) {
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    const block = blocks[index];
    if (
      block?.type === 'text'
      && block.status === 'running'
      && typeof (block.data.text ?? block.data.markdown) === 'string'
      && String(block.data.text ?? block.data.markdown)
    ) {
      return index;
    }
  }
  return -1;
}
