import { useCallback, useMemo, useState, type ReactNode } from 'react';
import type { RoomActivityProjection, RoomProjectionState } from '@/contracts/room-reducer';
import { publicAgentErrorText } from '@/features/agent/public-error';
import { PublicToolOutput } from '@/features/agent/timeline/ActivitySummary';
import {
  publicToolResultView,
  type PublicToolResultView,
} from '@/features/agent/timeline/public-tool-result';
import { ConversationSurface } from '@/features/conversation-ui';
import {
  conversationClock,
  type ConversationSurfaceController,
} from '@/features/conversation-ui';
import {
  roomApprovalDecision,
  roomPhase,
  roomTranscript,
  roomTranscriptRetrySource,
} from '@/features/conversation-ui/adapters/room-transcript';
import type { AssistantBlock, AssistantMessage } from '@/features/conversation-ui';
import { roomCollaborationRoleLabel } from '@/features/rooms/room-copy';
import type { RoomSummary } from '@/features/rooms/room-types';
import { runtimeToolWindowRequest } from '../runtime/runtime-tool-window';
import { roomFocusCelestialName } from './room-focus-projection';
import { roomToolEvidence } from './room-gravity-projection';

/**
 * The Room's public conversation, on the shared clean-room surface.
 *
 * The Room keeps every Runtime contract it owned before — one card per real
 * loop, pending approvals decided inline, background processes reachable, the
 * structured tool reader, retry only for the newest unsuperseded failure — but
 * the reading craft (pinned scroll, variable-height virtualization, turn
 * cards, tool receipts) is now the same code the partner satellite and any
 * other PAWOS conversation mount.
 */
export function PawRoomConversation({
  empty,
  lead,
  onApprovalDecision,
  onOpenProcessActivity,
  onRetryTurn,
  participantId,
  projection,
  retryingTurn,
  room,
}: {
  onApprovalDecision: (approvalId: string, decision: 'approved' | 'rejected', payloadSha256: string) => Promise<void>;
  onOpenProcessActivity?: (activity: RoomActivityProjection) => void;
  /** Only a mount that owns the Room composer can resend a failed request; a
   *  satellite reads the same history without offering retry. */
  onRetryTurn?: (message: string, rootId: string) => void;
  /** Restrict the transcript to one partner's public lane (satellite view). */
  participantId?: string;
  projection: RoomProjectionState;
  retryingTurn?: boolean;
  room: RoomSummary;
  lead?: ReactNode;
  empty?: ReactNode;
}) {
  const actorName = useCallback((candidateId: string | null | undefined) => {
    const participant = candidateId
      ? room.participants.find((item) => item.id === candidateId)
      : undefined;
    return participant ? roomFocusCelestialName(participant.ordinal) : 'Sol';
  }, [room.participants]);
  const actorRole = useCallback((candidateId: string | null | undefined) => {
    const participant = candidateId
      ? room.participants.find((item) => item.id === candidateId)
      : undefined;
    return participant ? roomCollaborationRoleLabel(participant.collaborationRole) : '';
  }, [room.participants]);

  /* A dispatch names the real task it carries, not only a WorkItem id. */
  const workItemObjective = useCallback((workItemId: string) => (
    room.workItems?.find((item) => item.id === workItemId)?.objective ?? ''
  ), [room.workItems]);

  const transcript = useMemo(() => roomTranscript(projection, {
    actorName,
    actorRole,
    workItemObjective,
    ...(participantId ? { participantId } : {}),
  }), [actorName, actorRole, participantId, projection, workItemObjective]);

  const renderBlockDetail = useCallback((block: AssistantBlock) => {
    const activity = transcript.activityByBlockId[block.id];
    if (!activity || block.kind !== 'tool') return undefined;
    const facts = roomToolEvidence(activity.payload)?.facts ?? [];
    const view = roomToolResultView(activity);
    if (!facts.length && !view) return undefined;
    return <>
      {facts.length ? (
        <dl className="paw-room-tool-facts">
          {facts.map((fact) => <div key={`${fact.label}:${fact.value}`}><dt>{fact.label}</dt><dd>{fact.value}</dd></div>)}
        </dl>
      ) : null}
      {view ? <PublicToolOutput view={view} /> : null}
    </>;
  }, [transcript.activityByBlockId]);

  const renderBlockAction = useCallback((block: AssistantBlock) => {
    const activity = transcript.activityByBlockId[block.id];
    if (!activity) return undefined;
    const approval = roomApprovalDecision(activity);
    const processWindow = onOpenProcessActivity ? roomProcessWindowRequest(activity, room.id) : null;
    if (!approval && !processWindow) return undefined;
    return <>
      {approval ? <RoomApprovalAction decision={onApprovalDecision} {...approval} /> : null}
      {processWindow ? (
        <button onClick={() => onOpenProcessActivity?.(activity)} type="button">查看后台 Bash</button>
      ) : null}
    </>;
  }, [onApprovalDecision, onOpenProcessActivity, room.id, transcript.activityByBlockId]);

  const controller = useMemo<ConversationSurfaceController>(() => ({
    conversationId: participantId ? `${room.id}:${participantId}` : room.id,
    messages: transcript.messages,
    phase: transcript.phase,
    capabilities: {
      /* A Room turn is retried by resending its request, so retry is the one
       * conversation-level action Runtime backs here. Fork, rewind and
       * message edit belong to a Session, not to shared Room history. */
      retry: Boolean(onRetryTurn),
      edit: false,
      fork: false,
      rewind: false,
      interrupt: false,
      copy: true,
    },
    canRetry: (message: AssistantMessage) => Boolean(
      onRetryTurn && message.error && message.turnId && roomTranscriptRetrySource(projection, message.turnId),
    ),
    retry: (message: AssistantMessage) => {
      const source = message.turnId ? roomTranscriptRetrySource(projection, message.turnId) : undefined;
      if (source) onRetryTurn?.(source.text, source.rootId);
    },
    retryPending: Boolean(retryingTurn),
    renderBlockDetail,
    renderBlockAction,
    formatTimestamp: conversationClock,
  }), [
    onRetryTurn,
    participantId,
    projection,
    renderBlockAction,
    renderBlockDetail,
    retryingTurn,
    room.id,
    transcript.messages,
    transcript.phase,
  ]);

  return <ConversationSurface
    controller={controller}
    density={participantId ? 'compact' : 'comfortable'}
    label={participantId ? '伙伴公开对话' : 'Room 公开对话'}
    {...(lead ? { lead } : {})}
    {...(empty ? { empty } : {})}
  />;
}

