export const MAX_CONVERSATION_MARKERS = 64;

/**
 * The transcript body is virtualized, so its companion navigator must not
 * quietly recreate one DOM node per historical turn. Keep evenly distributed
 * landmarks, the two ends, and the turn currently in the viewport.
 */
export function conversationMarkerIndexes(
  total: number,
  activeIndex: number,
  maxMarkers = MAX_CONVERSATION_MARKERS,
): number[] {
  const normalizedTotal = Math.max(0, Math.floor(total));
  if (normalizedTotal === 0) return [];
  const normalizedActive = clamp(
    Math.floor(activeIndex),
    0,
    normalizedTotal - 1,
  );
  const markerCount = Math.min(
    normalizedTotal,
    Math.max(1, Math.floor(maxMarkers)),
  );
  if (normalizedTotal <= markerCount) {
    return Array.from({ length: normalizedTotal }, (_, index) => index);
  }
  if (markerCount === 1) return [normalizedActive];

  const indexes = Array.from({ length: markerCount }, (_, slot) => (
    Math.round((slot * (normalizedTotal - 1)) / (markerCount - 1))
  ));
  if (indexes.includes(normalizedActive)) return indexes;

  // Preserve the first/last landmarks. Replace the closest interior sample so
  // aria-current always has a real marker without growing the bounded list.
  const replaceableStart = markerCount > 2 ? 1 : 0;
  const replaceableEnd = markerCount > 2 ? markerCount - 1 : markerCount;
  let replacement = replaceableStart;
  for (let position = replaceableStart + 1; position < replaceableEnd; position += 1) {
    if (
      Math.abs(indexes[position]! - normalizedActive)
      < Math.abs(indexes[replacement]! - normalizedActive)
    ) {
      replacement = position;
    }
  }
  indexes[replacement] = normalizedActive;
  return indexes.sort((left, right) => left - right);
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}
