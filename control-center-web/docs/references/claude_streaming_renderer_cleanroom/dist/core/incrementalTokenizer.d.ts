export interface TokenizeLineResult<TToken, TState> {
    readonly tokens: readonly TToken[];
    readonly stateAfter: TState;
}
export interface StatefulLineTokenizer<TToken, TState> {
    readonly key: string;
    readonly initialState: TState;
    tokenizeLine(line: string, stateBefore: TState): TokenizeLineResult<TToken, TState>;
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
/**
 * Stateful line tokenizer. Complete line objects keep identity; appending to
 * the unfinished line does not retokenize any earlier line.
 */
export declare class IncrementalLineTokenizer<TToken, TState> {
    private tokenizer;
    private cached;
    private tokenizerKey;
    constructor(tokenizer: StatefulLineTokenizer<TToken, TState>);
    setTokenizer(tokenizer: StatefulLineTokenizer<TToken, TState>): void;
    reset(): void;
    update(code: string, options: {
        readonly streaming: boolean;
    }): IncrementalTokenSnapshot<TToken, TState>;
}
export interface PlainToken {
    readonly content: string;
}
export declare const plainLineTokenizer: StatefulLineTokenizer<PlainToken, null>;
//# sourceMappingURL=incrementalTokenizer.d.ts.map