import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TooltipProvider } from '@/components/primitives';
import { AgentComposer } from './AgentComposer';

afterEach(cleanup);

describe('AgentComposer project instructions', () => {
  it('lets the user disable Pi project context for the current session', async () => {
    const onProjectContextChange = vi.fn();
    const user = userEvent.setup();
    render(
      <TooltipProvider>
        <AgentComposer
          draft=""
          attachments={[]}
          session={{
            id: 'session-1',
            title: '测试',
            mode: 'coordinator',
            status: 'idle',
            roleId: 'zhiyou-v1',
            roleVersion: '1',
            roleBookRevisionId: 'role-book-revision-1',
            updatedAtMs: 1,
            workspaceRoots: ['/tmp/project'],
            projectContextEnabled: true,
          }}
          commands={[]}
          tools={[]}
          toolCatalogStatus="ready"
          busy={false}
          sending={false}
          onDraftChange={vi.fn()}
          onAttachmentsChange={vi.fn()}
          onPickAttachments={vi.fn()}
          onPasteImages={vi.fn()}
          onToolSelect={vi.fn()}
          onProductCommand={vi.fn()}
          onSend={vi.fn()}
          onStop={vi.fn()}
          onPermissionChange={vi.fn()}
          onWorkspaceRootsChange={vi.fn()}
          onProjectContextChange={onProjectContextChange}
          onModelChange={vi.fn()}
        />
      </TooltipProvider>,
    );

    await user.click(screen.getByRole('button', { name: '项目指令：已加载' }));
    await user.click(screen.getByRole('switch', { name: '加载 AGENTS.md / CLAUDE.md' }));

    expect(onProjectContextChange).toHaveBeenCalledWith(false);
  });
});
