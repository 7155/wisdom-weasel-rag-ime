import React from "react";
import type { UserMessage } from "../model/types";
import { useConversation } from "../context/ConversationProvider";
import { MessageActions } from "./MessageActions";
import { SteerReceipt } from "./SteerReceipt";

export function UserTurn({ message }: { message: UserMessage }) {
  const controller = useConversation();
  return (
    <article className={`ccui-turn ccui-user-turn ${message.queued ? "is-queued" : ""}`} aria-label={`You said: ${message.text}`}>
      <div className="ccui-user-bubble">
        {message.attachments?.length ? (
          <div className="ccui-attachment-strip">
            {message.attachments.map(file => <span key={file.id} className="ccui-attachment-chip">{file.name}</span>)}
          </div>
        ) : null}
        <div className="ccui-user-text">{message.text}</div>
      </div>
      <div className="ccui-user-footer">
        {message.steerReceipt ? (
          <SteerReceipt
            state={message.steerReceipt}
            timestamp={message.timestamp}
            canInterrupt={message.steerReceipt === "unread" && controller.capabilities.interrupt}
            onInterrupt={() => void controller.interruptSteer(message.id)}
            onCancelAndEdit={() => void controller.cancelAndEditSteer(message.id)}
          />
        ) : (
          <time>{new Date(message.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time>
        )}
        <MessageActions
          text={message.text}
          onEdit={() => controller.editAndRetry(message.id)}
          onFork={controller.capabilities.fork ? () => void controller.forkFrom(message.id) : undefined}
          onRewind={controller.capabilities.rewind ? () => void controller.rewindTo(message.id) : undefined}
        />
      </div>
    </article>
  );
}
