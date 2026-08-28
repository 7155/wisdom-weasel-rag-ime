import type { RoomActivityProjection } from '@/contracts/room-reducer';

export type RoomActivityFlowKind = 'request' | 'intercom' | 'context' | 'dispatch' | 'approval' | 'review';
export type RoomActivityHandoffKind = 'handoff';
export type RoomWorkReviewPhase = 'submitted' | 'completed' | 'returned';

/**
 * The review relation emitted by the Room WorkItem producer.  This is kept as
 * a small pure projection helper so every surface uses the same provenance
 * rules: the event actor is the source, the WorkItem fields choose the target,
 * and refs come from the explicit nested work record.
 */
export interface RoomWorkReviewFlow {
  phase: RoomWorkReviewPhase;
  sourceParticipantId: string;
  targetParticipantId: string;
  status: 'waiting' | 'completed';
  workItemId: string;
  refs: string[];
}

const flowRefKeys = ['contextRefs', 'artifactRefs', 'evidenceRefs', 'documentRefs', 'skillRefs'] as const;
const workHandoffPhases = new Set(['assigned', 'accepted', 'offered', 'reassigned', 'transferred']);

export function roomFlowRefs(payload: Record<string, unknown>): string[] {
  const workValue = payload.work;
  const work = recordValue(workValue);
  const values = [
    ...flowRefKeys.map((key) => payload[key]),
    work.artifactRefs,
    work.evidenceRefs,
  ];
  return [...new Set(values
    .flatMap((value) => Array.isArray(value) ? value.map(stringValue) : [stringValue(value)])
    .filter(Boolean))].slice(0, 10);
}

/**
 * Map the production `participant_activity` WorkItem lifecycle into one
 * review packet.  The producer deliberately does not emit review prose or a
 * synthetic `sourceEventType`; phase, actor, and bounded WorkItem fields are
 * the only accepted source of truth.
 */
export function roomWorkReviewFlow(
  activity: RoomActivityProjection,
): RoomWorkReviewFlow | undefined {
  const payload = activity.payload;
  if (signalText(payload.activityKind) !== 'work') return undefined;
  const phase = signalText(payload.phase);
  if (!['submitted', 'completed', 'returned'].includes(phase)) return undefined;

  const sourceParticipantId = stringValue(activity.participantId).trim();
  const workValue = payload.work;
  const work = recordValue(workValue);
  const topLevelWorkItemId = stringValue(payload.workItemId).trim();
  const nestedWorkItemId = stringValue(work.id).trim();
  if (
    !sourceParticipantId
    || !isRecord(workValue)
    || (topLevelWorkItemId && nestedWorkItemId && topLevelWorkItemId !== nestedWorkItemId)
  ) return undefined;

  const workItemId = topLevelWorkItemId || nestedWorkItemId;
  if (!workItemId) return undefined;

  const parentWorkId = stringValue(work.parentWorkId).trim();
  const targetParticipantId = phase === 'submitted'
    ? parentWorkId
      ? stringValue(work.createdByParticipantId).trim()
      : stringValue(work.accountableParticipantId).trim()
    : stringValue(work.currentOwnerParticipantId).trim();
  if (!targetParticipantId) return undefined;

  return {
    phase: phase as RoomWorkReviewPhase,
    sourceParticipantId,
    targetParticipantId,
    status: phase === 'completed' ? 'completed' : 'waiting',
    workItemId,
    refs: roomFlowRefs(payload),
  };
}

/** UR-054/UR-057: a cross-window path may only come from an authoritative
 *  transfer — an approval, a dispatch/route decision, an intercom request, or
 *  refs the event explicitly hands to a named target participant. Refs recorded
 *  on a partner's own tool or progress activity stay in that lane's ledger;
 *  they never fabricate a decorative root→partner packet. */
export function roomActivityFlowKind(activity: RoomActivityProjection): RoomActivityFlowKind | undefined {
  const kind = roomActivityClassification(activity);
  return kind === 'handoff' ? undefined : kind;
}

/** The same authoritative classifier used by the flow ledger, kept separate
 * from ordinary flow packets so a handoff can feed the directed responsibility
 * projection without becoming a second decorative path. */
export function roomActivityHandoffKind(activity: RoomActivityProjection): RoomActivityHandoffKind | undefined {
  return roomActivityClassification(activity) === 'handoff' ? 'handoff' : undefined;
}

function roomActivityClassification(activity: RoomActivityProjection): RoomActivityFlowKind | RoomActivityHandoffKind | undefined {
  if (roomWorkReviewFlow(activity)) return 'review';
  const signals = [activity.kind, activity.payload.sourceEventType, activity.payload.activityKind]
    .map(signalText)
    .filter(Boolean);
  const requestKind = signalText(activity.payload.requestKind);
  if (
    ['plan_review', 'memory_review', 'review_request'].includes(requestKind)
    || signals.some((signal) => [
      'review_request',
      'review_requested',
      'review_started',
      'review_conclusion',
      'review_concluded',
      'review_completed',
      'review_result',
    ].includes(signal))
  ) return 'review';
  if (stringValue(activity.payload.approvalId) || signals.some((signal) => signal === 'approval' || signal.startsWith('approval_'))) return 'approval';
  const activityKind = signalText(activity.payload.activityKind);
  const phase = signalText(activity.payload.phase);
  if (signals.some(isHandoffSignal) || (activityKind === 'work' && workHandoffPhases.has(phase))) return 'handoff';
  if (signals.some((signal) => signal === 'dispatch' || signal === 'route' || signal === 'route_decision')) return 'dispatch';
  if (signals.includes('intercom')) return 'intercom';
  const addressed = Boolean(stringValue(activity.payload.targetParticipantId));
  if (addressed && roomFlowRefs(activity.payload).length) return 'context';
  return undefined;
}

function isHandoffSignal(signal: string): boolean {
  return /(?:^|_)(?:handoff|handoffed|reassign|reassigned|reassignment|transfer|transferred|offer|offered)(?:_|$)/.test(signal)
    || signal === 'ownership_transferred';
}

function signalText(value: unknown): string {
  return typeof value === 'string' ? value.trim().toLowerCase() : '';
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function recordValue(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}
