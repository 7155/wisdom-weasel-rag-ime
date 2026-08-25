import { useCallback, useMemo, useRef, type ReactNode } from 'react';
import { usePinnedTranscript } from '../hooks/usePinnedTranscript';
import { useSessionScrollMemory } from '../hooks/useSessionScrollMemory';
import { useVirtualTranscript } from '../hooks/useVirtualTranscript';
import type { RunPhase, TranscriptMessage } from '../model/types';
import { JumpToBottom } from '../components/JumpToBottom';
import { TranscriptRow } from '../components/TranscriptRow';

function estimateMessage(message: TranscriptMessage): number {
  if (message.role === 'user') return Math.min(240, 74 + Math.ceil(message.text.length / 65) * 22);
  let size = 56;
  for (const block of message.blocks) {
    if (block.kind === 'text') size += Math.min(640, 38 + Math.ceil(block.text.length / 72) * 22);
    else if (block.kind === 'thinking') size += block.detail ? 62 : 38;
    else size += block.output ? 88 : 58;
  }
  return Math.max(80, size);
}

/** VirtualTranscript without ConversationProvider — for Session/Room projections. */
export function StandaloneVirtualTranscript({
  conversationId,
  messages,
  phase = 'idle',
  renderRow,
}: {
  conversationId: string;
  messages: readonly TranscriptMessage[];
  phase?: RunPhase;
  renderRow?: (message: TranscriptMessage, index: number) => ReactNode;
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const sizerRef = useRef<HTMLDivElement | null>(null);
  const pinned = usePinnedTranscript(scrollRef, sizerRef);

  const getKey = useCallback((message: TranscriptMessage) => message.id, []);
  const estimate = useCallback((message: TranscriptMessage) => estimateMessage(message), []);
  const virtual = useVirtualTranscript({
    items: messages,
    getKey,
    estimateSize: estimate,
    scrollRef,
  });

  useSessionScrollMemory(
    conversationId,
    pinned.captureAnchor,
    pinned.restoreAnchor,
    scrollRef,
  );

  const busy = phase === 'sending' || phase === 'responding' || phase === 'stopping';
  const messageIndex = useMemo(() => new Map(messages.map((message, index) => [message.id, index])), [messages]);

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if ((event.target as HTMLElement).matches('input,textarea,button,[contenteditable=true]')) return;
    const current = document.activeElement?.closest<HTMLElement>('[data-message-id]')?.dataset.messageId;
    const index = current ? messageIndex.get(current) ?? messages.length - 1 : messages.length - 1;
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      virtual.scrollToIndex(Math.max(0, index - 1), 'center');
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      virtual.scrollToIndex(Math.min(messages.length - 1, index + 1), 'center');
    }
  };

  return (
    <div className="ccui-transcript-shell paw-conversation-transcript">
      <div
        ref={scrollRef}
        role="feed"
        aria-label="Conversation"
        aria-busy={busy}
        tabIndex={0}
        data-autoscroll-container=""
        className="ccui-transcript-scroll"
        onKeyDown={onKeyDown}
      >
        <div ref={sizerRef} data-rocksteady-sizer="" style={{ height: virtual.totalSize, position: 'relative' }}>
          {virtual.rows.map((row) => {
            const message = messages[row.index];
            if (!message) return null;
            return (
              <div
                data-message-id={message.id}
                key={row.key}
                ref={virtual.measureRef(row.key)}
                style={{ position: 'absolute', top: row.start, left: 0, right: 0 }}
              >
                {renderRow ? renderRow(message, row.index) : <TranscriptRow message={message} />}
              </div>
            );
          })}
        </div>
      </div>
      <JumpToBottom pinned={pinned} scrollRef={scrollRef} />
    </div>
  );
}
