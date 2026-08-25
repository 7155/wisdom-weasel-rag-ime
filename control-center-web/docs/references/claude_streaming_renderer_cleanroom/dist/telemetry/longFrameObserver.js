function emptyStats(supported) {
    return {
        supported,
        count: 0,
        blockedMsTotal: 0,
        blockedMsMax: 0,
        durationMsTotal: 0,
    };
}
/** Observe Chromium Long Animation Frame entries when available. */
export function observeLongAnimationFrames() {
    const supported = typeof PerformanceObserver !== "undefined" &&
        (PerformanceObserver.supportedEntryTypes ?? []).includes("long-animation-frame");
    if (!supported) {
        const stats = emptyStats(false);
        return {
            supported: false,
            snapshot: () => stats,
            stop: () => stats,
        };
    }
    let count = 0;
    let blockedMsTotal = 0;
    let blockedMsMax = 0;
    let durationMsTotal = 0;
    let stopped = false;
    const consume = (entries) => {
        for (const raw of entries) {
            const entry = raw;
            const blocked = entry.blockingDuration ?? entry.duration;
            count += 1;
            blockedMsTotal += blocked;
            blockedMsMax = Math.max(blockedMsMax, blocked);
            durationMsTotal += entry.duration;
        }
    };
    let observer;
    try {
        observer = new PerformanceObserver((list) => consume(list.getEntries()));
        observer.observe({ type: "long-animation-frame" });
    }
    catch {
        const stats = emptyStats(false);
        return {
            supported: false,
            snapshot: () => stats,
            stop: () => stats,
        };
    }
    const snapshot = () => ({
        supported: true,
        count,
        blockedMsTotal,
        blockedMsMax,
        durationMsTotal,
    });
    return {
        supported: true,
        snapshot,
        stop() {
            if (!stopped) {
                stopped = true;
                consume(observer?.takeRecords() ?? []);
                observer?.disconnect();
                observer = undefined;
            }
            return snapshot();
        },
    };
}
/**
 * Minimal measurement helper for A/B testing the renderer in a real browser.
 * Call update() whenever visible code grows and finish() at stream completion.
 */
export function createStreamRenderProbe() {
    const startedAt = performance.now();
    const frames = observeLongAnimationFrames();
    let updateCount = 0;
    let plainUpdateCount = 0;
    let latestText = "";
    return {
        update({ text, highlighted }) {
            if (text.length <= latestText.length) {
                latestText = text;
                return;
            }
            latestText = text;
            updateCount += 1;
            if (!highlighted)
                plainUpdateCount += 1;
        },
        finish() {
            return {
                updateCount,
                plainUpdateCount,
                streamMs: performance.now() - startedAt,
                textLength: latestText.length,
                lineCount: latestText.length === 0 ? 0 : latestText.split(/\r?\n/).length,
                longFrames: frames.stop(),
            };
        },
    };
}
//# sourceMappingURL=longFrameObserver.js.map