import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TooltipProvider } from '@/components/primitives';
import { AgentComposer } from './AgentComposer';

afterEach(cleanup);

describe('AgentComposer context resources', () => {
  it('selects one atomic resource profile through the shared catalog entry', async () => {
    const onContextResourcesChange = vi.fn();
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
            roleId: 'companion-present-v1',
            roleVersion: '1',
            roleBookRevisionId: 'role-book-revision-1',
            updatedAtMs: 1,
            workspaceRoots: ['/tmp/project'],
            projectContextEnabled: true,
            piSkillsEnabled: false,
            codexSkillsEnabled: false,
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
          onContextResourcesChange={onContextResourcesChange}
          onModelChange={vi.fn()}
        />
      </TooltipProvider>,
    );

    await user.click(screen.getByRole('button', { name: '工作资料：当前项目' }));
    await user.click(screen.getByRole('radio', { name: /本机扩展/ }));

    expect(onContextResourcesChange).toHaveBeenCalledWith({
      projectContextEnabled: true,
      piSkillsEnabled: true,
      codexSkillsEnabled: true,
    });
  });
});
