/**
 * Keep the progressive renderer active for one deferred React render after the
 * transport reports completion. That gives the final full-document parse a
 * clean transition instead of swapping render modes in the same urgent update.
 */
export declare function useDeferredStreaming(isStreaming: boolean): boolean;
//# sourceMappingURL=useDeferredStreaming.d.ts.map