import type { MarkdownChunk, MarkdownScanState } from "../core/types.js";
export interface ProgressiveChunksSnapshot {
    readonly completedChunks: readonly MarkdownChunk[];
    readonly streamingChunk: string;
    readonly streamingChunkOffset: number;
    readonly settled: boolean;
    readonly hasEverStreamed: boolean;
    readonly scanState: MarkdownScanState;
}
/**
 * Synchronously derives progressive chunks. A ref is intentional here: the
 * scanner is a deterministic cache, not user-visible state, and updating it
 * must not schedule a second React render for every token append.
 */
export declare function useProgressiveChunks(options: {
    readonly text: string;
    readonly isStreaming: boolean;
    readonly documentKey: string;
    readonly enabled?: boolean;
}): ProgressiveChunksSnapshot;
//# sourceMappingURL=useProgressiveChunks.d.ts.map