import type {
  AgentActivityProjection,
  AgentMessageProjection,
  AgentTurnStatus,
} from '@/contracts/agent-reducer';

export type AgentTurnSequenceEntry =
  | { kind: 'message'; message: AgentMessageProjection }
  | { kind: 'activity-group'; key: string; activities: AgentActivityProjection[] };

export type AgentTurnWorkItem = {
  entry: AgentTurnSequenceEntry;
  role: 'work' | 'result';
};

export type AgentTurnWorkModel = {
  canCollapse: boolean;
  finalMessageId: string;
  hiddenActivityCount: number;
  hiddenMessageCount: number;
  items: AgentTurnWorkItem[];
  resultCount: number;
  toolCount: number;
};

const responseTailBlockTypes = new Set([
  'artifact',
  'audio',
  'card',
  'checklist',
  'citation',
  'code',
  'diff',
  'file',
  'image',
  'reference',
  'status',
  'table',
  'task_plan',
]);

const settledTurnStatuses = new Set<AgentTurnStatus>(['completed', 'failed', 'aborted']);

/**
 * Partition one canonical turn without changing its order.
 *
 * A PAW turn has an authoritative terminal status but no separate final-text
 * marker. Any settled turn (completed, failed, or aborted) collapses its
 * process work behind one compact summary; the final narrative text plus
 * files, diffs, media, code, and other response-tail results remain visible
 * outside the collapsed region. The turn-level failure alert and recovery
 * actions render outside this model, so collapsing a failed turn never hides
 * its recovery surface. Active turns always fail open.
 */
export function buildAgentTurnWorkModel(
  status: AgentTurnStatus,
  entries: AgentTurnSequenceEntry[],
): AgentTurnWorkModel {
  const settled = settledTurnStatuses.has(status);
  const finalMessageId = settled ? finalNarrativeMessageId(entries) : '';
  const visibleResultIds = new Set<string>();
  if (finalMessageId) visibleResultIds.add(finalMessageId);
  for (const entry of entries) {
    if (entry.kind === 'message' && hasResponseTailResult(entry.message)) {
      visibleResultIds.add(entry.message.id);
    }
  }

  const items = entries.map((entry): AgentTurnWorkItem => ({
    entry,
    role: entry.kind === 'message' && visibleResultIds.has(entry.message.id) ? 'result' : 'work',
  }));
  const hiddenEntries = items.filter((item) => item.role === 'work');
  const hiddenActivities = hiddenEntries.flatMap((item) => (
    item.entry.kind === 'activity-group' ? item.entry.activities : []
  ));
  const hiddenMessageCount = hiddenEntries.filter((item) => item.entry.kind === 'message').length;
  const resultCount = items.filter((item) => item.role === 'result').length;

  return {
    canCollapse: settled && hiddenEntries.length > 0,
    finalMessageId,
    hiddenActivityCount: hiddenActivities.length,
    hiddenMessageCount,
    items,
    resultCount,
    toolCount: hiddenActivities.filter(isToolActivity).length,
  };
}

function finalNarrativeMessageId(entries: AgentTurnSequenceEntry[]): string {
  for (let index = entries.length - 1; index >= 0; index -= 1) {
    const entry = entries[index];
    if (entry?.kind === 'message' && hasNarrativeText(entry.message)) return entry.message.id;
  }
  return '';
}

function hasNarrativeText(message: AgentMessageProjection): boolean {
  return message.blocks.some((block) => (
    block.type === 'text'
    && Boolean(stringValue(block.data.text ?? block.data.markdown).trim())
  ));
}

function hasResponseTailResult(message: AgentMessageProjection): boolean {
  return message.blocks.some((block) => responseTailBlockTypes.has(block.type));
}

function isToolActivity(activity: AgentActivityProjection): boolean {
  return activity.kind.startsWith('tool_') || Boolean(stringValue(activity.payload.toolCallId));
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
