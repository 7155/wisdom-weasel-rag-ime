export type NestedCodeBlockMode = "markdown-document" | "code-in-markdown";
export interface NormalizeStreamingMarkdownOptions {
    readonly isStreaming?: boolean;
    readonly nestedCodeBlockMode?: NestedCodeBlockMode;
}
/**
 * Small pre-parse repairs for model-generated Markdown. This is deliberately
 * separate from the block scanner so callers can replace or disable it.
 */
export declare function normalizeStreamingMarkdown(input: unknown, options?: NormalizeStreamingMarkdownOptions): string;
//# sourceMappingURL=normalizeStreamingMarkdown.d.ts.map