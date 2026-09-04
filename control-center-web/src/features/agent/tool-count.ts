import type { AgentActivityProjection } from '@/contracts/agent-reducer';

/**
 * Identify a real model Tool lifecycle row.
 *
 * The reducer normally folds start/progress/finish rows by toolCallId, but a
 * replay can contain the individual events as separate projection entries.
 * Keeping this predicate in one module prevents the composer, task panel and
 * Trace rail from reporting different numbers for the same execution.
 */
export function isCountableToolActivity(
  activity: AgentActivityProjection,
): boolean {
  const kind = activity.kind.toLowerCase();
  const toolId = text(activity.payload.toolId ?? activity.payload.toolName).toLowerCase();
  if (toolId === 'todo' || kind.includes('todo')) return false;
  return kind.startsWith('tool_') || kind.includes('browser');
}

/** Return one representative row for each logical Tool call, in timeline order. */
export function uniqueToolActivities(
  activities: readonly AgentActivityProjection[],
): AgentActivityProjection[] {
  const seen = new Set<string>();
  const result: AgentActivityProjection[] = [];
  for (const activity of activities) {
    if (!isCountableToolActivity(activity)) continue;
    const toolCallId = text(activity.payload.toolCallId);
    const key = toolCallId || `${activity.turnId}:${activity.id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(activity);
  }
  return result;
}

export function countUniqueToolActivities(
  activities: readonly AgentActivityProjection[],
): number {
  return uniqueToolActivities(activities).length;
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}
