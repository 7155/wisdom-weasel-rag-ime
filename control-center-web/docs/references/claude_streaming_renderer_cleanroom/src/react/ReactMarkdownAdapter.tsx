import {
  useCallback,
  useMemo,
  type ComponentProps,
  type ReactNode,
} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { StatefulLineTokenizer } from "../core/incrementalTokenizer.js";
import {
  IncrementalCodeBlock,
  type DisplayToken,
} from "./IncrementalCodeBlock.js";
import {
  ProgressiveMarkdown,
  type ProgressiveChunkRenderContext,
} from "./ProgressiveMarkdown.js";

export interface ReactMarkdownProgressiveProps {
  readonly text: string;
  readonly isStreaming: boolean;
  readonly documentKey: string;
  readonly className?: string | undefined;
  readonly holdBack?: boolean | undefined;
  readonly openFenceFastPath?: boolean | undefined;
  readonly showLineNumbers?: boolean | undefined;
  readonly renderVersion?: string | number | undefined;
  readonly components?: ComponentProps<typeof ReactMarkdown>["components"] | undefined;
  readonly createTokenizer?:
    | ((language: string) =>
        StatefulLineTokenizer<DisplayToken, unknown> | undefined)
    | undefined;
  readonly onFirstPaint?: (() => void) | undefined;
  readonly onSettledCommit?: ((timestamp: number) => void) | undefined;
}

/**
 * Ready-to-use adapter. It parses completed Markdown chunks independently
 * while streaming, and bypasses repeated Markdown parsing for a growing open
 * fenced code block.
 */
export function ReactMarkdownProgressive(
  props: ReactMarkdownProgressiveProps,
): ReactNode {
  const {
    text,
    isStreaming,
    documentKey,
    className,
    holdBack,
    openFenceFastPath,
    showLineNumbers = false,
    renderVersion = 0,
    components,
    createTokenizer,
    onFirstPaint,
    onSettledCommit,
  } = props;

  const markdownComponents = useMemo<
    ComponentProps<typeof ReactMarkdown>["components"]
  >(() => components, [components]);

  const renderChunk = useCallback(
    (context: ProgressiveChunkRenderContext): ReactNode => {
      const { text: chunkText, openFence } = context;
      if (openFence) {
        const tokenizer = createTokenizer?.(openFence.language);
        return (
          <>
            {openFence.prefix.trim().length > 0 ? (
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={markdownComponents}
              >
                {openFence.prefix}
              </ReactMarkdown>
            ) : null}
            <IncrementalCodeBlock
              code={openFence.value}
              language={openFence.language}
              streaming={true}
              tokenizer={tokenizer}
              showLineNumbers={showLineNumbers}
              className={
                openFence.language
                  ? `language-${openFence.language}`
                  : undefined
              }
            />
          </>
        );
      }

      return (
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={markdownComponents}
        >
          {chunkText}
        </ReactMarkdown>
      );
    },
    [createTokenizer, markdownComponents, showLineNumbers],
  );

  return (
    <ProgressiveMarkdown
      text={text}
      isStreaming={isStreaming}
      documentKey={documentKey}
      renderChunk={renderChunk}
      className={className}
      holdBack={holdBack}
      openFenceFastPath={openFenceFastPath}
      renderVersion={renderVersion}
      onFirstPaint={onFirstPaint}
      onSettledCommit={onSettledCommit}
    />
  );
}
