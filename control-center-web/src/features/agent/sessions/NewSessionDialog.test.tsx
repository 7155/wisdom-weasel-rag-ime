import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { NewSessionDialog } from './NewSessionDialog';

describe('NewSessionDialog', () => {
  it('creates an ordinary conversation without requiring a project', async () => {
    const user = userEvent.setup();
    const onCreate = vi.fn().mockResolvedValue(true);
    render(
      <NewSessionDialog
        open
        projects={[]}
        defaultRoots={[]}
        onOpenChange={() => {}}
        onPickRoots={vi.fn().mockResolvedValue(null)}
        onCreate={onCreate}
      />,
    );

    const dialog = screen.getByRole('dialog', { name: '新建对话' });
    expect(within(dialog).getByRole('radio', { name: /不预选项目/ })).toBeChecked();
    expect(within(dialog).getAllByRole('radio', { name: /只读|完全访问|工作区托管|全自动/ })).toHaveLength(4);
    expect(within(dialog).getByRole('radio', { name: /全自动/ })).toBeEnabled();
    expect(within(dialog).getByText('只允许查看、搜索、分析，以及隔离无网络的只读验证命令；写入与应用动作阻止')).toBeVisible();
    await user.click(within(dialog).getByRole('radio', { name: /^完全访问/ }));
    expect(within(dialog).getByText('路径不限，所有工具动作直接执行，无需人工或模型逐项批准')).toBeVisible();
    await user.click(within(dialog).getByRole('button', { name: '开始对话' }));

    expect(onCreate).toHaveBeenCalledWith({
      title: '新对话',
      workspaceRoots: [],
      executionMode: 'per_action',
      toolProfileVersion: 'control-center-full-access-v1',
    });
  });

  it('does not treat the system root as a project-scoped workspace', () => {
    render(
      <NewSessionDialog
        open
        projects={['/']}
        defaultRoots={['/']}
        onOpenChange={() => {}}
        onPickRoots={vi.fn().mockResolvedValue(null)}
        onCreate={vi.fn().mockResolvedValue(true)}
      />,
    );

    const dialog = screen.getByRole('dialog', { name: '新建对话' });
    const projects = within(dialog).getByRole('radiogroup', { name: '对话的起始项目' });
    expect(within(projects).getAllByRole('radio')).toHaveLength(1);
    expect(within(projects).getByRole('radio', { name: /不预选项目/ })).toBeChecked();
    expect(within(dialog).getByRole('radio', { name: /工作区托管/ })).toBeDisabled();
  });

  it('creates a workspace-managed conversation with an explicit scope receipt', async () => {
    const user = userEvent.setup();
    const onCreate = vi.fn().mockResolvedValue(true);
    render(
      <NewSessionDialog
        open
        projects={['/Volumes/work/learnA']}
        defaultRoots={['/Volumes/work/learnA']}
        onOpenChange={() => {}}
        onPickRoots={vi.fn().mockResolvedValue(null)}
        onCreate={onCreate}
      />,
    );

    const dialog = screen.getByRole('dialog', { name: '新建对话' });
    await user.click(within(dialog).getByRole('radio', { name: /工作区托管/ }));
    await user.click(within(dialog).getByRole('button', { name: '开始对话' }));

    expect(onCreate).toHaveBeenCalledWith({
      title: '新对话',
      workspaceRoots: ['/Volumes/work/learnA'],
      executionMode: 'workspace_managed',
      toolProfileVersion: 'control-center-v1',
      workspaceScopeConfirmed: true,
    });
  });

  it('creates a full-automation project conversation with one explicit action', async () => {
    const user = userEvent.setup();
    const onCreate = vi.fn().mockResolvedValue(true);
    render(
      <NewSessionDialog
        open
        projects={['/Volumes/work/learnA']}
        defaultRoots={['/Volumes/work/learnA']}
        onOpenChange={() => {}}
        onPickRoots={vi.fn().mockResolvedValue(null)}
        onCreate={onCreate}
      />,
    );
    const dialog = screen.getByRole('dialog', { name: '新建对话' });
    const fullAutomation = within(dialog).getByRole('radio', { name: /全自动/ });
    expect(fullAutomation).toBeEnabled();
    await user.click(fullAutomation);
    await user.click(within(dialog).getByRole('button', { name: '启用全自动并开始' }));

    expect(onCreate).toHaveBeenCalledWith({
      title: '新对话',
      workspaceRoots: ['/Volumes/work/learnA'],
      executionMode: 'full_trust',
      toolProfileVersion: 'control-center-auto-approve-v1',
      dangerousModeConfirmed: true,
    });
  });

  it('creates under the selected existing project', async () => {
    const user = userEvent.setup();
    const onCreate = vi.fn().mockResolvedValue(true);
    render(
      <NewSessionDialog
        open
        projects={['/Volumes/work/learnA']}
        defaultRoots={['/Volumes/work/learnA']}
        onOpenChange={() => {}}
        onPickRoots={vi.fn().mockResolvedValue(null)}
        onCreate={onCreate}
      />,
    );

    const dialog = screen.getByRole('dialog', { name: '新建对话' });
    await user.type(within(dialog).getByPlaceholderText('新对话'), '整理 RAG 工具');
    await user.click(within(dialog).getByRole('radio', { name: /learnA/ }));
    await user.click(within(dialog).getByRole('button', { name: '开始对话' }));

    expect(onCreate).toHaveBeenCalledWith({
      title: '整理 RAG 工具',
      workspaceRoots: ['/Volumes/work/learnA'],
      executionMode: 'per_action',
      toolProfileVersion: 'control-center-full-access-v1',
    });
  });

  it('can return from a project-bound default to direct chat', async () => {
    const user = userEvent.setup();
    const onCreate = vi.fn().mockResolvedValue(true);
    render(
      <NewSessionDialog
        open
        projects={['/Volumes/work/learnA']}
        defaultRoots={['/Volumes/work/learnA']}
        onOpenChange={() => {}}
        onPickRoots={vi.fn().mockResolvedValue(null)}
        onCreate={onCreate}
      />,
    );

    const dialog = screen.getByRole('dialog', { name: '新建对话' });
    expect(within(dialog).getByRole('radio', { name: /learnA/ })).toBeChecked();
    await user.click(within(dialog).getByRole('radio', { name: /不预选项目/ }));
    await user.click(within(dialog).getByRole('button', { name: '开始对话' }));

    expect(onCreate).toHaveBeenCalledWith({
      title: '新对话',
      workspaceRoots: [],
      executionMode: 'per_action',
      toolProfileVersion: 'control-center-full-access-v1',
    });
  });
});
