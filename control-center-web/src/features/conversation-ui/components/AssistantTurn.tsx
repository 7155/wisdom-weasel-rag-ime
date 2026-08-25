import React from "react";
import type { AssistantMessage } from "../model/types";
import { useConversation } from "../context/ConversationProvider";
import { ProgressiveMarkdown } from "../rendering/react/ProgressiveMarkdown";
import { MessageActions } from "./MessageActions";
import { ThinkingBlock } from "./ThinkingBlock";
import { ToolCard } from "./ToolCard";

export function AssistantTurn({ message }: { message: AssistantMessage }) {
  const controller = useConversation();
  const text = message.blocks.filter(block => block.kind === "text").map(block => block.kind === "text" ? block.text : "").join("\n");
  return (
    <article className="ccui-turn ccui-assistant-turn" aria-label="Assistant response">
      <div className="ccui-assistant-body">
        {message.blocks.map(block => {
          if (block.kind === "thinking") return <ThinkingBlock key={block.id} block={block} />;
          if (block.kind === "tool") return <ToolCard key={block.id} block={block} />;
          return (
            <ProgressiveMarkdown
              key={block.id}
              documentKey={`${message.id}:${block.id}`}
              text={block.text}
              isStreaming={Boolean(block.streaming)}
            />
          );
        })}
        {message.error ? <div className="ccui-error-card">{message.error}</div> : null}
      </div>
      <div className="ccui-assistant-footer">
        <MessageActions
          text={text}
          onRetry={() => void controller.retryAssistant(message.id)}
          onFork={controller.capabilities.fork ? () => void controller.forkFrom(message.id) : undefined}
          onRewind={controller.capabilities.rewind ? () => void controller.rewindTo(message.id) : undefined}
        />
      </div>
    </article>
  );
}
