import { type ReactNode } from "react";
import { type OpenFenceTail } from "../core/openFence.js";
import { type NestedCodeBlockMode } from "../core/normalizeStreamingMarkdown.js";
export interface ProgressiveChunkRenderContext {
    readonly text: string;
    readonly offset: number;
    readonly index: number;
    readonly active: boolean;
    readonly settled: boolean;
    readonly openFence: OpenFenceTail | null;
}
export type ProgressiveChunkRenderer = (context: ProgressiveChunkRenderContext) => ReactNode;
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
/**
 * Renderer-agnostic implementation of stable-prefix + mutable-tail Markdown.
 * Use ReactMarkdownAdapter.tsx for a ready-made react-markdown adapter.
 */
export declare function ProgressiveMarkdown(props: ProgressiveMarkdownProps): ReactNode;
//# sourceMappingURL=ProgressiveMarkdown.d.ts.map