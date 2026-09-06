import { describe, expect, it } from 'vitest';
import type { AgentRoomIntercomV1 } from '@/contracts/generated/agent-room-intercom.v1';
import { hasRoomSatelliteSnapshot, mergeRoomMessageFlow, roomFlowStatusLabel, roomIntercomMessages, roomSatellites } from './room-message-flow';
import type { RoomFocusPacket } from './room-focus-projection';

function run(id: string, overrides: Record<string, unknown> = {}) {
  return { schemaVersion: 'rag-ime.agent-subagent-run.v1', id, nodeId: `node:${id}`, attemptId: `attempt:${id}`, attemptNumber: 1,
    depth: 1, task: `任务 ${id}`, childSessionId: `child:${id}`, templateId: 'worker', state: 'running',
    usage: { turnCount: 1, toolCount: 1, totalTokens: 20 }, result: {}, error: '', updatedAtMs: 100, ...overrides };
}
function snapshot(runs: ReturnType<typeof run>[]) {
  return { ok: true, tree: { rootSessionId: 's-earth', nodeCount: runs.length, maxDepth: 1, roots: runs.map((value) => ({ run: value, children: [] })) } };
}
function message(id: string, overrides: Partial<AgentRoomIntercomV1> = {}): AgentRoomIntercomV1 {
  return { schemaVersion: 'rag-ime.agent-room-intercom.v1', id, roomId: 'room-1', kind: 'ask', sourceParticipantId: 'earth', targetParticipantId: 'mars',
    sourceSessionId: 's-earth', targetSessionId: 's-mars', sourceGeneration: 1, targetGeneration: 1, clientMessageId: id, replyTo: '',
    workItemId: '', workAction: '', status: 'delivered', content: '请提供核对结果', acceptedTurnId: '', error: '', createdAtMs: 200,
    updatedAtMs: 220, deliveredAtMs: 210, repliedAtMs: null, ...overrides };
}

describe('Room satellite ownership and counts', () => {
  it('counts each node once using its latest attempt and never counts a Room Partner as a satellite', () => {
    const satellites = roomSatellites(snapshot([
      run('old', { nodeId: 'node-worker', state: 'failed', attemptNumber: 1, updatedAtMs: 500 }),
      run('retry', { nodeId: 'node-worker', state: 'running', attemptNumber: 2, updatedAtMs: 200 }),
      run('room-partner', { childSessionId: 's-mars' }),
      run('queued', { state: 'queued' }),
    ]), ['s-earth', 's-mars']);
    expect(satellites.map((item) => [item.id, item.state])).toEqual([['retry', 'running'], ['queued', 'queued']]);
  });

  it('preserves returned and invalid-contract states instead of inflating completed counts', () => {
    const satellites = roomSatellites(snapshot([
      run('returned', { state: 'completed', result: { verificationStatus: 'unverified' } }),
      run('invalid', { state: 'completed', result: { contractStatus: 'invalid' } }),
    ]), ['s-earth']);
    expect(satellites.map((item) => [item.state, item.stateLabel])).toEqual([['returned', '已返回'], ['contract_invalid', '合同无效']]);
  });

  it('requires a valid owned snapshot before zero can be shown', () => {
    expect(hasRoomSatelliteSnapshot(undefined, 's-earth')).toBe(false);
    expect(hasRoomSatelliteSnapshot({ ok: false, items: [] }, 's-earth')).toBe(false);
    expect(hasRoomSatelliteSnapshot(snapshot([]), 's-mars')).toBe(false);
    expect(hasRoomSatelliteSnapshot(snapshot([]), 's-earth')).toBe(true);
    expect(hasRoomSatelliteSnapshot({ ok: true, tree: { rootSessionId: 's-earth', nodeCount: 1, roots: [{ run: {} }] } }, 's-earth')).toBe(false);
    expect(hasRoomSatelliteSnapshot({ ok: true, items: [{}] }, 's-earth')).toBe(false);
  });
});

describe('Room message traffic', () => {
  it('merges lifecycle receipts without duplicating traffic and keeps real reverse replies', () => {
    const receipt: RoomFocusPacket = { id: 'intercom:ask-1', intercomId: 'ask-1', sourceParticipantId: 'earth', targetParticipantIds: ['mars'],
      kind: 'question', summary: 'public receipt', status: 'delivered', sequence: 4, createdAtMs: 205, receiptIds: ['evt-1'], refs: ['doc:brief'] };
    const result = mergeRoomMessageFlow([receipt], [message('ask-1', { status: 'replied', repliedAtMs: 240 }),
      message('reply-1', { kind: 'reply', sourceParticipantId: 'mars', targetParticipantId: 'earth', replyTo: 'ask-1', content: '核对完成', createdAtMs: 240 })]);
    expect(result).toHaveLength(2);
    expect(result[0]).toMatchObject({ sourceParticipantId: 'earth', targetParticipantIds: ['mars'], status: 'replied', receiptIds: ['evt-1'], refs: ['doc:brief'], summary: '请提供核对结果' });
    expect(result[1]).toMatchObject({ kind: 'answer', sourceParticipantId: 'mars', targetParticipantIds: ['earth'], replyToPacketId: 'intercom:ask-1', scope: 'recent-room' });
  });

  it('orders queue timestamps against event timestamps, not unrelated sequence magnitudes', () => {
    const packet: RoomFocusPacket = { id: 'public-1', sourceParticipantId: 'earth', targetParticipantIds: ['mars'], kind: 'dispatch', summary: '分派', status: 'completed', createdAtMs: 300, sequence: 1, refs: [] };
    expect(mergeRoomMessageFlow([packet], [message('ask-1')]).map((item) => item.id)).toEqual(['intercom:ask-1', 'public-1']);
  });

  it('filters foreign rooms and distinguishes delivery failure from other failures', () => {
    expect(roomIntercomMessages({ items: [message('ours'), message('foreign', { roomId: 'room-2' }), {}] }, 'room-1').map((item) => item.id)).toEqual(['ours']);
    expect(roomFlowStatusLabel('failed')).toBe('失败');
    expect(roomFlowStatusLabel('failed', true)).toBe('投递失败');
    expect(roomFlowStatusLabel('delivered', true)).toBe('已送达');
    expect(roomFlowStatusLabel('replied', true)).toBe('已回复');
  });
});
