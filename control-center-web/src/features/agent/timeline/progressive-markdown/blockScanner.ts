import type {
  MarkdownChunk,
  MarkdownScanCursor,
  MarkdownScanState,
  ProgressiveChunkResult,
} from "./types";

const BLANK_LINE = /^[\t\r ]*$/;
const INDENTED_CODE = /^( {4}| {0,3}\t)/;
const FENCE_START = /^(`{3,}|~{3,})/;
const LIST_MARKER = /^[-*+]\s|^\d+[.)]\s/;
const BARE_LIST_MARKER = /^([-*+]|\d+[.)]?)$/;
const THEMATIC_BREAK = /^([-*_])(?:[ \t]*\1){2,}$/;

export const INITIAL_SCAN_CURSOR: MarkdownScanCursor = Object.freeze({
  codeFence: null,
  inMathBlock: false,
  inList: false,
  listPendingBlank: false,
  inTable: false,
  inBlockquote: false,
  inIndentedCode: false,
  indentedCodePendingBlank: false,
  hadBlankLine: false,
  hadContent: false,
  offset: 0,
});

export const INITIAL_SCAN_STATE: MarkdownScanState = Object.freeze({
  chunks: Object.freeze([]),
  committedEnd: 0,
  previousText: "",
  cursor: INITIAL_SCAN_CURSOR,
});

function trimTrailingWhitespace(value: string): string {
  let end = value.length;
  while (end > 0) {
    const code = value.charCodeAt(end - 1);
    if (code !== 9 && code !== 10 && code !== 13 && code !== 32) break;
    end -= 1;
  }
  return end === value.length ? value : value.slice(0, end);
}

type BlockFlags = Pick<
  MarkdownScanCursor,
  | "codeFence"
  | "inMathBlock"
  | "inList"
  | "inTable"
  | "inBlockquote"
  | "inIndentedCode"
>;

function insideAnyBlock(cursor: BlockFlags): boolean {
  return (
    cursor.codeFence !== null ||
    cursor.inMathBlock ||
    cursor.inList ||
    cursor.inTable ||
    cursor.inBlockquote ||
    cursor.inIndentedCode
  );
}

interface ScanSuffixResult {
  readonly boundaries: readonly number[];
  readonly nextCursor: MarkdownScanCursor;
}

/**
 * Scan only the suffix beginning at cursor.offset.
 *
 * The final physical line is deliberately not committed into nextCursor. A
 * streaming append can still change that line from `-` into `- item`, from
 * ``` into a longer fence, or from plain text into a table/list construct.
 */
function scanSuffix(text: string, cursor: MarkdownScanCursor): ScanSuffixResult {
  const lines = text.slice(cursor.offset).split("\n");
  const finalLineIndex = lines.length - 1;
  const boundaries: number[] = [];

  let codeFence = cursor.codeFence;
  let inMathBlock = cursor.inMathBlock;
  let inList = cursor.inList;
  let listPendingBlank = cursor.listPendingBlank;
  let inTable = cursor.inTable;
  let inBlockquote = cursor.inBlockquote;
  let inIndentedCode = cursor.inIndentedCode;
  let indentedCodePendingBlank = cursor.indentedCodePendingBlank;
  let hadBlankLine = cursor.hadBlankLine;
  let hadContent = cursor.hadContent;
  let absoluteOffset = cursor.offset;
  let nextCursor = cursor;

  for (let index = 0; index < lines.length; index += 1) {
    if (index === finalLineIndex) {
      nextCursor = {
        codeFence,
        inMathBlock,
        inList,
        listPendingBlank,
        inTable,
        inBlockquote,
        inIndentedCode,
        indentedCodePendingBlank,
        hadBlankLine,
        hadContent,
        offset: absoluteOffset,
      };
    }

    const line = lines[index] ?? "";
    const trimmed = line.trim();
    const isBlank = BLANK_LINE.test(line);
    const isIndented = INDENTED_CODE.test(line);
    const wasInsideFence = codeFence !== null;
    const blockStateBefore = {
      codeFence,
      inMathBlock,
      inList,
      inTable,
      inBlockquote,
      inIndentedCode,
    };
    const wasInsideAnyBlock = insideAnyBlock(blockStateBefore);

    let exitedIndentedCodeAfterBlank = false;
    if (inIndentedCode) {
      if (isBlank) {
        indentedCodePendingBlank = true;
      } else {
        if (!isIndented) {
          inIndentedCode = false;
          exitedIndentedCodeAfterBlank = indentedCodePendingBlank;
        }
        indentedCodePendingBlank = false;
      }
    } else if (
      isIndented &&
      !isBlank &&
      !wasInsideAnyBlock &&
      (hadBlankLine || !hadContent)
    ) {
      inIndentedCode = true;
      indentedCodePendingBlank = false;
    }

    // Fences inside math/indented code are data, not Markdown fences.
    const fenceMatch =
      isIndented || inMathBlock || inIndentedCode
        ? null
        : trimmed.match(FENCE_START);
    if (fenceMatch?.[1]) {
      const marker = fenceMatch[1];
      const char = marker[0] as "`" | "~";
      if (codeFence === null) {
        codeFence = { char, length: marker.length };
      } else if (
        char === codeFence.char &&
        marker.length >= codeFence.length &&
        trimmed.length === marker.length
      ) {
        codeFence = null;
      }
    }

    let exitedListAfterBlank = false;
    const mathStateBefore = inMathBlock;
    if (!wasInsideFence && !inIndentedCode) {
      if (trimmed === "$$") inMathBlock = !inMathBlock;

      // On a closing $$ line, do not reinterpret the same line as another
      // block construct. On an opening line this conservative scanner may
      // still update the surrounding state, matching the observed behavior.
      if (!mathStateBefore) {
        const isThematicBreak = THEMATIC_BREAK.test(trimmed);
        const isListMarker = !isIndented && !isThematicBreak && LIST_MARKER.test(trimmed);

        if (isListMarker) {
          inList = true;
          listPendingBlank = false;
        } else if (inList && isBlank) {
          listPendingBlank = true;
        } else if (inList && listPendingBlank) {
          if (/^[ \t]/.test(line)) {
            listPendingBlank = false;
          } else {
            inList = false;
            listPendingBlank = false;
            exitedListAfterBlank = true;
          }
        }

        if (trimmed.includes("|")) {
          inTable = true;
        } else if (inTable && isBlank) {
          inTable = false;
        }

        if (!isIndented && trimmed.startsWith(">")) {
          inBlockquote = true;
        } else if (inBlockquote && isBlank) {
          inBlockquote = false;
        }
      }
    }

    if (isBlank) {
      const blockStateAfter = {
        codeFence,
        inMathBlock,
        inList,
        inTable,
        inBlockquote,
        inIndentedCode,
      };
      const isInsideAfter = insideAnyBlock(blockStateAfter);
      if (
        (!wasInsideAnyBlock && hadContent) ||
        (wasInsideAnyBlock && !isInsideAfter)
      ) {
        hadBlankLine = true;
      }
    } else if (exitedIndentedCodeAfterBlank) {
      boundaries.push(absoluteOffset);
      hadBlankLine = false;
    } else if (
      !exitedListAfterBlank ||
      (index === finalLineIndex && BARE_LIST_MARKER.test(trimmed))
    ) {
      if (hadBlankLine && !wasInsideAnyBlock) {
        boundaries.push(absoluteOffset);
        hadBlankLine = false;
      }
    } else {
      boundaries.push(absoluteOffset);
      hadBlankLine = false;
    }

    if (!isBlank) hadContent = true;
    absoluteOffset += line.length + 1;
  }

  return { boundaries, nextCursor };
}

/**
 * Incrementally discover block-safe commit points in append-only Markdown.
 * Completed chunks preserve their object identity until a new boundary is
 * committed, which is important for React.memo.
 */
export function scanIncrementalMarkdown(
  previous: MarkdownScanState,
  text: string,
  enabled = true,
): MarkdownScanState {
  if (!enabled || text.length === 0) return INITIAL_SCAN_STATE;
  if (text === previous.previousText) return previous;

  const base = text.startsWith(previous.previousText)
    ? previous
    : INITIAL_SCAN_STATE;
  const { boundaries, nextCursor } = scanSuffix(text, base.cursor);
  const newBoundaries = boundaries.filter(
    (boundary) => boundary > base.committedEnd,
  );

  let chunks = base.chunks;
  let committedEnd = base.committedEnd;

  if (newBoundaries.length > 0) {
    const additions: MarkdownChunk[] = [];
    let start = base.committedEnd;
    for (const boundary of newBoundaries) {
      const chunkText = trimTrailingWhitespace(text.slice(start, boundary));
      if (chunkText.length > 0) {
        additions.push({ text: chunkText, offset: start });
      }
      start = boundary;
    }
    if (additions.length > 0) chunks = [...base.chunks, ...additions];
    committedEnd = newBoundaries[newBoundaries.length - 1] ?? committedEnd;
  }

  return {
    chunks,
    committedEnd,
    previousText: text,
    cursor: nextCursor,
  };
}

export function splitSettledMarkdown(text: string): readonly MarkdownChunk[] {
  if (text.length === 0) return [];
  const scanned = scanIncrementalMarkdown(INITIAL_SCAN_STATE, text, true);
  const remainder = text.slice(scanned.committedEnd);
  return remainder.length > 0
    ? [
        ...scanned.chunks,
        { text: remainder, offset: scanned.committedEnd },
      ]
    : scanned.chunks;
}

export function resolveProgressiveChunks(
  text: string,
  isStreaming: boolean,
  hasEverStreamed: boolean,
  scanState: MarkdownScanState,
): ProgressiveChunkResult {
  if (isStreaming) {
    return {
      completedChunks: scanState.chunks,
      streamingChunk: text.slice(scanState.committedEnd),
      streamingChunkOffset: scanState.committedEnd,
    };
  }

  if (hasEverStreamed) {
    return {
      completedChunks: splitSettledMarkdown(text),
      streamingChunk: "",
      streamingChunkOffset: text.length,
    };
  }

  return {
    completedChunks: [],
    streamingChunk: text,
    streamingChunkOffset: 0,
  };
}
