import { type ReactNode } from "react";
import { type StatefulLineTokenizer } from "../core/incrementalTokenizer.js";
export interface DisplayToken {
    readonly content: string;
    readonly color?: string;
    readonly fontStyle?: number;
}
export interface IncrementalCodeBlockProps<TState = unknown> {
    readonly code: string;
    readonly language?: string | undefined;
    readonly streaming: boolean;
    readonly tokenizer?: StatefulLineTokenizer<DisplayToken, TState> | undefined;
    readonly className?: string | undefined;
    readonly showLineNumbers?: boolean | undefined;
    readonly maxHighlightedChars?: number | undefined;
    readonly renderToken?: ((token: DisplayToken, key: string) => ReactNode) | undefined;
}
/**
 * Highlights only complete physical lines. The unfinished final line remains
 * plain while streaming, then receives one final tokenization after settle.
 */
export declare function IncrementalCodeBlock<TState = unknown>(props: IncrementalCodeBlockProps<TState>): ReactNode;
//# sourceMappingURL=IncrementalCodeBlock.d.ts.map