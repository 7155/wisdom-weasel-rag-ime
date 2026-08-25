export interface MarkdownChunk {
  /** Absolute UTF-16 offset in the normalized Markdown document. */
  readonly offset: number;
  readonly text: string;
}

export interface FenceState {
  readonly char: "`" | "~";
  readonly length: number;
}

export interface MarkdownScanCursor {
  readonly codeFence: FenceState | null;
  readonly inMathBlock: boolean;
  readonly inList: boolean;
  readonly listPendingBlank: boolean;
  readonly inTable: boolean;
  readonly inBlockquote: boolean;
  readonly inIndentedCode: boolean;
  readonly indentedCodePendingBlank: boolean;
  readonly hadBlankLine: boolean;
  readonly hadContent: boolean;
  /** Offset from which the next append-only scan may safely resume. */
  readonly offset: number;
}

export interface MarkdownScanState {
  readonly chunks: readonly MarkdownChunk[];
  readonly committedEnd: number;
  readonly previousText: string;
  readonly cursor: MarkdownScanCursor;
}

export interface ProgressiveChunkResult {
  readonly completedChunks: readonly MarkdownChunk[];
  readonly streamingChunk: string;
  readonly streamingChunkOffset: number;
}
