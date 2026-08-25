export interface SafeTextReleaseOptions {
    readonly enabled: boolean;
    readonly stepChars?: number | undefined;
    readonly minimumIntervalMs?: number | undefined;
    readonly maximumIntervalMs?: number | undefined;
    readonly backlogBudgetMs?: number | undefined;
    readonly maximumHoldBackChars?: number | undefined;
}
/**
 * Releases streaming text at Markdown-safe inline boundaries. The rAF loop is
 * a display scheduler, not a replacement for transport/event batching.
 */
export declare function useSafeTextRelease(text: string, options: SafeTextReleaseOptions): string;
//# sourceMappingURL=useSafeTextRelease.d.ts.map