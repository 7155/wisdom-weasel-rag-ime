// Markdown outline for the Knowledge reading desk. The extractor mirrors what
// react-markdown/remark-gfm will actually render as headings, so the 目录 can
// address rendered DOM headings by plain text + occurrence. It intentionally
// stays a pure line scanner: content arrives as numbered line windows and the
// outline must stay honest about which lines it has seen.

export interface MarkdownOutlineItem {
  /** Stable id derived from the source line number. */
  id: string;
  /** Position inside the outline (for occurrence matching). */
  index: number;
  /** Heading depth 1–6. */
  level: number;
  /** Plain heading text as the DOM will render it. */
  text: string;
  /** 1-based source line the heading starts on. */
  lineNumber: number;
}

interface NumberedLine {
  lineNumber: number;
  content: string;
}

const FENCE_PATTERN = /^ {0,3}(`{3,}|~{3,})(.*)$/u;
const ATX_PATTERN = /^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$/u;
const SETEXT_PATTERN = /^ {0,3}(=+|-+)[ \t]*$/u;
// Lines that cannot be the paragraph half of a setext heading.
const NON_PARAGRAPH_PATTERN = /^ {0,3}(?:[>|]|#{1,6}[ \t]|[-+*][ \t]|\d{1,9}[.)][ \t])/u;

export function extractMarkdownOutline(lines: readonly NumberedLine[]): MarkdownOutlineItem[] {
  const items: MarkdownOutlineItem[] = [];
  let fence: { marker: string; length: number } | null = null;
  let paragraph: NumberedLine | null = null;
  const push = (level: number, rawText: string, lineNumber: number) => {
    const text = plainHeadingText(rawText);
    if (!text) return;
    items.push({ id: `knowledge-heading-${lineNumber}`, index: items.length, level, text, lineNumber });
  };

  for (const line of lines) {
    const fenceMatch = FENCE_PATTERN.exec(line.content);
    if (fenceMatch) {
      const [, marker, rest] = fenceMatch;
      if (!fence) {
        fence = { marker: marker[0], length: marker.length };
        paragraph = null;
        continue;
      }
      if (marker[0] === fence.marker && marker.length >= fence.length && !rest.trim()) {
        fence = null;
        paragraph = null;
        continue;
      }
    }
    if (fence) continue;

    const atx = ATX_PATTERN.exec(line.content);
    if (atx) {
      push(atx[1].length, (atx[2] ?? '').replace(/[ \t]+#+[ \t]*$/u, ''), line.lineNumber);
      paragraph = null;
      continue;
    }

    const setext = SETEXT_PATTERN.exec(line.content);
    if (setext && paragraph) {
      push(setext[1][0] === '=' ? 1 : 2, paragraph.content, paragraph.lineNumber);
      paragraph = null;
      continue;
    }

    paragraph = line.content.trim() && !NON_PARAGRAPH_PATTERN.test(line.content) ? line : null;
  }
  return items;
}

/** Strip common inline Markdown so the text matches rendered `textContent`. */
export function plainHeadingText(value: string): string {
  return value
    .replace(/!\[([^\]]*)\]\([^)]*\)/gu, '$1')
    .replace(/\[([^\]]*)\]\([^)]*\)/gu, '$1')
    .replace(/`+([^`]*)`+/gu, '$1')
    .replace(/(\*\*|__)(.+?)\1/gu, '$2')
    .replace(/~~(.+?)~~/gu, '$1')
    .replace(/(^|[^\w*])\*([^*]+)\*(?=[^\w*]|$)/gu, '$1$2')
    .replace(/(^|[^\w_])_([^_]+)_(?=[^\w_]|$)/gu, '$1$2')
    .replace(/\s+/gu, ' ')
    .trim();
}
