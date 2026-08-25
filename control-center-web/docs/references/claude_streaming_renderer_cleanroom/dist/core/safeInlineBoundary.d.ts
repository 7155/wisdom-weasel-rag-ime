/** Return a conservative display boundary at or before limit. */
export declare function findSafeInlineBoundary(text: string, limit?: number): number;
/**
 * Do not let hold-back grow without bound. A very long unresolved construct is
 * eventually shown as plain/incomplete text rather than freezing the UI.
 */
export declare function computeReleaseCeiling(text: string, maxHoldBackChars?: number): number;
export declare function advanceToSafeBoundary(text: string, current: number, ceiling: number, stepChars?: number): number;
//# sourceMappingURL=safeInlineBoundary.d.ts.map