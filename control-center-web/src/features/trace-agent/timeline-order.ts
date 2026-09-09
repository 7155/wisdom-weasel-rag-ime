export interface TraceTimelineOrderEntry {
  id: string;
  kind: string;
  sequence?: number;
  createdAtMs: number;
  turnId?: string;
  messageIndex?: number;
}

export function recordedTimelineSequence(value: Record<string, unknown>, fallback?: number): number | undefined {
  for (const sequence of [value.timelineSequence, value.sequence]) {
    if (typeof sequence === 'number' && Number.isFinite(sequence)) return sequence;
  }
  return fallback;
}

/** Keep ordinal and timestamp domains separate, and compute one total order. */
export function orderTraceTimelineEntries<T extends TraceTimelineOrderEntry>(entries: readonly T[]): T[] {
  const anchors = entries.filter((entry): entry is T & { sequence: number } => entry.sequence !== undefined && Number.isFinite(entry.sequence))
    .sort((left, right) => (left.sequence - right.sequence) || compareUnsequenced(left, right));
  if (!anchors.length) return [...entries].sort(compareUnsequenced);
  const messages = anchors.filter((entry) => entry.messageIndex !== undefined && ['user', 'assistant'].includes(entry.kind))
    .sort((left, right) => left.messageIndex! - right.messageIndex!);

  const anchored = entries.map((entry) => {
    if (entry.sequence !== undefined) return { entry, anchor: entry.sequence, side: 0 };
    // The messages array is the durable conversation order. A user row may
    // lack an ordinal even when its turn's reasoning/tool receipts have one.
    // Bound the missing row by its recorded message neighbors before locating
    // it among that turn's activities, including later Steer rows in one turn.
    if (entry.messageIndex !== undefined) {
      const before = messages.filter((message) => message.messageIndex! < entry.messageIndex!).at(-1);
      const after = messages.find((message) => message.messageIndex! > entry.messageIndex!);
      const turnAnchors = entry.turnId ? anchors.filter((anchor) => anchor.turnId === entry.turnId
        && (!before || anchor.sequence > before.sequence) && (!after || anchor.sequence < after.sequence)) : [];
      if (turnAnchors.length) {
        const position = entry.kind === 'user' ? { anchor: turnAnchors[0]!.sequence, side: -1 } : positionByTime(entry, turnAnchors);
        return { entry, ...position };
      }
      if (after) return { entry, anchor: after.sequence, side: -1 };
      if (before) return { entry, anchor: before.sequence, side: 1 };
    }
    const turnAnchors = entry.turnId ? anchors.filter((anchor) => anchor.turnId === entry.turnId) : [];
    return { entry, ...positionByTime(entry, turnAnchors.length ? turnAnchors : anchors) };
  });
  return anchored.sort((left, right) => (left.anchor - right.anchor) || (left.side - right.side)
    || compareUnsequenced(left.entry, right.entry)).map(({ entry }) => entry);
}

function positionByTime(entry: TraceTimelineOrderEntry, anchors: (TraceTimelineOrderEntry & { sequence: number })[]) {
  const byTime = [...anchors].sort((left, right) => (left.createdAtMs - right.createdAtMs) || (left.sequence - right.sequence));
  const after = byTime.find((anchor) => anchor.createdAtMs > entry.createdAtMs
    || (anchor.createdAtMs === entry.createdAtMs && entry.kind !== 'assistant'));
  return after ? { anchor: after.sequence, side: -1 } : { anchor: byTime.at(-1)!.sequence, side: 1 };
}

function compareUnsequenced(left: TraceTimelineOrderEntry, right: TraceTimelineOrderEntry): number {
  return (left.createdAtMs - right.createdAtMs)
    || ((left.messageIndex ?? Number.MAX_SAFE_INTEGER) - (right.messageIndex ?? Number.MAX_SAFE_INTEGER))
    || left.id.localeCompare(right.id);
}
