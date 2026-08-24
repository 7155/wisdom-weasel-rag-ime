import type { RoomActivityProjection } from '@/contracts/room-reducer';

export type RoomActivityFlowKind = 'request' | 'context' | 'dispatch' | 'approval';

const flowRefKeys = ['contextRefs', 'artifactRefs', 'evidenceRefs', 'documentRefs', 'skillRefs'] as const;

export function roomFlowRefs(payload: Record<string, unknown>): string[] {
  const values = flowRefKeys.map((key) => payload[key]);
  return [...new Set(values
    .flatMap((value) => Array.isArray(value) ? value.map(stringValue) : [stringValue(value)])
    .filter(Boolean))].slice(0, 10);
}

export function roomActivityFlowKind(activity: RoomActivityProjection): RoomActivityFlowKind | undefined {
  const signals = [activity.kind, activity.payload.sourceEventType, activity.payload.activityKind]
    .map(signalText)
    .filter(Boolean);
  if (stringValue(activity.payload.approvalId) || signals.some((signal) => signal === 'approval' || signal.startsWith('approval_'))) return 'approval';
  if (roomFlowRefs(activity.payload).length) return 'context';
  if (signals.includes('intercom')) return 'request';
  if (signals.some((signal) => signal === 'dispatch' || signal === 'route' || signal === 'route_decision')) return 'dispatch';
  return undefined;
}

function signalText(value: unknown): string {
  return typeof value === 'string' ? value.trim().toLowerCase() : '';
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
