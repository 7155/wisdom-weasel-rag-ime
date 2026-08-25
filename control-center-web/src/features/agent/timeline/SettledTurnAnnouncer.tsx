import { useEffect, useState } from 'react';
import type { AgentProjectionState } from '@/contracts/agent-reducer';
import { useAgentLiveStore } from '../state/live-store';
import { isRoomPublicPostMessage } from './AgentTimeline';

const ACTIVE_TURN_STATUSES = new Set(['queued', 'running', 'waiting']);
const TERMINAL_TURN_STATUSES = new Set(['completed', 'failed', 'aborted']);
const ANNOUNCEMENT_CHARACTERS = 200;

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function latestTurnId(projection: AgentProjectionState | undefined): string {
  return projection?.turnOrder.at(-1) ?? '';
}

function turnStatus(projection: AgentProjectionState | undefined, turnId: string): string {
  return turnId ? projection?.turnsById[turnId]?.status ?? '' : '';
}

/**
 * One bounded sentence describing a turn that just reached a terminal status.
 * The transcript itself remains readable; this only orients a reader who
 * cannot see that the stream stopped.
 */
export function settledTurnAnnouncement(
  projection: AgentProjectionState | undefined,
  turnId: string,
): string {
  const turn = projection?.turnsById[turnId];
  if (!projection || !turn) return '';
  if (turn.status === 'aborted') return '本轮已停止。';
  if (turn.status === 'failed') {
    const failure = (turn.failure ?? '').replace(/\s+/gu, ' ').trim();
    return failure ? `本轮未完成：${failure.slice(0, ANNOUNCEMENT_CHARACTERS)}` : '本轮未完成。';
  }
  const reply = turn.messageIds
    .map((messageId) => projection.messagesById[messageId])
    .filter((message) => (
      message?.role === 'assistant' && !isRoomPublicPostMessage(message)
    ))
    .flatMap((message) => message?.blocks ?? [])
    .map((block) => text(block.data.text ?? block.data.markdown))
    .join(' ')
    .replace(/\s+/gu, ' ')
    .trim();
  if (!reply) return 'Agent 本轮没有文本回复，工作明细在时间线中。';
  return reply.length > ANNOUNCEMENT_CHARACTERS
    ? `Agent 回复已完成，共 ${reply.length} 字，开头是：${reply.slice(0, ANNOUNCEMENT_CHARACTERS)}…`
    : `Agent 回复已完成：${reply}`;
}

/**
 * Settle-only announcement for the transcript.
 *
 * The timeline is a `log` whose body is rewritten on every batched token
 * commit. Left as an implicit live region it made a screen reader read the
 * answer aloud dozens of times as it grew. The log is therefore silent and
 * this element speaks exactly once per settled turn.
 */
export function SettledTurnAnnouncer({ sessionId }: { sessionId: string }) {
  const [announcement, setAnnouncement] = useState('');
  useEffect(() => {
    setAnnouncement('');
    let previousTurnId = latestTurnId(useAgentLiveStore.getState().projections[sessionId]);
    let previousStatus = turnStatus(
      useAgentLiveStore.getState().projections[sessionId],
      previousTurnId,
    );
    return useAgentLiveStore.subscribe((state, previousState) => {
      const projection = state.projections[sessionId];
      if (projection === previousState.projections[sessionId]) return;
      const turnId = latestTurnId(projection);
      const status = turnStatus(projection, turnId);
      const settled = turnId === previousTurnId
        && ACTIVE_TURN_STATUSES.has(previousStatus)
        && TERMINAL_TURN_STATUSES.has(status);
      previousTurnId = turnId;
      previousStatus = status;
      if (!settled) return;
      const next = settledTurnAnnouncement(projection, turnId);
      // A repeated string in a live region is not re-announced; the trailing
      // space makes two identical consecutive replies distinguishable.
      setAnnouncement((current) => (current === next ? `${next} ` : next));
    });
  }, [sessionId]);
  return (
    <p
      aria-atomic="true"
      aria-live="polite"
      className="agent-timeline__announcer"
    >
      {announcement}
    </p>
  );
}
