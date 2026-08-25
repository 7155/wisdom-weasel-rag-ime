import { useMemo, useRef } from "react";
import {
  INITIAL_SCAN_STATE,
  resolveProgressiveChunks,
  scanIncrementalMarkdown,
} from "./blockScanner";
import type {
  MarkdownChunk,
  MarkdownScanState,
} from "./types";

export interface ProgressiveChunksSnapshot {
  readonly completedChunks: readonly MarkdownChunk[];
  readonly streamingChunk: string;
  readonly streamingChunkOffset: number;
  readonly settled: boolean;
  readonly hasEverStreamed: boolean;
  readonly scanState: MarkdownScanState;
}

interface StatefulScan {
  documentKey: string;
  scanState: MarkdownScanState;
  hasEverStreamed: boolean;
}

/**
 * Synchronously derives progressive chunks. A ref is intentional here: the
 * scanner is a deterministic cache, not user-visible state, and updating it
 * must not schedule a second React render for every token append.
 */
export function useProgressiveChunks(options: {
  readonly text: string;
  readonly isStreaming: boolean;
  readonly documentKey: string;
  readonly enabled?: boolean;
}): ProgressiveChunksSnapshot {
  const { text, isStreaming, documentKey, enabled = true } = options;
  const stateRef = useRef<StatefulScan>({
    documentKey,
    scanState: INITIAL_SCAN_STATE,
    hasEverStreamed: false,
  });

  if (stateRef.current.documentKey !== documentKey) {
    stateRef.current = {
      documentKey,
      scanState: INITIAL_SCAN_STATE,
      hasEverStreamed: false,
    };
  }

  if (isStreaming) stateRef.current.hasEverStreamed = true;
  const nextScan = scanIncrementalMarkdown(
    stateRef.current.scanState,
    text,
    enabled && isStreaming,
  );
  stateRef.current.scanState = nextScan;

  const hasEverStreamed = stateRef.current.hasEverStreamed;
  const resolved = useMemo(
    () =>
      resolveProgressiveChunks(
        text,
        isStreaming,
        hasEverStreamed,
        nextScan,
      ),
    [text, isStreaming, hasEverStreamed, nextScan],
  );

  return {
    ...resolved,
    settled: !isStreaming,
    hasEverStreamed,
    scanState: nextScan,
  };
}
