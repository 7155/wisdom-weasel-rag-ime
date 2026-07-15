import { fireEvent, render, screen } from '@testing-library/react';
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
            onSend={onSend}
            onStop={() => {}}
            onModeChange={() => {}}
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
});
