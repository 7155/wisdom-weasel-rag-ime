export interface TokenizeLineResult<TToken, TState> {
  readonly tokens: readonly TToken[];
  readonly stateAfter: TState;
}

export interface StatefulLineTokenizer<TToken, TState> {
  readonly key: string;
  readonly initialState: TState;
  tokenizeLine(
    line: string,
    stateBefore: TState,
  ): TokenizeLineResult<TToken, TState>;
}

export interface CachedTokenLine<TToken, TState> {
  readonly text: string;
  readonly separator: "" | "\n" | "\r\n";
  readonly startOffset: number;
  readonly tokens: readonly TToken[];
  readonly stateAfter: TState;
}

export interface IncrementalTokenSnapshot<TToken, TState> {
  readonly completeLines: readonly CachedTokenLine<TToken, TState>[];
  /** During streaming, the unfinished final line remains cheap/plain. */
  readonly partialText: string;
  /** Present only after finalization, when the final line has been tokenized. */
  readonly partialTokens?: readonly TToken[];
}

interface PhysicalLine {
  readonly text: string;
  readonly separator: "\n" | "\r\n";
}

function splitCompleteLines(code: string): {
  readonly completeLines: readonly PhysicalLine[];
  readonly trailingText: string;
} {
  const completeLines: PhysicalLine[] = [];
  const newline = /\r?\n/g;
  let start = 0;
  for (let match = newline.exec(code); match; match = newline.exec(code)) {
    completeLines.push({
      text: code.slice(start, match.index),
      separator: match[0] as "\n" | "\r\n",
    });
    start = match.index + match[0].length;
  }
  return { completeLines, trailingText: code.slice(start) };
}

/**
 * Stateful line tokenizer. Complete line objects keep identity; appending to
 * the unfinished line does not retokenize any earlier line.
 */
export class IncrementalLineTokenizer<TToken, TState> {
  private cached: CachedTokenLine<TToken, TState>[] = [];
  private tokenizerKey: string;

  public constructor(
    private tokenizer: StatefulLineTokenizer<TToken, TState>,
  ) {
    this.tokenizerKey = tokenizer.key;
  }

  public setTokenizer(
    tokenizer: StatefulLineTokenizer<TToken, TState>,
  ): void {
    if (tokenizer.key !== this.tokenizerKey) {
      this.cached = [];
      this.tokenizerKey = tokenizer.key;
    }
    this.tokenizer = tokenizer;
  }

  public reset(): void {
    this.cached = [];
  }

  public update(
    code: string,
    options: { readonly streaming: boolean },
  ): IncrementalTokenSnapshot<TToken, TState> {
    const { completeLines, trailingText } = splitCompleteLines(code);

    let commonPrefix = 0;
    while (
      commonPrefix < this.cached.length &&
      commonPrefix < completeLines.length
    ) {
      const cached = this.cached[commonPrefix];
      const incoming = completeLines[commonPrefix];
      if (
        !cached ||
        !incoming ||
        cached.text !== incoming.text ||
        cached.separator !== incoming.separator
      ) {
        break;
      }
      commonPrefix += 1;
    }

    if (this.cached.length > commonPrefix) {
      this.cached.length = commonPrefix;
    }

    for (let index = commonPrefix; index < completeLines.length; index += 1) {
      const physical = completeLines[index];
      if (!physical) continue;
      const previous = this.cached[index - 1];
      const stateBefore = previous
        ? previous.stateAfter
        : this.tokenizer.initialState;
      const startOffset = previous
        ? previous.startOffset + previous.text.length + previous.separator.length
        : 0;
      const result = this.tokenizer.tokenizeLine(
        physical.text,
        stateBefore,
      );
      this.cached.push({
        text: physical.text,
        separator: physical.separator,
        startOffset,
        tokens: result.tokens,
        stateAfter: result.stateAfter,
      });
    }

    if (options.streaming) {
      return {
        completeLines: this.cached,
        partialText: trailingText,
      };
    }

    const previous = this.cached[this.cached.length - 1];
    const stateBefore = previous
      ? previous.stateAfter
      : this.tokenizer.initialState;
    const partial = this.tokenizer.tokenizeLine(trailingText, stateBefore);
    return {
      completeLines: this.cached,
      partialText: trailingText,
      partialTokens: partial.tokens,
    };
  }
}

export interface PlainToken {
  readonly content: string;
}

export const plainLineTokenizer: StatefulLineTokenizer<PlainToken, null> = {
  key: "plain",
  initialState: null,
  tokenizeLine(line) {
    return { tokens: [{ content: line }], stateAfter: null };
  },
};
