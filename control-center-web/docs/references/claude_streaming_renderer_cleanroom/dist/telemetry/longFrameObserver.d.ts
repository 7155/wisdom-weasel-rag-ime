export interface LongFrameStats {
    readonly supported: boolean;
    readonly count: number;
    readonly blockedMsTotal: number;
    readonly blockedMsMax: number;
    readonly durationMsTotal: number;
}
export interface LongFrameObserver {
    readonly supported: boolean;
    snapshot(): LongFrameStats;
    stop(): LongFrameStats;
}
/** Observe Chromium Long Animation Frame entries when available. */
export declare function observeLongAnimationFrames(): LongFrameObserver;
export interface StreamRenderSample {
    readonly updateCount: number;
    readonly plainUpdateCount: number;
    readonly streamMs: number;
    readonly textLength: number;
    readonly lineCount: number;
    readonly longFrames: LongFrameStats;
}
/**
 * Minimal measurement helper for A/B testing the renderer in a real browser.
 * Call update() whenever visible code grows and finish() at stream completion.
 */
export declare function createStreamRenderProbe(): {
    update(options: {
        readonly text: string;
        readonly highlighted: boolean;
    }): void;
    finish(): StreamRenderSample;
};
//# sourceMappingURL=longFrameObserver.d.ts.map