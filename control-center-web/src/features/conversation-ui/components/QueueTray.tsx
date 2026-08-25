import React, { useMemo, useState } from "react";
import { useConversation } from "../context/ConversationProvider";

export function QueueTray() {
  const controller = useConversation();
  const { queue, phase } = controller.state;
  const [expanded, setExpanded] = useState(false);
  const [dragging, setDragging] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingText, setEditingText] = useState("");
  const busy = phase === "sending" || phase === "responding" || phase === "stopping";
  const canSendNow = !busy || controller.capabilities.steering;
  const previews = useMemo(() => queue.map(item => item.text.trim().replace(/\s+/g, " ")), [queue]);

  if (queue.length === 0) return null;

  if (queue.length === 1 && !expanded) {
    const item = queue[0]!;
    return (
      <div className="ccui-queue-single" role="status">
        <span className="ccui-queue-count">1 message queued</span>
        <button type="button" className="ccui-queue-preview" onClick={() => setExpanded(true)}>{previews[0]}</button>
        <button type="button" className="ccui-icon-action" aria-label="Remove queued message" onClick={() => controller.removeQueued(item.id)}>×</button>
      </div>
    );
  }

  if (!expanded) {
    return (
      <button type="button" className="ccui-queue-collapsed" aria-expanded="false" onClick={() => setExpanded(true)}>
        <strong>{queue.length} messages queued</strong>
        <span>Next: {previews[0]}</span>
        <span aria-hidden="true">⌄</span>
      </button>
    );
  }

  const beginEdit = (id: string, text: string) => {
    setEditingId(id);
    setEditingText(text);
  };
  const commitEdit = () => {
    if (!editingId) return;
    const next = editingText.trim();
    if (next) controller.editQueued(editingId, next);
    setEditingId(null);
    setEditingText("");
  };

  return (
    <section className="ccui-queue-panel" aria-label="Queued messages">
      <header className="ccui-queue-header">
        <strong>{queue.length} messages queued</strong>
        <button className="ccui-icon-action" type="button" onClick={() => setExpanded(false)} aria-label="Collapse queued messages">⌃</button>
      </header>
      <div className="ccui-queue-list" role="list">
        {queue.map((item, index) => {
          const editing = editingId === item.id;
          return (
            <div
              key={item.id}
              role="listitem"
              className={`ccui-queue-row ${dragging === item.id ? "is-dragging" : ""} ${editing ? "is-editing" : ""}`}
              draggable={!editing}
              onDragStart={event => {
                setDragging(item.id);
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("text/plain", item.id);
              }}
              onDragEnd={() => setDragging(null)}
              onDragOver={event => {
                if (editing) return;
                event.preventDefault();
                event.dataTransfer.dropEffect = "move";
              }}
              onDrop={event => {
                event.preventDefault();
                const activeId = event.dataTransfer.getData("text/plain");
                if (activeId && activeId !== item.id) controller.reorderQueued(activeId, item.id);
                setDragging(null);
              }}
            >
              <span className="ccui-drag-handle" aria-hidden="true">⠿</span>
              <div className="ccui-queue-row-main">
                <span className="ccui-queue-row-index">{index + 1}</span>
                {editing ? (
                  <textarea
                    className="ccui-queue-inline-editor"
                    value={editingText}
                    autoFocus
                    rows={2}
                    onChange={event => setEditingText(event.target.value)}
                    onKeyDown={event => {
                      if (event.key === "Escape") {
                        event.preventDefault();
                        setEditingId(null);
                      } else if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                        event.preventDefault();
                        commitEdit();
                      }
                    }}
                  />
                ) : (
                  <>
                    <span className="ccui-queue-row-text">{previews[index]}</span>
                    {item.queuedWhileBusy ? <span className="ccui-queue-tag">after current turn</span> : null}
                  </>
                )}
              </div>
              <div className="ccui-queue-actions">
                {editing ? (
                  <>
                    <button type="button" onClick={commitEdit}>Save</button>
                    <button type="button" onClick={() => setEditingId(null)}>Cancel</button>
                  </>
                ) : (
                  <>
                    <button type="button" disabled={!canSendNow} onClick={() => void controller.sendQueuedNow(item.id)}>Send now</button>
                    <button type="button" onClick={() => beginEdit(item.id, item.text)}>Edit</button>
                    <button type="button" onClick={() => controller.removeQueued(item.id)}>Remove</button>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <footer className="ccui-queue-footer">
        <span>Drag to reorder</span>
        <button type="button" className="danger" onClick={controller.clearQueue}>Clear all</button>
      </footer>
    </section>
  );
}
