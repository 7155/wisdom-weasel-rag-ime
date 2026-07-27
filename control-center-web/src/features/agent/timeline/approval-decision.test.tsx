import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AgentBlocks } from './BlockRenderer';

/*
 * Regression cover for a real production defect: AgentTimeline received
 * onApprovalDecision and forwarded it to activity groups, but the ordinary
 * assistant-message path (AgentTurn -> MessageView -> AgentBlocks) never
 * threaded it. An approval arriving inside a normal message therefore
 * rendered with no Reject/Approve controls at all.
 */
const HASH = 'b3f1c2a9d4e5a7160c83f92d418be5cf0a2d7e64913b8ac5de07f21649a3bd8e';

function approvalBlock(state = 'pending', approvalId = 'apr-1') {
  return [{
    id: 'block-approval',
    type: 'approval' as const,
    status: 'completed' as const,
    presentationKind: 'interactive' as const,
    data: {
      approvalId,
      title: '写入词表草案',
      detail: '需要你确认后才会写入本机词库。',
      state,
      payloadSha256: HASH,
    },
  }];
}

afterEach(cleanup);

describe('approval decisions inside ordinary assistant messages', () => {
  it('invokes the decision callback with id, decision and hash when approving', async () => {
    const onApprovalDecision = vi.fn();
    const user = userEvent.setup();
    render(<AgentBlocks blocks={approvalBlock()} sessionId="s1" onApprovalDecision={onApprovalDecision} />);

    await user.click(screen.getByRole('button', { name: '批准' }));

    expect(onApprovalDecision).toHaveBeenCalledTimes(1);
    expect(onApprovalDecision).toHaveBeenCalledWith('apr-1', 'approved', HASH);
  });

  it('invokes the decision callback with id, decision and hash when rejecting', async () => {
    const onApprovalDecision = vi.fn();
    const user = userEvent.setup();
    render(<AgentBlocks blocks={approvalBlock()} sessionId="s1" onApprovalDecision={onApprovalDecision} />);

    await user.click(screen.getByRole('button', { name: '拒绝' }));

    expect(onApprovalDecision).toHaveBeenCalledWith('apr-1', 'rejected', HASH);
  });

  it('cannot submit twice while the projection catches up', async () => {
    const onApprovalDecision = vi.fn();
    const user = userEvent.setup();
    render(<AgentBlocks blocks={approvalBlock()} sessionId="s1" onApprovalDecision={onApprovalDecision} />);

    const approve = screen.getByRole('button', { name: '批准' });
    await user.click(approve);
    await user.click(approve);
    await user.click(screen.getByRole('button', { name: '拒绝' }));

    expect(onApprovalDecision).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: '已批准' })).toBeDisabled();
  });

  it('releases the latch when a new approval reuses the same position', async () => {
    const onApprovalDecision = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(
      <AgentBlocks blocks={approvalBlock('pending', 'apr-1')} sessionId="s1" onApprovalDecision={onApprovalDecision} />,
    );

    await user.click(screen.getByRole('button', { name: '批准' }));
    expect(screen.getByRole('button', { name: '已批准' })).toBeDisabled();

    // Same component position, different approval: React reuses the instance,
    // so a latch tied only to instance state would render the new approval as
    // already decided and trap the user.
    rerender(
      <AgentBlocks blocks={approvalBlock('pending', 'apr-2')} sessionId="s1" onApprovalDecision={onApprovalDecision} />,
    );

    const approve = screen.getByRole('button', { name: '批准' });
    expect(approve).toBeEnabled();
    await user.click(approve);
    expect(onApprovalDecision).toHaveBeenLastCalledWith('apr-2', 'approved', HASH);
  });

  it('offers no controls once the approval is already decided', () => {
    const onApprovalDecision = vi.fn();
    render(<AgentBlocks blocks={approvalBlock('approved')} sessionId="s1" onApprovalDecision={onApprovalDecision} />);

    expect(screen.queryByRole('button', { name: '批准' })).toBeNull();
    expect(screen.queryByRole('button', { name: '拒绝' })).toBeNull();
  });
});
