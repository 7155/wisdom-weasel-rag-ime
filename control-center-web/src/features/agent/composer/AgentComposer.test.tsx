import { fireEvent, render, screen, within } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { TooltipProvider } from '@/components/primitives';
import type { CapabilityCatalog } from '@/features/plugins/capability-policy';
import { previewSessions } from '../preview-data';
import type { ToolManifest } from '../types';
import { AgentComposer } from './AgentComposer';

describe('AgentComposer macOS input methods', () => {
  it('keeps marked text local until composition ends and does not send the commit key', () => {
    const onDraftChange = vi.fn();
    const onSend = vi.fn();

    function Harness() {
      const [draft, setDraft] = useState('');
      return (
        <TooltipProvider>
          <AgentComposer
            draft={draft}
            attachments={[]}
            session={previewSessions[0]}
            commands={[]}
            tools={[]}
            toolCatalogStatus="ready"
            busy={false}
            sending={false}
            onDraftChange={(value) => { onDraftChange(value); setDraft(value); }}
            onAttachmentsChange={() => {}}
            onPickAttachments={() => {}}
            onPasteImages={() => {}}
            onToolSelect={() => {}}
            onProductCommand={() => {}}
            onSend={onSend}
            onStop={() => {}}
            onPermissionChange={() => {}}
            onWorkspaceRootsChange={() => {}}
            onModelChange={() => {}}
          />
        </TooltipProvider>
      );
    }

    render(<Harness />);
    const composer = screen.getByRole('textbox', { name: '消息' });

    expect(composer).toHaveAttribute('autocapitalize', 'none');
    expect(composer).toHaveAttribute('autocomplete', 'off');
    expect(composer).toHaveAttribute('autocorrect', 'off');
    expect(composer).toHaveAttribute('spellcheck', 'false');
    expect(composer).toHaveAttribute('aria-expanded', 'false');

    fireEvent.compositionStart(composer);
    fireEvent.change(composer, { target: { value: 'jinr' } });
    expect(composer).toHaveValue('jinr');
    expect(onDraftChange).not.toHaveBeenCalled();

    fireEvent.keyDown(composer, { key: 'Enter', code: 'Enter', keyCode: 229, isComposing: false });
    expect(onSend).not.toHaveBeenCalled();

    fireEvent.change(composer, { target: { value: '今儿' } });
    fireEvent.compositionEnd(composer, { data: '今儿' });
    expect(onDraftChange).toHaveBeenLastCalledWith('今儿');
    expect(composer).toHaveValue('今儿');

    fireEvent.keyDown(composer, { key: 'Enter', code: 'Enter' });
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend).toHaveBeenLastCalledWith('prompt', '今儿');
  });

  it('labels the capability picker and provides an explicit close target', () => {
    const tool: ToolManifest = {
      schemaVersion: 'rag-ime.control-tool-manifest.v1',
      id: 'planning',
      domain: 'planning',
      displayName: '规划与任务',
      description: '查看每日计划',
      category: 'planning',
      riskLevel: 'R1',
      sessionModes: ['coordinator'],
      operations: ['dashboard'],
      resultPresentation: 'status',
      availability: 'online',
      version: '1',
    };
    const capabilityCatalog: CapabilityCatalog = {
      schemaVersion: 'rag-ime.capability-catalog.v1',
      ok: true,
      revision: 'catalog-1',
      effectiveAtMs: 1,
      projectScope: {
        supported: false,
        identityKind: 'none',
        reason: 'No project scope in this focused picker test.',
      },
      sessionPolicy: {
        sessionId: previewSessions[0].id,
        policyRevision: 1,
        disclosurePreferences: {
          globalDefault: {},
          projectDefault: {},
          session: {},
          effective: { 'tool:planning': 'enabled' },
        },
        effectiveAtMs: 1,
      },
      items: [{
        id: tool.id,
        canonicalId: 'tool:planning',
        kind: 'tool',
        displayName: tool.displayName,
        description: tool.description,
        source: { kind: 'built_in', label: 'Control Center' },
        status: 'available',
        risk: tool.riskLevel,
        requiredPermissions: [],
        authorization: { state: 'authorized', reason: 'Focused picker test fixture.' },
        disclosure: {
          preference: 'inherit',
          effective: 'enabled',
          state: 'disclosed',
          reason: 'Focused picker test fixture.',
        },
        effectiveScope: 'built_in_default',
        reasons: [],
        revision: 'capability-1',
        effectiveAtMs: 1,
      }],
    };
    render(
      <TooltipProvider>
        <AgentComposer
          draft=""
          attachments={[]}
          session={previewSessions[0]}
          commands={[]}
          capabilityCatalog={capabilityCatalog}
          tools={[tool]}
          toolCatalogStatus="ready"
          busy={false}
          sending={false}
          onDraftChange={() => {}}
          onAttachmentsChange={() => {}}
          onPickAttachments={() => {}}
          onPasteImages={() => {}}
          onToolSelect={() => {}}
          onProductCommand={() => {}}
          onSend={() => {}}
          onStop={() => {}}
          onPermissionChange={() => {}}
          onWorkspaceRootsChange={() => {}}
          onModelChange={() => {}}
        />
      </TooltipProvider>,
    );

    const trigger = screen.getByRole('button', { name: '这段对话可用工具：1 个' });
    fireEvent.click(trigger);
    const dialog = screen.getByRole('dialog', { name: '当前对话能力' });
    expect(within(dialog).getByRole('combobox', { name: '规划与任务的当前对话披露' })).toBeInTheDocument();
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    fireEvent.click(within(dialog).getByRole('button', { name: '关闭当前对话能力' }));
    expect(screen.queryByRole('dialog', { name: '当前对话能力' })).not.toBeInTheDocument();
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
  });

  it('keeps responsive controls together while the send action stays fixed', () => {
    const onJumpLatest = vi.fn();
    const { container } = render(
      <TooltipProvider>
        <AgentComposer
          draft="准备发送"
          attachments={[]}
          session={previewSessions[0]}
          commands={[]}
          tools={[]}
          toolCatalogStatus="ready"
          imageSupport="supported"
          busy={false}
          sending={false}
          showJumpLatest
          onJumpLatest={onJumpLatest}
          onDraftChange={() => {}}
          onAttachmentsChange={() => {}}
          onPickAttachments={() => {}}
          onPasteImages={() => {}}
          onToolSelect={() => {}}
          onProductCommand={() => {}}
          onSend={() => {}}
          onStop={() => {}}
          onPermissionChange={() => {}}
          onWorkspaceRootsChange={() => {}}
          onModelChange={() => {}}
        />
      </TooltipProvider>,
    );

    const controls = container.querySelector('.agent-composer__controls');
    const view = within(container);
    const send = view.getByRole('button', { name: '发送' });
    expect(controls).toContainElement(view.getByRole('button', { name: '添加图片' }));
    expect(controls).toContainElement(view.getByRole('button', { name: /对话权限/ }));
    expect(controls).toContainElement(view.getByRole('button', { name: /这段对话可用工具/ }));
    expect(controls).not.toContainElement(send);
    expect(send.closest('.agent-composer__toolbar')).not.toBeNull();
    expect(view.queryByRole('button', { name: '打开命令面板' })).not.toBeInTheDocument();
    const jumpLatest = view.getByRole('button', { name: '回到最新' });
    expect(jumpLatest.closest('.agent-composer-wrap')).not.toBeNull();
    expect(jumpLatest.closest('.agent-composer')).toBeNull();
    fireEvent.click(jumpLatest);
    expect(onJumpLatest).toHaveBeenCalledTimes(1);
  });

  it('uses double Escape to request an in-place edit without disturbing IME input', () => {
    const onEditPrevious = vi.fn();
    const { container } = render(
      <TooltipProvider>
        <AgentComposer
          draft=""
          attachments={[]}
          session={previewSessions[0]}
          commands={[]}
          tools={[]}
          toolCatalogStatus="ready"
          busy={false}
          sending={false}
          onDraftChange={() => {}}
          onAttachmentsChange={() => {}}
          onPickAttachments={() => {}}
          onPasteImages={() => {}}
          onToolSelect={() => {}}
          onProductCommand={() => {}}
          onSend={() => {}}
          onStop={() => {}}
          onEditPrevious={onEditPrevious}
          onPermissionChange={() => {}}
          onWorkspaceRootsChange={() => {}}
          onModelChange={() => {}}
        />
      </TooltipProvider>,
    );
    const composer = within(container).getByRole('textbox', { name: '消息' });
    fireEvent.keyDown(composer, { key: 'Escape' });
    expect(onEditPrevious).not.toHaveBeenCalled();
    fireEvent.keyDown(composer, { key: 'Escape' });
    expect(onEditPrevious).toHaveBeenCalledTimes(1);
  });

  it('sends native steering and follow-up messages while keeping stop separate', () => {
    const onSend = vi.fn();
    const onStop = vi.fn();
    const { container } = render(
      <TooltipProvider>
        <AgentComposer
          draft="补充要求"
          attachments={[]}
          session={previewSessions[0]}
          commands={[]}
          tools={[]}
          toolCatalogStatus="ready"
          imageSupport="supported"
          busy
          sending={false}
          onDraftChange={() => {}}
          onAttachmentsChange={() => {}}
          onPickAttachments={() => {}}
          onPasteImages={() => {}}
          onToolSelect={() => {}}
          onProductCommand={() => {}}
          onSend={onSend}
          onStop={onStop}
          onPermissionChange={() => {}}
          onWorkspaceRootsChange={() => {}}
          onModelChange={() => {}}
        />
      </TooltipProvider>,
    );

    const view = within(container);
    const composer = view.getByRole('textbox', { name: '消息' });
    fireEvent.keyDown(composer, { key: 'Enter', code: 'Enter' });
    expect(onSend).toHaveBeenLastCalledWith('steer', '补充要求');

    fireEvent.change(composer, { target: { value: '补充要求' } });
    fireEvent.click(view.getByRole('radio', { name: '接续' }));
    fireEvent.keyDown(composer, { key: 'Enter', code: 'Enter' });
    expect(onSend).toHaveBeenLastCalledWith('followUp', '补充要求');

    fireEvent.change(composer, { target: { value: '补充要求' } });
    fireEvent.keyDown(composer, { key: 'Enter', code: 'Enter', altKey: true });
    expect(onSend).toHaveBeenLastCalledWith('followUp', '补充要求');
    fireEvent.click(view.getByRole('button', { name: '停止本轮' }));
    expect(onStop).toHaveBeenCalledTimes(1);
    expect(view.getByRole('button', { name: '添加图片' })).toBeEnabled();
  });
});
