import React, { useRef, useState } from "react";
import { FRONTEND_QUEUE_CAP } from "../model/queue";
import { useConversation } from "../context/ConversationProvider";
import { useAutoGrowTextarea } from "../hooks/useAutoGrowTextarea";
import { QueueTray } from "./QueueTray";

export function Composer() {
  const controller = useConversation();
  const { draft, phase, queue } = controller.state;
  const ref = useRef<HTMLTextAreaElement | null>(null);
  const [busyMode, setBusyMode] = useState<"queue" | "steer">("queue");
  useAutoGrowTextarea(ref, draft.text);

  const busy = phase === "sending" || phase === "responding" || phase === "stopping";
  const canSteer = busy && controller.capabilities.steering;
  const queueFull = queue.length >= FRONTEND_QUEUE_CAP;
  const empty = draft.text.trim().length === 0 && draft.attachments.length === 0;

  const submit = () => {
    if (busy && busyMode === "steer" && canSteer) {
      void controller.submit("steer");
    } else {
      void controller.submit("auto");
    }
  };

  return (
    <div className="ccui-composer-zone" data-chat-input-container="">
      <QueueTray />
      {controller.state.lastError ? (
        <div className="ccui-inline-error" role="alert">
          <span>{controller.state.lastError}</span>
          <button type="button" onClick={controller.dismissError}>Dismiss</button>
        </div>
      ) : null}
      {draft.editingMessageId ? (
        <div className="ccui-edit-banner">
          <span>Editing an earlier message. Sending will replace the branch after it.</span>
          <button type="button" onClick={controller.cancelEditing}>Cancel</button>
        </div>
      ) : null}
      <div className={`ccui-composer ${busy ? "is-busy" : ""}`}>
        <textarea
          ref={ref}
          value={draft.text}
          rows={1}
          aria-label="Message"
          placeholder={busy ? "Reply at any time, even while the agent is working…" : "Message the agent…"}
          onChange={event => controller.setDraft(event.target.value)}
          onKeyDown={event => {
            if (event.key === "Escape" && busy) {
              event.preventDefault();
              void controller.stop();
              return;
            }
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              if (!empty) submit();
            }
          }}
        />
        <div className="ccui-composer-bottom">
          <div className="ccui-composer-tools">
            {controller.capabilities.sideChat ? (
              <button type="button" className="ccui-quiet-action" onClick={() => controller.toggleSideChat(true)} title="Side chat · Cmd/Ctrl + ;">Side chat</button>
            ) : null}
            {busy && canSteer ? (
              <div className="ccui-send-mode" role="group" aria-label="Busy send behavior">
                <button type="button" className={busyMode === "queue" ? "active" : ""} onClick={() => setBusyMode("queue")}>Queue</button>
                <button type="button" className={busyMode === "steer" ? "active" : ""} onClick={() => setBusyMode("steer")}>Steer</button>
              </div>
            ) : null}
          </div>
          <div className="ccui-composer-primary">
            {busy ? (
              <button type="button" className="ccui-stop-button" onClick={() => void controller.stop()} disabled={phase === "stopping"} title="Stop response · Esc">
                {phase === "stopping" ? "Stopping…" : "Stop"}
              </button>
            ) : null}
            <button
              type="button"
              className="ccui-send-button"
              disabled={empty || (busy && busyMode === "queue" && queueFull) || phase === "stopping"}
              onClick={submit}
              title={busy && busyMode === "queue" ? "Queue message" : busy && busyMode === "steer" ? "Steer current session" : "Send message"}
            >
              {busy ? (busyMode === "steer" && canSteer ? "Steer" : "Queue") : "Send"}
            </button>
          </div>
        </div>
      </div>
      <div className="ccui-composer-hint">
        <span>Enter to send · Shift+Enter for newline</span>
        {busy ? <span>{queue.length}/{FRONTEND_QUEUE_CAP} queued</span> : <span>/btw opens side chat</span>}
      </div>
    </div>
  );
}
