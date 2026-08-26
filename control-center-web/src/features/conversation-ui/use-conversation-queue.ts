import { useCallback, useEffect, useRef, useState } from 'react';
import {
  editQueuedDraft,
  enqueueQueuedDraft,
  FRONTEND_QUEUE_CAP,
  mergeQueueBackToDraft,
  removeQueuedDraft,
  reorderQueuedDrafts,
} from './model/queue';
import type { QueuedDraft } from './model/types';

export interface ConversationQueueController {
  queue: readonly QueuedDraft[];
  capReached: boolean;
  /** Hold a draft in front of the Runtime send path. `false` means the cap
   *  refused it and the text must stay in the composer. */
  enqueue(text: string): boolean;
  remove(id: string): void;
  edit(id: string, text: string): void;
  reorder(activeId: string, overId: string): void;
  clear(): void;
  sendNow(id: string): void;
  /** Stop pulls unconsumed drafts back into the composer instead of dropping
   *  them — the queue only ever held them, it never dispatched them. */
  restoreToDraft(currentText: string): string;
}

/**
 * Front-end follow-up queue with the clean-room package's contract: cap 8,
 * one drain per settled turn, reorder/edit/remove/clear, and restore-on-stop.
 *
 * Nothing here reaches Pi until `send` is called for the head draft, so every
 * queued row stays fully reversible and no Runtime ordering is invented.
 */
export function useConversationQueue({
  busy,
  conversationId,
  send,
  cap = FRONTEND_QUEUE_CAP,
}: {
  busy: boolean;
  conversationId: string;
  send(text: string): void;
  cap?: number;
}): ConversationQueueController {
  const [queue, setQueue] = useState<readonly QueuedDraft[]>([]);
  const [capReached, setCapReached] = useState(false);
  const sendRef = useRef(send);
  sendRef.current = send;

  useEffect(() => {
    setQueue([]);
    setCapReached(false);
  }, [conversationId]);

  // Drain exactly one held draft once the current turn settles. Keeping this
  // in an effect makes the dependency on committed busy state explicit and
  // avoids racing the optimistic append the send path performs.
  useEffect(() => {
    if (busy || queue.length === 0) return;
    const [next, ...rest] = queue;
    if (!next) return;
    setQueue(rest);
    setCapReached(false);
    sendRef.current(next.text);
  }, [busy, queue]);

  const enqueue = useCallback((text: string) => {
    const value = text.trim();
    if (!value) return false;
    let accepted = false;
    setQueue((current) => {
      const result = enqueueQueuedDraft(current, {
        id: `queued-${crypto.randomUUID()}`,
        text: value,
        conversationId,
        busy: true,
        existingDepth: current.length,
      }, cap);
      accepted = result.accepted;
      return result.queue;
    });
    setCapReached(!accepted);
    return accepted;
  }, [cap, conversationId]);

  const remove = useCallback((id: string) => {
    setQueue((current) => removeQueuedDraft(current, id));
    setCapReached(false);
  }, []);

  const edit = useCallback((id: string, text: string) => {
    setQueue((current) => editQueuedDraft(current, id, text));
  }, []);

  const reorder = useCallback((activeId: string, overId: string) => {
    setQueue((current) => reorderQueuedDrafts(current, activeId, overId));
  }, []);

  const clear = useCallback(() => {
    setQueue([]);
    setCapReached(false);
  }, []);

  const sendNow = useCallback((id: string) => {
    const item = queue.find((candidate) => candidate.id === id);
    if (!item) return;
    // React may invoke state updater functions twice in StrictMode. Dispatching
    // from inside the updater therefore sent one human action to Runtime twice.
    // Resolve the immutable queued draft first, then keep the updater pure.
    setQueue((current) => removeQueuedDraft(current, id));
    setCapReached(false);
    sendRef.current(item.text);
  }, [queue]);

  const restoreToDraft = useCallback((currentText: string) => {
    const restored = mergeQueueBackToDraft(queue, currentText);
    setQueue([]);
    setCapReached(false);
    return restored;
  }, [queue]);

  return { queue, capReached, enqueue, remove, edit, reorder, clear, sendNow, restoreToDraft };
}
