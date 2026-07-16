import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { NewSessionDialog } from './NewSessionDialog';

describe('NewSessionDialog', () => {
  it('requires a project path before creating a task', async () => {
    const user = userEvent.setup();
    const onPickRoots = vi.fn().mockResolvedValue(null);
    const onCreate = vi.fn().mockResolvedValue(true);
    render(
      <NewSessionDialog
        open
        projects={[]}
        defaultRoots={[]}
        onOpenChange={() => {}}
        onPickRoots={onPickRoots}
        onCreate={onCreate}
      />,
    );

    const dialog = screen.getByRole('dialog', { name: '新建任务' });
    expect(within(dialog).getByRole('button', { name: '创建任务' })).toBeDisabled();
    await user.click(within(dialog).getByRole('button', { name: '选择项目目录' }));
    expect(onPickRoots).toHaveBeenCalledOnce();
    expect(onCreate).not.toHaveBeenCalled();
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

    const dialog = screen.getByRole('dialog', { name: '新建任务' });
    await user.type(within(dialog).getByPlaceholderText('新任务'), '整理 RAG 工具');
    await user.click(within(dialog).getByRole('button', { name: '创建任务' }));

    expect(onCreate).toHaveBeenCalledWith({
      title: '整理 RAG 工具',
      workspaceRoots: ['/Volumes/work/learnA'],
    });
  });
});
