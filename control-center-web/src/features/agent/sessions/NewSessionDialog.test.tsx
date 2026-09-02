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
    expect(within(dialog).getByRole('radio', { name: /全自动/ })).toBeEnabled();
    await user.click(within(dialog).getByRole('button', { name: '开始对话' }));

    expect(onCreate).toHaveBeenCalledWith({
      title: '新对话',
      workspaceRoots: [],
      executionMode: 'per_action',
      toolProfileVersion: 'control-center-full-access-v1',
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
