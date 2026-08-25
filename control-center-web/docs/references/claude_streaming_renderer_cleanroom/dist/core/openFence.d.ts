export interface OpenFenceTail {
    readonly marker: "`" | "~";
    readonly markerLength: number;
    readonly openingLineStart: number;
    readonly openingLineEnd: number;
    /** Markdown before the opening fence. */
    readonly prefix: string;
    /** Text through the opening fence line, excluding its newline. */
    readonly parseHead: string;
    readonly info: string;
    readonly language: string;
    readonly value: string;
    readonly end: {
        readonly line: number;
        readonly column: number;
        readonly offset: number;
    };
}
/**
 * Detect a top-level fenced code block that is still open at the end of a
 * streaming Markdown tail. The conservative exclusions avoid front matter,
 * CR/NUL normalization ambiguity, and nested constructs that need a full
 * parser.
 */
export declare function detectOpenFenceTail(text: string): OpenFenceTail | null;
//# sourceMappingURL=openFence.d.ts.map