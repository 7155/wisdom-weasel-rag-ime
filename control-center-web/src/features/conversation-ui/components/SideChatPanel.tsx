import React, { useEffect, useRef, useState } from "react";
import { useConversation } from "../context/ConversationProvider";

interface Geometry {
  x: number;
  y: number;
  width: number;
  height: number;
}

const DEFAULT_GEOMETRY: Geometry = { x: 34, y: 72, width: 390, height: 500 };

function loadGeometry(key: string): Geometry {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return DEFAULT_GEOMETRY;
    const value = JSON.parse(raw) as Geometry;
    if ([value.x, value.y, value.width, value.height].every(Number.isFinite)) return value;
  } catch {}
  return DEFAULT_GEOMETRY;
}

export function SideChatPanel() {
  const controller = useConversation();
  const { sideChat, conversationId } = controller.state;
  const [draft, setDraft] = useState("");
  const storageKey = `ccui-side-chat-geometry:${conversationId}`;
  const [geometry, setGeometry] = useState<Geometry>(() => typeof window === "undefined" ? DEFAULT_GEOMETRY : loadGeometry(storageKey));
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    setGeometry(loadGeometry(storageKey));
  }, [storageKey]);
  const drag = useRef<{ startX: number; startY: number; x: number; y: number } | null>(null);

  useEffect(() => {
    if (!sideChat.open) return;
    const onMove = (event: PointerEvent) => {
      if (!drag.current) return;
      const dx = event.clientX - drag.current.startX;
      const dy = event.clientY - drag.current.startY;
      setGeometry(current => ({ ...current, x: Math.max(8, drag.current!.x + dx), y: Math.max(8, drag.current!.y + dy) }));
    };
    const onUp = () => {
      drag.current = null;
      const panel = panelRef.current;
      if (panel) {
        const rect = panel.getBoundingClientRect();
        const next = { x: rect.left, y: rect.top, width: rect.width, height: rect.height };
        setGeometry(next);
        localStorage.setItem(storageKey, JSON.stringify(next));
      }
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [sideChat.open, storageKey]);

  useEffect(() => {
    const panel = panelRef.current;
    if (!panel || !sideChat.open) return;
    const observer = new ResizeObserver(() => {
      const rect = panel.getBoundingClientRect();
      const next = { x: rect.left, y: rect.top, width: rect.width, height: rect.height };
      setGeometry(next);
      localStorage.setItem(storageKey, JSON.stringify(next));
    });
    observer.observe(panel);
    return () => observer.disconnect();
  }, [sideChat.open, storageKey]);

  if (!sideChat.open) return null;

  const submit = () => {
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    void controller.sendSideChat(text);
  };

  return (
    <aside
      ref={panelRef}
      className="ccui-side-chat"
      aria-label="Side chat"
      style={{ left: geometry.x, top: geometry.y, width: geometry.width, height: geometry.height }}
    >
      <header
        className="ccui-side-chat-head"
        onPointerDown={event => {
          if ((event.target as HTMLElement).closest("button")) return;
          event.currentTarget.setPointerCapture?.(event.pointerId);
          drag.current = { startX: event.clientX, startY: event.clientY, x: geometry.x, y: geometry.y };
        }}
      >
        <div>
          <strong>Side chat</strong>
          <span>Reads this session · does not enter the main thread</span>
        </div>
        <div className="ccui-side-chat-head-actions">
          <button type="button" onClick={controller.clearSideChat}>Clear</button>
          <button type="button" className="ccui-icon-action" onClick={() => controller.toggleSideChat(false)} aria-label="Close side chat">×</button>
        </div>
      </header>
      <div className="ccui-side-chat-messages">
        {sideChat.messages.length === 0 ? (
          <div className="ccui-side-chat-empty">
            Ask about the current session without steering or polluting the main transcript.
          </div>
        ) : sideChat.messages.map(message => (
          <div key={message.id} className={`ccui-side-message role-${message.role}`}>
            <span>{message.text}</span>
          </div>
        ))}
        {sideChat.toolActivity ? <div className="ccui-side-tool">Working · {sideChat.toolActivity}</div> : null}
        {sideChat.status === "thinking" ? <div className="ccui-side-thinking">Thinking…</div> : null}
        {sideChat.queued ? <div className="ccui-side-queued">1 follow-up queued</div> : null}
        {sideChat.error ? <div className="ccui-side-error">{sideChat.error}</div> : null}
      </div>
      <div className="ccui-side-chat-composer">
        <textarea
          value={draft}
          rows={2}
          placeholder="Ask without interrupting the main session…"
          onChange={event => setDraft(event.target.value)}
          onKeyDown={event => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              submit();
            }
          }}
        />
        <button type="button" onClick={submit} disabled={!draft.trim()}>{sideChat.status === "thinking" ? "Queue" : "Send"}</button>
      </div>
    </aside>
  );
}
