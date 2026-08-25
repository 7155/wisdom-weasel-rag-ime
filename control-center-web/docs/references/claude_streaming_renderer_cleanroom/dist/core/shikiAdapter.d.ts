import type { StatefulLineTokenizer } from "./incrementalTokenizer.js";
export interface ShikiLikeToken {
    readonly content: string;
    readonly color?: string;
    readonly fontStyle?: number;
    readonly offset?: number;
}
export interface ShikiLikeHighlighter<TState = unknown> {
    codeToTokensBase(code: string, options: {
        readonly lang: string;
        readonly theme: string;
        readonly grammarState?: TState;
        readonly tokenizeTimeLimit?: number;
    }): readonly (readonly ShikiLikeToken[])[];
    getLastGrammarState(rows: readonly (readonly ShikiLikeToken[])[]): TState | undefined;
}
/**
 * Adapter for Shiki builds that expose grammarState/getLastGrammarState.
 * These are advanced APIs; pin the Shiki version in production.
 */
export declare function createShikiStatefulTokenizer<TState>(options: {
    readonly highlighter: ShikiLikeHighlighter<TState>;
    readonly language: string;
    readonly theme: string;
    readonly initialState: TState;
    readonly tokenizeTimeLimitMs?: number;
}): StatefulLineTokenizer<ShikiLikeToken, TState>;
//# sourceMappingURL=shikiAdapter.d.ts.map