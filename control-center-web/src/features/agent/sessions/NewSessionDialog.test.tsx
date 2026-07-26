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
    expect(within(dialog).getByRole('radio', { name: /直接聊天/ })).toBeChecked();
    await user.click(within(dialog).getByRole('button', { name: '开始对话' }));

    expect(onCreate).toHaveBeenCalledWith({
      title: '新对话',
      workspaceRoots: [],
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
    await user.click(within(dialog).getByRole('radio', { name: /直接聊天/ }));
    await user.click(within(dialog).getByRole('button', { name: '开始对话' }));

    expect(onCreate).toHaveBeenCalledWith({
      title: '新对话',
      workspaceRoots: [],
    });
  });
});
