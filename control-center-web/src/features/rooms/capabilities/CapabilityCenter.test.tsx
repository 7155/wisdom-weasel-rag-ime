import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { capabilityCenterFixture } from './capability-center-fixtures';
import { CapabilityCenter } from './CapabilityCenter';
import { ParticipantBindingInspector } from './ParticipantBindingInspector';
import { RoomExecutionTopology } from './RoomExecutionTopology';

describe('Capability Center', () => {
  afterEach(cleanup);

  it('renders all six authoritative states and layer narrowing receipts', async () => {
    const user = userEvent.setup();
    const fixture = capabilityCenterFixture();
    render(<CapabilityCenter projection={fixture.projection} sessionId="session-room-research" />);

    const center = screen.getByRole('region', { name: '能力中心' });
    for (const state of ['available', 'authorized', 'disclosed', 'loaded', 'invoked', 'revoked']) {
      expect(center).toHaveTextContent(state);
    }
    await user.click(screen.getByRole('button', { name: /知识检索/ }));
    expect(center).toHaveTextContent('角色书移除 control');
    expect(center).toHaveTextContent('manifest-r8');
    expect(center).toHaveTextContent('knowledge.search');
    expect(center).toHaveTextContent('context-r12');
  });

  it('supports keyboard inspection without exposing mutation actions', async () => {
    const user = userEvent.setup();
    const fixture = capabilityCenterFixture();
    render(<CapabilityCenter projection={fixture.projection} sessionId="session-room-research" />);

    await user.tab();
    expect(screen.getByRole('button', { name: /长期记忆写入/ })).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(screen.getByRole('button', { name: /长期记忆写入/ })).toHaveAttribute('aria-expanded', 'true');
    expect(screen.queryByRole('button', { name: /activate|rollback|revoke|启用|回滚|撤销/i })).not.toBeInTheDocument();
  });

  it('hides Room binding noise for an ordinary Agent binding', () => {
    const fixture = capabilityCenterFixture();
    render(<ParticipantBindingInspector binding={fixture.projection.bindingsBySessionId['session-ordinary']!} />);

    expect(screen.getByRole('region', { name: 'Participant Binding 检查器' })).toHaveTextContent('session-ordinary');
    expect(screen.queryByText('Room Binding')).not.toBeInTheDocument();
    expect(screen.queryByText('room-binding-a')).not.toBeInTheDocument();
  });

  it('keeps concurrent Root Task and Dispatch projections visibly separate', () => {
    const fixture = capabilityCenterFixture();
    render(<RoomExecutionTopology
      roots={[
        { rootId: 'root-research', generation: 3, state: 'running', isFinal: false },
        { rootId: 'root-review', generation: 1, state: 'waiting', isFinal: false },
      ]}
      tasksByRootId={fixture.tasksByRootId}
      dispatchesByRootId={fixture.dispatchesByRootId}
    />);

    expect(screen.getByRole('region', { name: 'root-research Tasks' })).toHaveTextContent('核对 Room 路由和能力回执');
    expect(screen.getByRole('region', { name: 'root-research Dispatches' })).toHaveTextContent('dispatch-research-attempt-2');
    expect(screen.getByRole('region', { name: 'root-review Tasks' })).not.toHaveTextContent('task-verify-room-routing');
  });
});
