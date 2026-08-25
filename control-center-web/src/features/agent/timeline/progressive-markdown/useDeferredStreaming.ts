import { useDeferredValue } from "react";

/**
 * Keep the progressive renderer active for one deferred React render after the
 * transport reports completion. That gives the final full-document parse a
 * clean transition instead of swapping render modes in the same urgent update.
 */
export function useDeferredStreaming(isStreaming: boolean): boolean {
  const deferred = useDeferredValue(isStreaming);
  return isStreaming || deferred;
}
