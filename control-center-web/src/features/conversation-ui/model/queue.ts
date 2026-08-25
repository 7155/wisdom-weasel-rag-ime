/* Vendored clean-room front-end queue model. See ../ATTRIBUTION.md.
 *
 * The queue is a composer-side holding area: nothing here has reached Pi, so
 * every row stays reorderable, editable and fully reversible. The cap exists
 * so a held backlog can never grow past what a reader can still review. */

import type { AttachmentRef, QueuedDraft } from './types';

export const FRONTEND_QUEUE_CAP = 8;

export interface QueueInput {
  id: string;
  text: string;
  attachments?: AttachmentRef[];
  conversationId: string;
  busy: boolean;
  existingDepth: number;
  now?: number;
}

export function createQueuedDraft(input: QueueInput): QueuedDraft {
  return {
    id: input.id,
    text: input.text,
    attachments: input.attachments ?? [],
    queuedAt: input.now ?? Date.now(),
    forConversationId: input.conversationId,
    queuedWhileBusy: input.busy,
    queuedBehindPending: input.existingDepth > 0,
  };
}

/** Refusing at the cap keeps the text in the composer; it is never dropped. */
export function enqueueQueuedDraft(
  queue: readonly QueuedDraft[],
  input: QueueInput,
  cap = FRONTEND_QUEUE_CAP,
): { accepted: boolean; queue: QueuedDraft[] } {
  if (queue.length >= cap) return { accepted: false, queue: [...queue] };
  return { accepted: true, queue: [...queue, createQueuedDraft(input)] };
}

export function removeQueuedDraft(queue: readonly QueuedDraft[], id: string): QueuedDraft[] {
  return queue.filter((item) => item.id !== id);
}

export function editQueuedDraft(
  queue: readonly QueuedDraft[],
  id: string,
  text: string,
): QueuedDraft[] {
  const value = text.trim();
  if (!value) return removeQueuedDraft(queue, id);
  return queue.map((item) => item.id === id ? { ...item, text: value } : item);
}

export function reorderQueuedDrafts(
  queue: readonly QueuedDraft[],
  activeId: string,
  overId: string,
): QueuedDraft[] {
  if (activeId === overId) return [...queue];
  const from = queue.findIndex((item) => item.id === activeId);
  const to = queue.findIndex((item) => item.id === overId);
  if (from < 0 || to < 0) return [...queue];
  const next = [...queue];
  const [item] = next.splice(from, 1);
  if (!item) return [...queue];
  next.splice(to, 0, item);
  return next;
}

export function mergeQueueBackToDraft(
  queue: readonly QueuedDraft[],
  currentText: string,
): string {
  const parts = [currentText.trim(), ...queue.map((item) => item.text.trim())].filter(Boolean);
  return parts.join('\n\n');
}

export function mergeQueueAttachments(
  queue: readonly QueuedDraft[],
  current: readonly AttachmentRef[],
): AttachmentRef[] {
  const seen = new Set<string>();
  const merged: AttachmentRef[] = [];
  for (const attachment of [...current, ...queue.flatMap((item) => item.attachments)]) {
    if (seen.has(attachment.id)) continue;
    seen.add(attachment.id);
    merged.push(attachment);
  }
  return merged;
}
