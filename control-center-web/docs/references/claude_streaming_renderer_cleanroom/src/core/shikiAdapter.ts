import type { StatefulLineTokenizer } from "./incrementalTokenizer.js";

export interface ShikiLikeToken {
  readonly content: string;
  readonly color?: string;
  readonly fontStyle?: number;
  readonly offset?: number;
}

export interface ShikiLikeHighlighter<TState = unknown> {
  codeToTokensBase(
    code: string,
    options: {
      readonly lang: string;
      readonly theme: string;
      readonly grammarState?: TState;
      readonly tokenizeTimeLimit?: number;
    },
  ): readonly (readonly ShikiLikeToken[])[];
  getLastGrammarState(
    rows: readonly (readonly ShikiLikeToken[])[],
  ): TState | undefined;
}

/**
 * Adapter for Shiki builds that expose grammarState/getLastGrammarState.
 * These are advanced APIs; pin the Shiki version in production.
 */
export function createShikiStatefulTokenizer<TState>(options: {
  readonly highlighter: ShikiLikeHighlighter<TState>;
  readonly language: string;
  readonly theme: string;
  readonly initialState: TState;
  readonly tokenizeTimeLimitMs?: number;
}): StatefulLineTokenizer<ShikiLikeToken, TState> {
  const {
    highlighter,
    language,
    theme,
    initialState,
    tokenizeTimeLimitMs = 2_000,
  } = options;

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
