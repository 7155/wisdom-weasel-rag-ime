import type { ComponentType } from 'react';
import type { UiAgentBlock } from '@/contracts/ui-events';

export interface AgentBlockRenderProps {
  block: UiAgentBlock;
  onApprovalDecision?: (
    approvalId: string,
    decision: 'approved' | 'rejected',
    hash: string,
  ) => void;
  sessionId: string;
  streamingTail: boolean;
}

export type AgentBlockRenderer = ComponentType<AgentBlockRenderProps>;
