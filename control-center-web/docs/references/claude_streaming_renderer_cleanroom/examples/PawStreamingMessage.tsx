import { memo, useCallback, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  IncrementalCodeBlock,
  ProgressiveMarkdown,
  type ProgressiveChunkRenderContext,
} from "../src/react/index.js";

export interface PawStreamingMessageProps {
  readonly messageId: string;
  readonly text: string;
  readonly status: "queued" | "streaming" | "completed" | "failed";
}

/**
 * The message shell may rerender for status/tool events, while completed text
 * chunks remain frozen inside ProgressiveMarkdown.
 */
export const PawStreamingMessage = memo(function PawStreamingMessage(
  props: PawStreamingMessageProps,
): ReactNode {
  const isStreaming = props.status === "streaming";

  const renderChunk = useCallback(
    ({ text, openFence }: ProgressiveChunkRenderContext): ReactNode => {
      if (openFence) {
        return (
          <>
            {openFence.prefix ? (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {openFence.prefix}
              </ReactMarkdown>
            ) : null}
            <IncrementalCodeBlock
              code={openFence.value}
              language={openFence.language}
              streaming
              className="paw-code-block"
            />
          </>
        );
      }

      return (
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
      );
    },
    [],
  );

  return (
    <article
      className="paw-assistant-message"
      data-message-id={props.messageId}
      data-status={props.status}
    >
      <ProgressiveMarkdown
        documentKey={props.messageId}
        text={props.text}
        isStreaming={isStreaming}
        renderChunk={renderChunk}
        className={
          isStreaming ? "progressive-markdown" : "standard-markdown"
        }
        holdBack
        openFenceFastPath
      />
    </article>
  );
});
