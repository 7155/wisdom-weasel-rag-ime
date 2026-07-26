import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { TooltipProvider } from '@/components/primitives';
import { RoomComposer } from './RoomComposer';

describe('RoomComposer macOS input methods', () => {
  it('keeps marked text local and does not send the IME commit key', () => {
    const onDraftChange = vi.fn();
    const onSend = vi.fn();

    function Harness() {
      const [draft, setDraft] = useState('');
      return (
        <TooltipProvider>
          <RoomComposer
            room={{
              id: 'room-1',
              status: 'active',
              roomKind: 'collaboration',
              participants: [{
                id: 'participant-1',
                sessionId: 'session-1',
                roleId: 'companion-present-v1',
                roleVersion: '1',
                displayName: '智鼬',
                status: 'active',
              }],
            }}
            personas={[]}
            draft={draft}
            sending={false}
            onDraftChange={(value) => {
              onDraftChange(value);
              setDraft(value);
            }}
            onSend={onSend}
          />
        </TooltipProvider>
      );
    }

    render(<Harness />);
    const composer = screen.getByRole('textbox', { name: '协作消息' });
    expect(composer).toHaveAttribute('autocapitalize', 'none');
    expect(composer).toHaveAttribute('autocomplete', 'off');
    expect(composer).toHaveAttribute('autocorrect', 'off');
    expect(composer).toHaveAttribute('spellcheck', 'false');

    fireEvent.compositionStart(composer);
    fireEvent.change(composer, { target: { value: 'duiq' } });
    expect(composer).toHaveValue('duiq');
    expect(onDraftChange).not.toHaveBeenCalled();

    fireEvent.keyDown(composer, {
      key: 'Enter',
      code: 'Enter',
      keyCode: 229,
      isComposing: false,
    });
    expect(onSend).not.toHaveBeenCalled();

    fireEvent.change(composer, { target: { value: '对齐' } });
    fireEvent.compositionEnd(composer, { data: '对齐' });
    expect(onDraftChange).toHaveBeenLastCalledWith('对齐');
    expect(composer).toHaveValue('对齐');

    fireEvent.keyDown(composer, { key: 'Enter', code: 'Enter' });
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend).toHaveBeenLastCalledWith('对齐');
  });
});
