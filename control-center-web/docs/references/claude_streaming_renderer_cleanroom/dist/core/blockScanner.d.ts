import type { MarkdownChunk, MarkdownScanCursor, MarkdownScanState, ProgressiveChunkResult } from "./types.js";
export declare const INITIAL_SCAN_CURSOR: MarkdownScanCursor;
export declare const INITIAL_SCAN_STATE: MarkdownScanState;
/**
 * Incrementally discover block-safe commit points in append-only Markdown.
 * Completed chunks preserve their object identity until a new boundary is
 * committed, which is important for React.memo.
 */
export declare function scanIncrementalMarkdown(previous: MarkdownScanState, text: string, enabled?: boolean): MarkdownScanState;
export declare function splitSettledMarkdown(text: string): readonly MarkdownChunk[];
export declare function resolveProgressiveChunks(text: string, isStreaming: boolean, hasEverStreamed: boolean, scanState: MarkdownScanState): ProgressiveChunkResult;
//# sourceMappingURL=blockScanner.d.ts.map