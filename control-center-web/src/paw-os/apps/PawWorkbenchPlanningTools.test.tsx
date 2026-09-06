import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PawWorkbenchPlanningTools } from './PawWorkbenchPlanningTools';

afterEach(cleanup);

describe('Workbench selected task handoff', () => {
  it('uses the selected task title, description and exact id in its draft', async () => {
    const onOpenAgent = vi.fn();
    const first = { id: 'first-task', title: '首项任务', status: 'active' };
    const selected = { id: 'chosen-task', title: '选中的工作', detail: '先核对实际来源。', status: 'todo' };
    render(<PawWorkbenchPlanningTools date="2026-09-05" onDateChange={vi.fn()} onOpenAgent={onOpenAgent} planning={{ tasks: [first, selected] }} projectName="PAW" projectPath="/work/paw" selectedTask={selected} />);
    await userEvent.click(screen.getByRole('button', { name: '拆解当前任务' }));
    expect(onOpenAgent).toHaveBeenCalledWith(expect.stringContaining('选中的工作（chosen-task）'));
    expect(onOpenAgent).toHaveBeenCalledWith(expect.stringContaining('先核对实际来源。'));
    expect(onOpenAgent.mock.calls[0]?.[0]).not.toContain('首项任务');
  });

  it('does not silently substitute the first task for an explicit empty selection', () => {
    render(<PawWorkbenchPlanningTools date="2026-09-05" onDateChange={vi.fn()} onOpenAgent={vi.fn()} planning={{ tasks: [{ id: 'first-task', title: '首项任务' }] }} projectName="PAW" projectPath="/work/paw" selectedTask={null} />);
    expect(screen.getByRole('button', { name: '拆解当前任务' })).toBeDisabled();
  });
});
