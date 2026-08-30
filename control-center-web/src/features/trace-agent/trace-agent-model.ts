export type TraceTargetKind = 'session' | 'room' | 'run';

export const TRACE_AGENT_MAX_TARGETS = 12;

/**
 * The server uses the same kind/id pair as the durable target identity.  Keep
 * this in one place so selection state, report links, and visual status cannot
 * accidentally key only by a bare id.
 */
export function traceTargetKey(kind: TraceTargetKind, id: string): string {
  return `${kind}:${id}`;
}

/**
 * A report color is only an identity aid.  It must never be interpreted as a
 * severity or score.  HSL derived from the stable key avoids color changing
 * after a refetch while giving adjacent target keys visibly different hues.
 */
export function traceTargetColorToken(targetKey: string): string {
  let hash = 0;
  for (const character of targetKey) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  const hue = hash % 360;
  const saturation = 62 + (hash % 12);
  const lightness = 42 + (hash % 10);
  return `hsl(${hue} ${saturation}% ${lightness}%)`;
}

export function toggleTraceTargetSelection(
  selectedKeys: readonly string[],
  targetKey: string,
  maximum = TRACE_AGENT_MAX_TARGETS,
): string[] {
  const current = [...new Set(selectedKeys)];
  const index = current.indexOf(targetKey);
  if (index >= 0) {
    current.splice(index, 1);
    return current;
  }
  if (current.length >= maximum) return current;
  current.push(targetKey);
  return current;
}
