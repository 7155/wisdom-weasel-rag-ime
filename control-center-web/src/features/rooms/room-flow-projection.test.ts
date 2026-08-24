import { describe, expect, it } from 'vitest';
import type { RoomActivityProjection } from '@/contracts/room-reducer';
import { roomActivityFlowKind, roomFlowRefs } from './room-flow-projection';

function activity(overrides: Partial<RoomActivityProjection> & { payload?: Record<string, unknown> }): RoomActivityProjection {
  return {
    id: 'activity-1',
    turnId: 'turn-1',
    participantId: 'partner-a',
    sourceSessionId: 'session-1',
    kind: 'participant_activity',
    status: 'completed',
    summary: '',
    createdAtMs: 1,
    ...overrides,
    payload: overrides.payload ?? {},
  };
}

describe('roomActivityFlowKind', () => {
  it('classifies approval requests as approval paths even when refs are attached', () => {
    expect(roomActivityFlowKind(activity({
      payload: { approvalId: 'approval-9', contextRefs: ['doc:plan'] },
    }))).toBe('approval');
    expect(roomActivityFlowKind(activity({
      payload: { sourceEventType: 'approval_requested' },
    }))).toBe('approval');
  });

  it('keeps real dispatch and route decisions as dispatch paths', () => {
    expect(roomActivityFlowKind(activity({
      payload: { sourceEventType: 'dispatch', targetParticipantId: 'partner-b' },
    }))).toBe('dispatch');
    expect(roomActivityFlowKind(activity({
      payload: { activityKind: 'route_decision', contextRefs: ['doc:brief'] },
    }))).toBe('dispatch');
  });

  it('classifies intercom traffic as request paths', () => {
    expect(roomActivityFlowKind(activity({
      payload: { sourceEventType: 'intercom', targetParticipantId: 'partner-b' },
    }))).toBe('request');
  });

  it('treats refs as a context handoff only when explicitly addressed to a target', () => {
    expect(roomActivityFlowKind(activity({
      payload: { targetParticipantId: 'partner-b', contextRefs: ['doc:spec'] },
    }))).toBe('context');
  });

  it('never draws a path for a partner tool or progress activity that merely records refs', () => {
    expect(roomActivityFlowKind(activity({
      payload: { sourceEventType: 'tool_finished', evidenceRefs: ['receipt:build'] },
    }))).toBeUndefined();
    expect(roomActivityFlowKind(activity({
      payload: { sourceEventType: 'current_progress', contextRefs: ['doc:notes'], artifactRefs: ['artifact:report'] },
    }))).toBeUndefined();
  });

  it('draws nothing for plain activities without transfer signals', () => {
    expect(roomActivityFlowKind(activity({ payload: {} }))).toBeUndefined();
    expect(roomActivityFlowKind(activity({
      payload: { targetParticipantId: 'partner-b' },
    }))).toBeUndefined();
  });
});

describe('roomFlowRefs', () => {
  it('merges, deduplicates, and bounds refs across payload keys', () => {
    const refs = roomFlowRefs({
      contextRefs: ['doc:a', 'doc:a', 'doc:b'],
      artifactRefs: 'artifact:c',
      evidenceRefs: ['doc:b', 42, ''],
      documentRefs: Array.from({ length: 12 }, (_, index) => `doc:extra-${index}`),
    });
    expect(refs.slice(0, 3)).toEqual(['doc:a', 'doc:b', 'artifact:c']);
    expect(refs).toHaveLength(10);
    expect(new Set(refs).size).toBe(refs.length);
  });
});
