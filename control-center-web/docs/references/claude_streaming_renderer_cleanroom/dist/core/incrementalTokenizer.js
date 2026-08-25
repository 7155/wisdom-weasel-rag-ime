function splitCompleteLines(code) {
    const completeLines = [];
    const newline = /\r?\n/g;
    let start = 0;
    for (let match = newline.exec(code); match; match = newline.exec(code)) {
        completeLines.push({
            text: code.slice(start, match.index),
            separator: match[0],
        });
        start = match.index + match[0].length;
    }
    return { completeLines, trailingText: code.slice(start) };
}
/**
 * Stateful line tokenizer. Complete line objects keep identity; appending to
 * the unfinished line does not retokenize any earlier line.
 */
export class IncrementalLineTokenizer {
    tokenizer;
    cached = [];
    tokenizerKey;
    constructor(tokenizer) {
        this.tokenizer = tokenizer;
        this.tokenizerKey = tokenizer.key;
    }
    setTokenizer(tokenizer) {
        if (tokenizer.key !== this.tokenizerKey) {
            this.cached = [];
            this.tokenizerKey = tokenizer.key;
        }
        this.tokenizer = tokenizer;
    }
    reset() {
        this.cached = [];
    }
    update(code, options) {
        const { completeLines, trailingText } = splitCompleteLines(code);
        let commonPrefix = 0;
        while (commonPrefix < this.cached.length &&
            commonPrefix < completeLines.length) {
            const cached = this.cached[commonPrefix];
            const incoming = completeLines[commonPrefix];
            if (!cached ||
                !incoming ||
                cached.text !== incoming.text ||
                cached.separator !== incoming.separator) {
                break;
            }
            commonPrefix += 1;
        }
        if (this.cached.length > commonPrefix) {
            this.cached.length = commonPrefix;
        }
        for (let index = commonPrefix; index < completeLines.length; index += 1) {
            const physical = completeLines[index];
            if (!physical)
                continue;
            const previous = this.cached[index - 1];
            const stateBefore = previous
                ? previous.stateAfter
                : this.tokenizer.initialState;
            const startOffset = previous
                ? previous.startOffset + previous.text.length + previous.separator.length
                : 0;
            const result = this.tokenizer.tokenizeLine(physical.text, stateBefore);
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
export const plainLineTokenizer = {
    key: "plain",
    initialState: null,
    tokenizeLine(line) {
        return { tokens: [{ content: line }], stateAfter: null };
    },
};
//# sourceMappingURL=incrementalTokenizer.js.map