function RoomApprovalAction({ approvalId, decision, payloadSha256 }: {
  approvalId: string;
  payloadSha256: string;
  decision: (approvalId: string, choice: 'approved' | 'rejected', payloadSha256: string) => Promise<void>;
}) {
  const [submitting, setSubmitting] = useState<'' | 'approved' | 'rejected'>('');
  const [error, setError] = useState('');
  const decide = (choice: 'approved' | 'rejected') => {
    if (submitting) return;
    setError('');
    setSubmitting(choice);
    void decision(approvalId, choice, payloadSha256)
      .catch((reason: unknown) => setError(publicAgentErrorText(reason)))
      .finally(() => setSubmitting(''));
  };
  return <>
    <button disabled={Boolean(submitting)} onClick={() => decide('approved')} type="button">
      {submitting === 'approved' ? '正在批准' : '批准并继续'}
    </button>
    <button disabled={Boolean(submitting)} onClick={() => decide('rejected')} type="button">
      {submitting === 'rejected' ? '正在拒绝' : '拒绝'}
    </button>
    {error ? <small role="alert">{error}</small> : null}
  </>;
}

/** Room tool activities project through the exact Session tool-result view
 *  (`arguments` → `args`), so a diff/edit/write/read receipt expands into the
 *  same structured detail as the Session timeline (PF-CM-004/007). */
function roomToolResultView(activity: RoomActivityProjection): PublicToolResultView | null {
  const payload = activity.payload;
  const args = payload.args ?? payload.arguments;
  const view = publicToolResultView({
    kind: typeof payload.sourceEventType === 'string' ? payload.sourceEventType : activity.kind,
    status: activity.status,
    payload: {
      ...payload,
      ...(typeof args === 'object' && args !== null && !Array.isArray(args) ? { args } : {}),
    },
  });
  return view.output ? view : null;
}

export function roomProcessWindowRequest(activity: RoomActivityProjection, roomId: string) {
  const request = runtimeToolWindowRequest({
    eventType: 'participant_activity',
    roomId,
    ...(activity.participantId ? { participantId: activity.participantId } : {}),
    sourceSessionId: activity.sourceSessionId,
    payload: {
      sourceEventType: typeof activity.payload.sourceEventType === 'string'
        ? activity.payload.sourceEventType
        : activity.kind,
      data: activity.payload,
    },
  });
  return request?.target.kind === 'process-terminal'
    && Boolean(request.target.runId || request.target.terminalId)
    ? request
    : null;
}
