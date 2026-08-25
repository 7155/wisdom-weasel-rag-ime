import { type ComponentProps, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import type { StatefulLineTokenizer } from "../core/incrementalTokenizer.js";
import { type DisplayToken } from "./IncrementalCodeBlock.js";
export interface ReactMarkdownProgressiveProps {
    readonly text: string;
    readonly isStreaming: boolean;
    readonly documentKey: string;
    readonly className?: string | undefined;
    readonly holdBack?: boolean | undefined;
    readonly openFenceFastPath?: boolean | undefined;
    readonly showLineNumbers?: boolean | undefined;
    readonly renderVersion?: string | number | undefined;
    readonly components?: ComponentProps<typeof ReactMarkdown>["components"] | undefined;
    readonly createTokenizer?: ((language: string) => StatefulLineTokenizer<DisplayToken, unknown> | undefined) | undefined;
    readonly onFirstPaint?: (() => void) | undefined;
    readonly onSettledCommit?: ((timestamp: number) => void) | undefined;
}
/**
 * Ready-to-use adapter. It parses completed Markdown chunks independently
 * while streaming, and bypasses repeated Markdown parsing for a growing open
 * fenced code block.
 */
export declare function ReactMarkdownProgressive(props: ReactMarkdownProgressiveProps): ReactNode;
//# sourceMappingURL=ReactMarkdownAdapter.d.ts.map