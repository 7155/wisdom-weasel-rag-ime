import { fireEvent, render, screen, within } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { TooltipProvider } from '@/components/primitives';
import { previewSessions } from '../preview-data';
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
  });

  it('keeps responsive controls together while the send action stays fixed', () => {
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
    expect(controls).toContainElement(view.getByRole('button', { name: /当前权限可用工具/ }));
    expect(controls).not.toContainElement(send);
    expect(send.closest('.agent-composer__toolbar')).not.toBeNull();
    expect(view.queryByRole('button', { name: '打开命令面板' })).not.toBeInTheDocument();
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
    expect(onSend).toHaveBeenLastCalledWith('steer');

    fireEvent.click(view.getByRole('radio', { name: '接续' }));
    fireEvent.keyDown(composer, { key: 'Enter', code: 'Enter' });
    expect(onSend).toHaveBeenLastCalledWith('followUp');

    fireEvent.keyDown(composer, { key: 'Enter', code: 'Enter', altKey: true });
    expect(onSend).toHaveBeenLastCalledWith('followUp');
    fireEvent.click(view.getByRole('button', { name: '停止本轮' }));
    expect(onStop).toHaveBeenCalledTimes(1);
    expect(view.getByRole('button', { name: '添加图片' })).toBeEnabled();
  });
});
