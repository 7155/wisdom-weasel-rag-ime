import { jsx as _jsx } from "react/jsx-runtime";
import { Fragment, memo, useEffect, useMemo, useRef, } from "react";
import { detectOpenFenceTail, } from "../core/openFence.js";
import { normalizeStreamingMarkdown, } from "../core/normalizeStreamingMarkdown.js";
import { useDeferredStreaming } from "./useDeferredStreaming.js";
import { useProgressiveChunks } from "./useProgressiveChunks.js";
import { useSafeTextRelease } from "./useSafeTextRelease.js";
const ChunkView = memo(function ChunkViewInner(props) {
    const { text, offset, index, active, settled, openFenceFastPath, renderChunk, finalizedNode, } = props;
    if (finalizedNode !== undefined)
        return finalizedNode;
    const openFence = active && !settled && openFenceFastPath
        ? detectOpenFenceTail(text)
        : null;
    return renderChunk({ text, offset, index, active, settled, openFence });
}, (previous, next) => previous.text === next.text &&
    previous.offset === next.offset &&
    previous.index === next.index &&
    previous.active === next.active &&
    previous.settled === next.settled &&
    previous.openFenceFastPath === next.openFenceFastPath &&
    previous.renderVersion === next.renderVersion &&
    previous.finalizedNode === next.finalizedNode &&
    // While streaming, stable completed chunks intentionally ignore changing
    // callback identity. At settle, renderer changes are allowed through.
    (!next.settled || previous.renderChunk === next.renderChunk));
/**
 * Renderer-agnostic implementation of stable-prefix + mutable-tail Markdown.
 * Use ReactMarkdownAdapter.tsx for a ready-made react-markdown adapter.
 */
export function ProgressiveMarkdown(props) {
    const { text, isStreaming, documentKey, renderChunk, finalizeDocument, className, holdBack = true, openFenceFastPath = true, normalize = true, nestedCodeBlockMode = "code-in-markdown", renderVersion = 0, onFirstPaint, onSettledCommit, } = props;
    const effectiveStreaming = useDeferredStreaming(isStreaming);
    const settled = !effectiveStreaming;
    const normalized = useMemo(() => normalize
        ? normalizeStreamingMarkdown(text, {
            isStreaming,
            nestedCodeBlockMode,
        })
        : text, [isStreaming, nestedCodeBlockMode, normalize, text]);
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
        if (!firstPaintReported.current &&
            visibleText.trim().length > 0 &&
            onFirstPaint) {
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
    if (effectiveStreaming)
        streamedForDocument.current = true;
    useEffect(() => {
        if (settled &&
            streamedForDocument.current &&
            !finalizationReported.current) {
            finalizationReported.current = true;
            const timestamp = typeof performance !== "undefined" ? performance.now() : Date.now();
            if (typeof performance !== "undefined" &&
                typeof performance.mark === "function") {
                performance.mark("progressive-markdown:finalize", {
                    startTime: timestamp,
                });
            }
            onSettledCommit?.(timestamp);
        }
    }, [onSettledCommit, settled]);
    const chunks = useMemo(() => progressive.streamingChunk
        ? [
            ...progressive.completedChunks,
            {
                text: progressive.streamingChunk,
                offset: progressive.streamingChunkOffset,
            },
        ]
        : [...progressive.completedChunks], [
        progressive.completedChunks,
        progressive.streamingChunk,
        progressive.streamingChunkOffset,
    ]);
    const activeIndex = !settled && progressive.streamingChunk.length > 0
        ? chunks.length - 1
        : -1;
    const finalizedNodes = useMemo(() => {
        if (!settled || !finalizeDocument || chunks.length === 0)
            return null;
        return finalizeDocument({
            text: visibleText,
            chunkOffsets: chunks.map((chunk) => chunk.offset),
        });
    }, [chunks, finalizeDocument, settled, visibleText]);
    return (_jsx("div", { className: className, "data-progressive-markdown": "", children: chunks.map((chunk, index) => (_jsx(Fragment, { children: _jsx(ChunkView, { text: chunk.text, offset: chunk.offset, index: index, active: index === activeIndex, settled: settled, openFenceFastPath: openFenceFastPath, renderChunk: renderChunk, renderVersion: renderVersion, finalizedNode: finalizedNodes?.[index] }) }, `${documentKey}:${chunk.offset}`))) }));
}
//# sourceMappingURL=ProgressiveMarkdown.js.map