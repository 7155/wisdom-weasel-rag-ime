import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { TooltipProvider } from '@/components/primitives';
import { RoomComposer } from './RoomComposer';

afterEach(cleanup);

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
                displayName: '澄',
                status: 'active',
              }],
            }}
            personas={[]}
            draft={draft}
            attachments={[]}
            sending={false}
            onDraftChange={(value) => {
              onDraftChange(value);
              setDraft(value);
            }}
            onAttachmentsChange={vi.fn()}
            onPasteImages={vi.fn()}
            onPasteFromClipboard={vi.fn()}
            onPickAttachments={vi.fn()}
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

  it('imports a clipboard File and invokes native fallback for an empty WebKit paste', () => {
    const onPasteImages = vi.fn();
    const onPasteFromClipboard = vi.fn();
    const image = new File(['png'], 'diagram.png', { type: 'image/png' });
    render(
      <TooltipProvider>
        <RoomComposer
          room={{ id: 'room-1', status: 'active', participants: [] }}
          personas={[]}
          draft=""
          attachments={[]}
          sending={false}
          onDraftChange={vi.fn()}
          onAttachmentsChange={vi.fn()}
          onPasteImages={onPasteImages}
          onPasteFromClipboard={onPasteFromClipboard}
          onPickAttachments={vi.fn()}
          onSend={vi.fn()}
        />
      </TooltipProvider>,
    );
    const composer = screen.getByRole('textbox', { name: '协作消息' });
    expect(fireEvent.paste(composer, {
      clipboardData: { files: [image], items: [], getData: () => '' },
    })).toBe(false);
    expect(onPasteImages).toHaveBeenCalledWith([image]);
    expect(fireEvent.paste(composer, {
      clipboardData: { files: [], items: [], getData: () => '' },
    })).toBe(false);
    expect(onPasteFromClipboard).toHaveBeenCalledTimes(1);
  });

  it('renders a removable managed attachment chip', () => {
    const onAttachmentsChange = vi.fn();
    render(
      <TooltipProvider>
        <RoomComposer
          room={{ id: 'room-1', status: 'active', participants: [] }}
          personas={[]}
          draft=""
          attachments={[{
            mediaId: 'media_room_attachment01',
            roomId: 'room-1',
            fileName: 'diagram.png',
            mimeType: 'image/png',
            byteSize: 128,
            sha256: 'a'.repeat(64),
          }]}
          sending={false}
          onDraftChange={vi.fn()}
          onAttachmentsChange={onAttachmentsChange}
          onPasteImages={vi.fn()}
          onPasteFromClipboard={vi.fn()}
          onPickAttachments={vi.fn()}
          onSend={vi.fn()}
        />
      </TooltipProvider>,
    );
    fireEvent.click(screen.getByRole('button', { name: '移除图片：diagram.png' }));
    expect(onAttachmentsChange).toHaveBeenCalledWith([]);
  });

  it('offers native steer while a task is busy and keeps pending answers constrained', () => {
    const onSend = vi.fn();
    const common = {
      room: {
        id: 'room-1',
        status: 'active',
        roomKind: 'collaboration' as const,
        participants: [],
      },
      personas: [],
      draft: '补充发布边界',
      attachments: [],
      sending: false,
      onDraftChange: vi.fn(),
      onAttachmentsChange: vi.fn(),
      onPasteImages: vi.fn(),
      onPasteFromClipboard: vi.fn(),
      onPickAttachments: vi.fn(),
      onSend,
    };
    const view = render(
      <TooltipProvider>
        <RoomComposer {...common} taskBusyState="running" />
      </TooltipProvider>,
    );

    expect(screen.getByRole('button', { name: '立即干预当前回合' })).toBeEnabled();
    expect(screen.getByText(/发送文字会立即干预主持伙伴的当前回合/)).toBeInTheDocument();

    view.rerender(
      <TooltipProvider>
        <RoomComposer
          {...common}
          pendingUserAnswer
          taskBusyState="running"
        />
      </TooltipProvider>,
    );

    const answer = screen.getByRole('button', { name: '发送问题回答' });
    expect(answer).toBeEnabled();
    expect(screen.getByRole('button', { name: '添加图片' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: '点名一位伙伴' })).not.toBeInTheDocument();
    fireEvent.click(answer);
    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend).toHaveBeenCalledWith('补充发布边界');
  });
});
