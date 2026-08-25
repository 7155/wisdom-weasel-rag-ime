export type NestedCodeBlockMode = "markdown-document" | "code-in-markdown";

export interface NormalizeStreamingMarkdownOptions {
  readonly isStreaming?: boolean;
  readonly nestedCodeBlockMode?: NestedCodeBlockMode;
}

interface FenceToken {
  readonly lineStart: number;
  readonly lineEnd: number;
  readonly indent: string;
  readonly width: number;
  readonly info: string;
  depth: number;
  closingToken?: FenceToken;
}

function normalizeBulletGlyphs(text: string): string {
  return text.replace(/(^|\n)([ \t]?)•([ \t]?)/g, "$1$2- ");
}

function collectBacktickFences(text: string): FenceToken[] {
  const tokens: FenceToken[] = [];
  const expression = /^([^\S\n\r\u2028\u2029]*)(`{3,})(.*)$/gm;

  for (const match of text.matchAll(expression)) {
    const full = match[0] ?? "";
    const indent = match[1] ?? "";
    const marker = match[2] ?? "";
    const trailing = match[3] ?? "";
    const lineStart = match.index ?? 0;
    tokens.push({
      lineStart,
      lineEnd: lineStart + full.length,
      indent,
      width: marker.length,
      info: trailing.trim(),
      depth: 0,
    });
  }

  return tokens;
}

/**
 * Claude accepts model output that sometimes contains a fenced code block
 * inside another fenced code block. CommonMark cannot represent that when both
 * levels use the same marker width, so this pass makes parent fences wider
 * than their children before parsing.
 */
function normalizeNestedBacktickFences(
  text: string,
  mode: NestedCodeBlockMode,
): string {
  const first = text.indexOf("```");
  if (first < 0 || text.indexOf("```", first + 3) < 0) return text;

  const tokens = collectBacktickFences(text);
  if (tokens.length === 0) return text;

  const stack: FenceToken[] = [];
  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index];
    if (!token) continue;

    if (token.info.length > 0 || stack.length === 0) {
      token.depth = stack.length;
      stack.push(token);
      continue;
    }

    const parent = stack[stack.length - 1];
    if (!parent) {
      token.depth = 0;
      stack.push(token);
      continue;
    }

    if (token.width < parent.width) {
      token.depth = stack.length;
      stack.push(token);
      continue;
    }

    // In a Markdown document embedded in a code block, a same-width empty
    // fence can itself be an example rather than the parent closer. Look for a
    // matching partner followed by another outer-level fence before deciding.
    let treatAsNestedExample = false;
    if (
      mode === "code-in-markdown" &&
      stack.length === 1 &&
      parent.info.length > 0
    ) {
      let partnerIndex = -1;
      for (let probe = index + 1; probe < tokens.length; probe += 1) {
        const candidate = tokens[probe];
        if (!candidate || candidate.info.length > 0) break;
        if (candidate.width === token.width) {
          partnerIndex = probe;
          break;
        }
      }

      if (partnerIndex >= 0) {
        const partner = tokens[partnerIndex];
        const after = tokens[partnerIndex + 1];
        if (partner && after) {
          const between = text.slice(partner.lineEnd, after.lineStart);
          treatAsNestedExample =
            after.width >= parent.width && between.trim().length === 0;
        }
      }
    }

    if (treatAsNestedExample) {
      token.depth = stack.length;
      stack.push(token);
      continue;
    }

    token.depth = Math.max(0, stack.length - 1);
    parent.closingToken = token;
    stack.pop();
  }

  const maxWidthByDepth = new Map<number, number>();
  let deepest = 0;
  for (const token of tokens) {
    deepest = Math.max(deepest, token.depth);
    maxWidthByDepth.set(
      token.depth,
      Math.max(maxWidthByDepth.get(token.depth) ?? 3, token.width),
    );
  }

  for (let depth = deepest - 1; depth >= 0; depth -= 1) {
    const own = maxWidthByDepth.get(depth) ?? 3;
    const child = maxWidthByDepth.get(depth + 1) ?? 0;
    if (child >= own) maxWidthByDepth.set(depth, child + 1);
  }

  const replacements: Array<{
    readonly start: number;
    readonly end: number;
    readonly value: string;
  }> = [];

  for (const token of tokens) {
    const required = maxWidthByDepth.get(token.depth) ?? token.width;
    const openingValue = `${"`".repeat(required)}${token.info}`;
    if (token.indent.length > 0 || required !== token.width) {
      replacements.push({
        start: token.lineStart,
        end: token.lineEnd,
        value: openingValue,
      });
    }

    const closing = token.closingToken;
    if (closing && (closing.indent.length > 0 || closing.width !== required)) {
      replacements.push({
        start: closing.lineStart,
        end: closing.lineEnd,
        value: "`".repeat(required),
      });
    }
  }

  // A closing token can also appear in the main iteration. Last write wins.
  const unique = new Map<number, (typeof replacements)[number]>();
  for (const replacement of replacements) unique.set(replacement.start, replacement);
  const ordered = [...unique.values()].sort((left, right) => left.start - right.start);
  if (ordered.length === 0) return text;

  let cursor = 0;
  let output = "";
  for (const replacement of ordered) {
    output += text.slice(cursor, replacement.start);
    output += replacement.value;
    cursor = replacement.end;
  }
  return output + text.slice(cursor);
}

function removeFenceIndentation(text: string): string {
  return text.replace(/^([^\S\n\r\u2028\u2029]*)(`{3,})/gm, "$2");
}

function hideIncompleteSetextUnderline(text: string): string {
  const finalNewline = text.lastIndexOf("\n");
  if (finalNewline < 0) return text;
  const finalLine = text.slice(finalNewline + 1);
  return /^\s{0,3}[-=]+\s*$/.test(finalLine)
    ? text.slice(0, finalNewline)
    : text;
}

/**
 * Small pre-parse repairs for model-generated Markdown. This is deliberately
 * separate from the block scanner so callers can replace or disable it.
 */
export function normalizeStreamingMarkdown(
  input: unknown,
  options: NormalizeStreamingMarkdownOptions = {},
): string {
  const {
    isStreaming = false,
    nestedCodeBlockMode = "code-in-markdown",
  } = options;

  let text = typeof input === "string" ? input : String(input ?? "");
  text = normalizeBulletGlyphs(text);
  text = normalizeNestedBacktickFences(text, nestedCodeBlockMode);
  text = removeFenceIndentation(text);
  if (isStreaming) text = hideIncompleteSetextUnderline(text);
  return text;
}
