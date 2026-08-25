import {
  Fragment,
  memo,
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
} from "react";
import {
  detectOpenFenceTail,
  type OpenFenceTail,
} from "./openFence";
import {
  normalizeStreamingMarkdown,
  type NestedCodeBlockMode,
} from "./normalizeStreamingMarkdown";
import { useDeferredStreaming } from "./useDeferredStreaming";
import { useProgressiveChunks } from "./useProgressiveChunks";
import { useSafeTextRelease } from "./useSafeTextRelease";

export interface ProgressiveChunkRenderContext {
  readonly text: string;
  readonly offset: number;
  readonly index: number;
  readonly active: boolean;
  readonly settled: boolean;
  readonly openFence: OpenFenceTail | null;
}

export type ProgressiveChunkRenderer = (
  context: ProgressiveChunkRenderContext,
) => ReactNode;

export type FinalizeDocumentRenderer = (options: {
  readonly text: string;
  readonly chunkOffsets: readonly number[];
}) => readonly ReactNode[] | null;

export interface ProgressiveMarkdownProps {
  readonly text: string;
  readonly isStreaming: boolean;
  readonly documentKey: string;
  readonly renderChunk: ProgressiveChunkRenderer;
  readonly finalizeDocument?: FinalizeDocumentRenderer | undefined;
  readonly className?: string | undefined;
  readonly holdBack?: boolean | undefined;
  readonly openFenceFastPath?: boolean | undefined;
  readonly normalize?: boolean | undefined;
  readonly nestedCodeBlockMode?: NestedCodeBlockMode | undefined;
  /** Increment when renderer configuration must invalidate frozen chunks. */
  readonly renderVersion?: string | number | undefined;
  readonly onFirstPaint?: (() => void) | undefined;
  readonly onSettledCommit?: ((timestamp: number) => void) | undefined;
}

interface ChunkViewProps {
  readonly text: string;
  readonly offset: number;
  readonly index: number;
  readonly active: boolean;
  readonly settled: boolean;
  readonly openFenceFastPath: boolean;
  readonly renderChunk: ProgressiveChunkRenderer;
  readonly renderVersion: string | number;
  readonly finalizedNode: ReactNode | undefined;
}

const ChunkView = memo(
  function ChunkViewInner(props: ChunkViewProps): ReactNode {
    const {
      text,
      offset,
      index,
      active,
      settled,
      openFenceFastPath,
      renderChunk,
      finalizedNode,
    } = props;
    if (finalizedNode !== undefined) return finalizedNode;
    const openFence =
      active && !settled && openFenceFastPath
        ? detectOpenFenceTail(text)
        : null;
    return renderChunk({ text, offset, index, active, settled, openFence });
  },
  (previous, next) =>
    previous.text === next.text &&
    previous.offset === next.offset &&
    previous.index === next.index &&
    previous.active === next.active &&
    previous.settled === next.settled &&
    previous.openFenceFastPath === next.openFenceFastPath &&
    previous.renderVersion === next.renderVersion &&
    previous.finalizedNode === next.finalizedNode &&
    // While streaming, stable completed chunks intentionally ignore changing
    // callback identity. At settle, renderer changes are allowed through.
    (!next.settled || previous.renderChunk === next.renderChunk),
);

/**
 * Renderer-agnostic implementation of stable-prefix + mutable-tail Markdown.
 * Use ReactMarkdownAdapter.tsx for a ready-made react-markdown adapter.
 */
export function ProgressiveMarkdown(props: ProgressiveMarkdownProps): ReactNode {
  const {
    text,
    isStreaming,
    documentKey,
    renderChunk,
    finalizeDocument,
    className,
    holdBack = true,
    openFenceFastPath = true,
    normalize = true,
    nestedCodeBlockMode = "code-in-markdown",
    renderVersion = 0,
    onFirstPaint,
    onSettledCommit,
  } = props;

  const effectiveStreaming = useDeferredStreaming(isStreaming);
  const settled = !effectiveStreaming;
  const normalized = useMemo(
    () =>
      normalize
        ? normalizeStreamingMarkdown(text, {
            isStreaming,
            nestedCodeBlockMode,
          })
        : text,
    [isStreaming, nestedCodeBlockMode, normalize, text],
  );
  const visibleText = useSafeTextRelease(normalized, {
    enabled: isStreaming && holdBack,
  });
  const progressive = useProgressiveChunks({
    text: visibleText,
    isStreaming: effectiveStreaming,
    documentKey,
  });

  const firstPaintReported = useRef(false);
  useEffect(() => {
    if (
      !firstPaintReported.current &&
      visibleText.trim().length > 0 &&
      onFirstPaint
    ) {
      firstPaintReported.current = true;
      onFirstPaint();
    }
  }, [onFirstPaint, visibleText]);

  const finalizationReported = useRef(false);
  const streamedForDocument = useRef(false);
  const previousDocumentKey = useRef(documentKey);
  if (previousDocumentKey.current !== documentKey) {
    previousDocumentKey.current = documentKey;
    finalizationReported.current = false;
    streamedForDocument.current = false;
    firstPaintReported.current = false;
  }
  if (effectiveStreaming) streamedForDocument.current = true;

  useEffect(() => {
    if (
      settled &&
      streamedForDocument.current &&
      !finalizationReported.current
    ) {
      finalizationReported.current = true;
      const timestamp =
        typeof performance !== "undefined" ? performance.now() : Date.now();
      if (
        typeof performance !== "undefined" &&
        typeof performance.mark === "function"
      ) {
        performance.mark("progressive-markdown:finalize", {
          startTime: timestamp,
        });
      }
      onSettledCommit?.(timestamp);
    }
  }, [onSettledCommit, settled]);

  const chunks = useMemo(
    () =>
      progressive.streamingChunk
        ? [
            ...progressive.completedChunks,
            {
              text: progressive.streamingChunk,
              offset: progressive.streamingChunkOffset,
            },
          ]
        : [...progressive.completedChunks],
    [
      progressive.completedChunks,
      progressive.streamingChunk,
      progressive.streamingChunkOffset,
    ],
  );
  const activeIndex =
    !settled && progressive.streamingChunk.length > 0
      ? chunks.length - 1
      : -1;
  const finalizedNodes = useMemo(() => {
    if (!settled || !finalizeDocument || chunks.length === 0) return null;
    return finalizeDocument({
      text: visibleText,
      chunkOffsets: chunks.map((chunk) => chunk.offset),
    });
  }, [chunks, finalizeDocument, settled, visibleText]);

  return (
    <div className={className} data-progressive-markdown="">
      {chunks.map((chunk, index) => (
        <Fragment key={`${documentKey}:${chunk.offset}`}>
          <ChunkView
            text={chunk.text}
            offset={chunk.offset}
            index={index}
            active={index === activeIndex}
            settled={settled}
            openFenceFastPath={openFenceFastPath}
            renderChunk={renderChunk}
            renderVersion={renderVersion}
            finalizedNode={finalizedNodes?.[index]}
          />
        </Fragment>
      ))}
    </div>
  );
}
