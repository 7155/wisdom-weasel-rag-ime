/**
 * Who owns the transcript's vertical position, and what the reader missed.
 *
 * The timeline previously carried this as one mutable boolean ref. That was
 * enough to stop live output from yanking a reader back to the bottom, but it
 * could not answer the two questions a detached reader actually has — how much
 * arrived while they were away, and whether their own next message will be
 * visible. Both answers live here as a pure reduction so they can be tested
 * without a scroller.
 */

export type TranscriptFollowMode = 'following' | 'detached';

export type TranscriptDetachReason = 'user-scroll' | 'jump-to-message' | 'selection';

export interface TranscriptFollowState {
  readonly mode: TranscriptFollowMode;
  /** Content items appended since the reader left the end. */
  readonly unseenUpdates: number;
  readonly detachedReason: TranscriptDetachReason | null;
}

export type TranscriptFollowEvent =
  | { type: 'content-appended'; count?: number }
  | { type: 'user-detached'; reason?: TranscriptDetachReason }
  | { type: 'reached-end' }
  | { type: 'jump-to-latest' }
  | { type: 'prompt-submitted' }
  | { type: 'conversation-switched' };

/**
 * True when the live selection intersects the transcript root.
 *
 * Submitting a prompt normally claims the end of the transcript, but a reader
 * who is mid-selection is quoting or copying an earlier turn, and jumping
 * collapses that highlight under them. The transcript then stays where it is
 * and the unseen count reports the new turn instead.
 */
export function transcriptHasLiveSelection(root: ParentNode | null | undefined): boolean {
  if (!root || typeof document === 'undefined') return false;
  const selection = document.getSelection();
  if (!selection || selection.isCollapsed || selection.rangeCount < 1) return false;
  const range = selection.getRangeAt(0);
  const common = range.commonAncestorContainer;
  const node = common.nodeType === Node.ELEMENT_NODE ? common as Element : common.parentElement;
  return Boolean(node && root.contains(node));
}

export const FOLLOWING_TRANSCRIPT: TranscriptFollowState = Object.freeze({
  mode: 'following',
  unseenUpdates: 0,
  detachedReason: null,
});

/**
 * Returns the same object when nothing changed. The timeline dispatches this
 * on every store commit, so identity is the signal that no host re-render is
 * owed.
 */
export function reduceTranscriptFollow(
  state: TranscriptFollowState,
  event: TranscriptFollowEvent,
): TranscriptFollowState {
  switch (event.type) {
    case 'content-appended': {
      if (state.mode === 'following') return state;
      const appended = Math.max(1, Math.floor(event.count ?? 1));
      return { ...state, unseenUpdates: state.unseenUpdates + appended };
    }
    case 'user-detached': {
      const reason = event.reason ?? 'user-scroll';
      if (state.mode === 'detached' && state.detachedReason === reason) return state;
      // Leaving the end does not retroactively make already-read content
      // unseen, so an existing count carries over rather than resetting.
      return {
        mode: 'detached',
        unseenUpdates: state.mode === 'detached' ? state.unseenUpdates : 0,
        detachedReason: reason,
      };
    }
    case 'reached-end':
    case 'jump-to-latest':
    case 'prompt-submitted':
    case 'conversation-switched':
      return state.mode === 'following' && state.unseenUpdates === 0
        ? state
        : FOLLOWING_TRANSCRIPT;
  }
}

/** Bounded so a long unattended stream cannot widen the jump control. */
export function unseenUpdatesLabel(count: number): string {
  if (count <= 0) return '';
  return count > 99 ? '99+' : String(count);
}
