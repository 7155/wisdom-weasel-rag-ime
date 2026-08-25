import React, { useCallback, useMemo, useRef } from "react";
import { useConversation } from "../context/ConversationProvider";
import { usePinnedTranscript } from "../hooks/usePinnedTranscript";
import { useSessionScrollMemory } from "../hooks/useSessionScrollMemory";
import { useVirtualTranscript } from "../hooks/useVirtualTranscript";
import type { TranscriptMessage } from "../model/types";
import { JumpToBottom } from "./JumpToBottom";
import { TranscriptRow } from "./TranscriptRow";

function estimateMessage(message: TranscriptMessage): number {
  if (message.role === "user") return Math.min(240, 74 + Math.ceil(message.text.length / 65) * 22);
  let size = 56;
  for (const block of message.blocks) {
    if (block.kind === "text") size += Math.min(640, 38 + Math.ceil(block.text.length / 72) * 22);
    else if (block.kind === "thinking") size += block.detail ? 62 : 38;
    else size += block.output ? 88 : 58;
  }
  return Math.max(80, size);
}

export function VirtualTranscript() {
  const controller = useConversation();
  const { messages, phase, conversationId } = controller.state;
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

  const busy = phase === "sending" || phase === "responding" || phase === "stopping";
  const messageIndex = useMemo(() => new Map(messages.map((message, index) => [message.id, index])), [messages]);

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if ((event.target as HTMLElement).matches("input,textarea,button,[contenteditable=true]")) return;
    const current = document.activeElement?.closest<HTMLElement>("[data-message-id]")?.dataset.messageId;
    const index = current ? messageIndex.get(current) ?? messages.length - 1 : messages.length - 1;
    if (event.key === "ArrowUp") {
      event.preventDefault();
      virtual.scrollToIndex(Math.max(0, index - 1), "center");
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      virtual.scrollToIndex(Math.min(messages.length - 1, index + 1), "center");
    } else if (event.key === "PageUp") {
      event.preventDefault();
      scrollRef.current?.scrollBy({ top: -(scrollRef.current?.clientHeight ?? 600) * 0.8 });
    } else if (event.key === "PageDown") {
      event.preventDefault();
      scrollRef.current?.scrollBy({ top: (scrollRef.current?.clientHeight ?? 600) * 0.8 });
    }
  };

  return (
    <div className="ccui-transcript-shell">
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
        <div
          ref={sizerRef}
          data-rocksteady-sizer=""
          className="ccui-transcript-sizer"
          style={{ height: virtual.totalSize }}
        >
          {virtual.virtualRows.map(row => {
            const message = messages[row.index];
            if (!message) return null;
            return (
              <div
                key={row.key}
                ref={virtual.measureElement(row.key)}
                data-message-id={message.id}
                data-rs-index={row.index}
                data-index={row.index}
                className="ccui-virtual-row"
                style={{ transform: `translateY(${row.start}px)` }}
              >
                <TranscriptRow message={message} />
              </div>
            );
          })}
        </div>
        {messages.length === 0 ? (
          <div className="ccui-empty-transcript">
            <div className="ccui-empty-mark">AI</div>
            <h2>Start a working conversation</h2>
            <p>Keep the composer usable while agents work. Follow-ups can queue, steer, or branch without turning the transcript into a control panel.</p>
          </div>
        ) : null}
      </div>
      <JumpToBottom visible={pinned.showJumpToBottom} onClick={() => pinned.scrollToBottom("smooth")} />
    </div>
  );
}
