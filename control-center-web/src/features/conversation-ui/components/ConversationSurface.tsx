import React from "react";
import { useConversation } from "../context/ConversationProvider";
import { Composer } from "./Composer";
import { SideChatPanel } from "./SideChatPanel";
import { VirtualTranscript } from "./VirtualTranscript";

export function ConversationSurface({
  title = "Agent session",
  subtitle,
  rightSlot,
}: {
  title?: string;
  subtitle?: string;
  rightSlot?: React.ReactNode;
}) {
  const controller = useConversation();
  const { phase, queue } = controller.state;
  return (
    <section className="ccui-conversation-surface">
      <header className="ccui-conversation-header">
        <div className="ccui-conversation-title">
          <h1>{title}</h1>
          <div className="ccui-conversation-subtitle">
            <span className={`ccui-phase-dot phase-${phase}`} />
            <span>{subtitle ?? (phase === "idle" ? "Ready" : phase === "responding" ? "Working" : phase === "sending" ? "Sending" : phase === "stopping" ? "Stopping" : "Needs attention")}</span>
            {queue.length ? <span>· {queue.length} queued</span> : null}
          </div>
        </div>
        <div className="ccui-conversation-header-actions">
          {controller.capabilities.sideChat ? <button type="button" onClick={() => controller.toggleSideChat(true)}>Side chat <kbd>⌘;</kbd></button> : null}
          {rightSlot}
        </div>
      </header>
      <VirtualTranscript />
      <Composer />
      <SideChatPanel />
    </section>
  );
}
