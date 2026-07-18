import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TooltipProvider } from '@/components/primitives';
import { AgentComposer } from './AgentComposer';

afterEach(cleanup);

describe('AgentComposer context resources', () => {
  it('controls project instructions, Pi Skills, and Codex Skills independently', async () => {
    const onProjectContextChange = vi.fn();
    const onPiSkillsChange = vi.fn();
    const onCodexSkillsChange = vi.fn();
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
          onProjectContextChange={onProjectContextChange}
          onPiSkillsChange={onPiSkillsChange}
          onCodexSkillsChange={onCodexSkillsChange}
          onModelChange={vi.fn()}
        />
      </TooltipProvider>,
    );

    await user.click(screen.getByRole('button', { name: '项目指令：已加载' }));
    await user.click(screen.getByRole('switch', { name: '加载 AGENTS.md / CLAUDE.md' }));
    await user.click(screen.getByRole('switch', { name: '加载 Pi Skills' }));
    await user.click(screen.getByRole('switch', { name: '加载 Codex Skills' }));

    expect(onProjectContextChange).toHaveBeenCalledWith(false);
    expect(onPiSkillsChange).toHaveBeenCalledWith(true);
    expect(onCodexSkillsChange).toHaveBeenCalledWith(true);
  });
});
