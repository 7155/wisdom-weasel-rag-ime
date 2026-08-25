/**
 * Adapter for Shiki builds that expose grammarState/getLastGrammarState.
 * These are advanced APIs; pin the Shiki version in production.
 */
export function createShikiStatefulTokenizer(options) {
    const { highlighter, language, theme, initialState, tokenizeTimeLimitMs = 2_000, } = options;
    return {
        key: `shiki:${language}:${theme}`,
        initialState,
        tokenizeLine(line, stateBefore) {
            const rows = highlighter.codeToTokensBase(line, {
                lang: language,
                theme,
                grammarState: stateBefore,
                tokenizeTimeLimit: tokenizeTimeLimitMs,
            });
            const stateAfter = highlighter.getLastGrammarState(rows);
            if (stateAfter === undefined) {
                throw new Error("Shiki did not return a grammar state");
            }
            return {
                tokens: rows[0] ?? [{ content: line }],
                stateAfter,
            };
        },
    };
}
//# sourceMappingURL=shikiAdapter.js.map