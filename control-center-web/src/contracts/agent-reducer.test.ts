import { describe, expect, it } from 'vitest';

import {
  abortAgentTurn,
  appendOptimisticAgentMessage,
  applyAgentSnapshot,
  createAgentProjection,
  failOptimisticAgentMessage,
  reduceAgentEvent,
} from './agent-reducer';
import { parseAgentEvent } from './validators';
import { agentEventFixture as agentEvent } from '@/test/fixtures/events';

describe('AgentEventReducer', () => {
  it('applies ordered deltas and ignores replayed duplicates', () => {
    const initial = createAgentProjection('session-1');
    const first = reduceAgentEvent(initial, agentEvent(1, 'text_delta', { delta: '你' }));
    const second = reduceAgentEvent(first.state, agentEvent(2, 'text_delta', { delta: '好' }));
    const replay = reduceAgentEvent(second.state, agentEvent(2, 'text_delta', { delta: '好' }));

    expect(replay.disposition).toBe('ignored-duplicate');
    expect(replay.state).toBe(second.state);
    expect(textOf(second.state.messagesById['turn-1:assistant'])).toBe('你好');
  });

  it('keeps completed turns referentially stable while the active tail streams', () => {
    const hydrated = applyAgentSnapshot(createAgentProjection('session-1'), {
      messages: [
        serverMessage('stable-user', 'user', 'stable-turn', '之前的问题'),
        serverMessage('stable-assistant', 'assistant', 'stable-turn', '之前的回答'),
        serverMessage('active-user', 'user', 'turn-1', '继续'),
      ],
      liveEvents: [],
      lastSequence: 0,
      resumeToken: '',
      status: 'responding',
    });
    const stableTurn = hydrated.turnsById['stable-turn'];
    const activeTurn = hydrated.turnsById['turn-1'];
    const stableMessage = hydrated.messagesById['stable-assistant'];

    const streamed = reduceAgentEvent(
      hydrated,
      agentEvent(1, 'text_delta', { delta: '新的流式内容' }),
    ).state;

    expect(streamed.turnsById['stable-turn']).toBe(stableTurn);
    expect(streamed.messagesById['stable-assistant']).toBe(stableMessage);
    expect(streamed.turnsById['turn-1']).not.toBe(activeTurn);
    expect(hydrated.turnsById['turn-1'].messageIds).not.toContain('turn-1:assistant');
    expect(streamed.turnsById['turn-1'].messageIds).toContain('turn-1:assistant');
  });

  it('preserves assistant segments around a tool call instead of replacing earlier text', () => {
    let state = createAgentProjection('session-1');
    const events = [
      agentEvent(1, 'text_delta', { delta: '我先检查运行状态。', replaceBlock: true }),
      agentEvent(2, 'message_completed', {
        message: serverMessage('turn-1:assistant', 'assistant', 'turn-1', '我先检查运行状态。'),
      }),
      agentEvent(3, 'tool_started', {
        toolCallId: 'tool-interleaved',
        toolName: 'ime_overview',
      }),
      agentEvent(4, 'tool_finished', {
        toolCallId: 'tool-interleaved',
        toolName: 'ime_overview',
        result: { details: { result: { summary: '运行状态正常' } } },
      }),
      agentEvent(5, 'text_delta', { delta: '检查完成，一切正常。', replaceBlock: true }),
      agentEvent(6, 'message_completed', {
        message: serverMessage('turn-1:assistant', 'assistant', 'turn-1', '检查完成，一切正常。'),
      }),
      agentEvent(7, 'turn_completed', { status: 'completed' }),
    ];
    for (const event of events) state = reduceAgentEvent(state, event).state;

    expect(state.turnsById['turn-1'].messageIds).toEqual([
      'turn-1:assistant',
      'turn-1:assistant:segment:5',
    ]);
    expect(textOf(state.messagesById['turn-1:assistant'])).toBe('我先检查运行状态。');
    expect(textOf(state.messagesById['turn-1:assistant:segment:5'])).toBe('检查完成，一切正常。');
    expect(state.messagesById['turn-1:assistant']).toMatchObject({ createdAtMs: 10, timelineSequence: 1 });
    expect(state.messagesById['turn-1:assistant:segment:5']).toMatchObject({ createdAtMs: 50, timelineSequence: 5 });
    expect(state.activitiesById['tool-interleaved']).toMatchObject({
      createdAtMs: 30,
      timelineSequence: 3,
      status: 'completed',
    });
  });

  it('stops projection on a sequence gap until a snapshot is applied', () => {
    const first = reduceAgentEvent(
      createAgentProjection('session-1'),
      agentEvent(4, 'status_changed', { status: 'busy' }),
    );
    const gap = reduceAgentEvent(first.state, agentEvent(6, 'text_delta', { delta: 'lost' }));
    const pending = reduceAgentEvent(gap.state, agentEvent(7, 'text_delta', { delta: 'late' }));

    expect(gap.disposition).toBe('snapshot-required');
    expect(gap.state.gap).toMatchObject({ expectedSequence: 5, receivedSequence: 6 });
    expect(pending.disposition).toBe('ignored-snapshot-pending');

    const recovered = applyAgentSnapshot(gap.state, {
      messages: [serverMessage('server-user', 'user', 'turn-snapshot', '恢复后的问题')],
      liveEvents: [],
      lastSequence: 8,
      resumeToken: 'session-1:8',
    });
    expect(recovered.needsSnapshot).toBe(false);
    expect(recovered.lastSequence).toBe(8);
    expect(recovered.messageOrder).toEqual(['server-user']);
  });

  it('projects queued steering and follow-up messages without replacing the active turn', () => {
    const active = applyAgentSnapshot(createAgentProjection('session-1'), {
      messages: [serverMessage('active-user', 'user', 'turn-active', '继续检查')],
      liveEvents: [],
      lastSequence: 1,
      resumeToken: 'session-1:1',
      status: 'working',
      messageQueue: { steering: [], followUp: [] },
    });
    const optimistic = appendOptimisticAgentMessage(active, {
      clientMessageId: 'steer-1',
      text: '先不要修改配置',
      nowMs: 20,
      turnId: 'turn-active',
      delivery: 'steer',
    });
    const queued = reduceAgentEvent(
      optimistic,
      agentEvent(2, 'message_queue_updated', {
        steering: ['先不要修改配置'],
        followUp: ['完成后总结'],
      }),
    ).state;

    expect(optimistic.turnOrder).toEqual(['turn-active']);
    expect(optimistic.turnsById['turn-active']?.status).toBe('running');
    expect(optimistic.messagesById['local:steer-1']?.blocks[0]?.data.delivery).toBe('steer');
    expect(queued.messageQueue).toEqual({
      steering: ['先不要修改配置'],
      followUp: ['完成后总结'],
    });

    const restored = applyAgentSnapshot(queued, {
      messages: [],
      liveEvents: [],
      lastSequence: 3,
      resumeToken: 'session-1:3',
      messageQueue: { steering: [], followUp: ['下一项任务'] },
    });
    expect(restored.messageQueue).toEqual({ steering: [], followUp: ['下一项任务'] });
  });

  it('projects provider retries as one live progress activity', () => {
    const started = reduceAgentEvent(
      createAgentProjection('session-1'),
      agentEvent(1, 'status_changed', {
        status: 'retrying',
        phase: 'provider_retry',
        activityState: 'running',
        summary: '模型连接暂时失败，正在自动重试（1/3）',
        attempt: 1,
        maxAttempts: 3,
        delayMs: 2_000,
      }),
    ).state;

    expect(started.status).toBe('retrying');
    expect(started.activitiesById['turn-1:status_changed']).toMatchObject({
      status: 'running',
      summary: '模型连接暂时失败，正在自动重试（1/3）',
    });

    const recovered = reduceAgentEvent(
      started,
      agentEvent(2, 'status_changed', {
        status: 'analyzing',
        phase: 'provider_retry',
        activityState: 'completed',
        summary: '模型连接已恢复，继续处理',
        attempt: 1,
        maxAttempts: 3,
        success: true,
      }),
    ).state;

    expect(recovered.status).toBe('analyzing');
    expect(recovered.activitiesById['turn-1:status_changed']).toMatchObject({
      status: 'completed',
      summary: '模型连接已恢复，继续处理',
    });
    expect(recovered.activityOrder).toEqual(['turn-1:status_changed']);
  });

  it('restores live tool and approval state from a snapshot without moving the SSE cursor', () => {
    const recovered = applyAgentSnapshot(createAgentProjection('session-1'), {
      messages: [serverMessage('server-user', 'user', 'history:server-user', '执行检查')],
      liveEvents: [
        rawAgentEvent(41, 'tool_started', {
          toolCallId: 'tool-live-1',
          toolName: 'workspace_search',
          summary: '正在搜索工作区',
        }),
        {
          ...rawAgentEvent(42, 'approval_required', {
            approvalId: 'approval-live-1',
            payloadSha256: 'a'.repeat(64),
            operation: '写入文件',
          }),
          turnId: 'approval:approval-live-1',
        },
      ],
      lastSequence: 42,
      resumeToken: 'session-1:42',
      status: 'busy',
    });

    expect(recovered.lastSequence).toBe(42);
    expect(recovered.resumeToken).toBe('session-1:42');
    expect(recovered.activitiesById['tool-live-1']).toMatchObject({
      kind: 'tool_started',
      status: 'running',
    });
    expect(recovered.activitiesById['approval-live-1']).toMatchObject({
      kind: 'approval_required',
      status: 'waiting',
      turnId: 'approval:approval-live-1',
    });
    expect(recovered.status).toBe('waiting');
  });

  it('restores the durable plan and advances it from live agent_plan results', () => {
    const restored = applyAgentSnapshot(createAgentProjection('session-1'), {
      messages: [],
      liveEvents: [],
      lastSequence: 0,
      resumeToken: '',
      plan: {
        revision: 2,
        items: [
          { id: 'step-1', title: '核对现状', status: 'completed', sequence: 1, updatedAtMs: 10 },
          { id: 'step-2', title: '实现清单', status: 'in_progress', sequence: 2, updatedAtMs: 20 },
        ],
      },
    });

    expect(restored.plan.counts).toEqual({
      total: 2,
      pending: 0,
      inProgress: 1,
      completed: 1,
    });

    const advanced = reduceAgentEvent(
      restored,
      agentEvent(1, 'tool_finished', {
        toolCallId: 'plan-update',
        toolName: 'agent_plan',
        result: {
          details: {
            result: {
              plan: {
                revision: 3,
                items: [
                  { id: 'step-1', title: '核对现状', status: 'completed', sequence: 1, updatedAtMs: 10 },
                  { id: 'step-2', title: '实现清单', status: 'completed', sequence: 3, updatedAtMs: 30 },
                ],
              },
            },
          },
        },
      }),
    ).state;

    expect(advanced.plan.revision).toBe(3);
    expect(advanced.plan.items.map((item) => item.status)).toEqual(['completed', 'completed']);
    expect(advanced.plan.counts.completed).toBe(2);
  });

  it('uses the authoritative idle snapshot status to recover a stale aborting turn', () => {
    const recovered = applyAgentSnapshot(createAgentProjection('session-1'), {
      messages: [],
      liveEvents: [
        rawAgentEvent(41, 'status_changed', { status: 'busy' }),
        rawAgentEvent(42, 'text_delta', { delta: 'partial' }),
        rawAgentEvent(43, 'status_changed', { status: 'aborting' }),
      ],
      lastSequence: 43,
      resumeToken: 'session-1:43',
      status: 'idle',
    });

    expect(recovered.status).toBe('idle');
    expect(recovered.turnsById['turn-1'].status).toBe('aborted');
    expect(recovered.messagesById['turn-1:assistant'].status).toBe('aborted');
  });

  it('does not reopen the last completed transcript turn when Pi marks the Session active', () => {
    const recovered = applyAgentSnapshot(createAgentProjection('session-1'), {
      messages: [
        serverMessage('server-user', 'user', 'turn-history', '调用 ime_overview'),
        serverMessage('server-assistant', 'assistant', 'turn-history', '控制中心运行正常。'),
      ],
      liveEvents: [rawAgentEvent(43, 'status_changed', { status: 'ready' })],
      lastSequence: 43,
      resumeToken: 'session-1:43',
      // AgentSessionStore uses active for an open transcript binding. It is
      // not evidence that Pi currently owns an in-flight turn.
      status: 'active',
    });

    expect(recovered.status).toBe('active');
    expect(recovered.turnsById['turn-history'].status).toBe('completed');
    expect(recovered.messagesById['server-assistant'].status).toBe('completed');
  });

  it('keeps bounded progress checkpoints for one logical tool call', () => {
    const started = reduceAgentEvent(
      createAgentProjection('session-1'),
      agentEvent(1, 'tool_started', {
        toolCallId: 'tool-progress-1',
        toolName: 'ime_knowledge',
        summary: '开始检索知识库',
        args: { path: 'docs/acceptance.md' },
      }),
    ).state;
    const firstProgress = reduceAgentEvent(
      started,
      agentEvent(2, 'tool_progress', {
        toolCallId: 'tool-progress-1',
        partialResult: { details: { summary: '已找到候选来源' } },
      }),
    ).state;
    const secondProgress = reduceAgentEvent(
      firstProgress,
      agentEvent(3, 'tool_progress', {
        toolCallId: 'tool-progress-1',
        partialResult: { details: { result: { summary: '正在重排 4 条证据' } } },
      }),
    ).state;
    const finished = reduceAgentEvent(
      secondProgress,
      agentEvent(4, 'tool_finished', {
        toolCallId: 'tool-progress-1',
        args: {},
        result: { details: { result: { summary: '知识检索完成' } } },
      }),
    ).state;

    expect(finished.activityOrder).toEqual(['tool-progress-1']);
    expect(finished.activitiesById['tool-progress-1']).toMatchObject({
      kind: 'tool_finished',
      status: 'completed',
      createdAtMs: 10,
      updatedAtMs: 40,
      payload: {
        toolName: 'ime_knowledge',
        args: { path: 'docs/acceptance.md' },
        progressHistory: [
          { kind: 'tool_started', summary: '开始检索知识库', createdAtMs: 10 },
          { kind: 'tool_progress', summary: '已找到候选来源', createdAtMs: 20 },
          { kind: 'tool_progress', summary: '正在重排 4 条证据', createdAtMs: 30 },
          { kind: 'tool_finished', summary: '知识检索完成', createdAtMs: 40 },
        ],
      },
    });
  });

  it('merges an optimistic user message only by clientMessageId', () => {
    const optimistic = appendOptimisticAgentMessage(createAgentProjection('session-1'), {
      clientMessageId: 'client-1',
      text: '同一段文字',
      nowMs: 10,
    });
    const completed = reduceAgentEvent(
      optimistic,
      agentEvent(1, 'message_completed', {
        clientMessageId: 'client-1',
        message: {
          ...serverMessage('server-1', 'user', 'turn-server', '同一段文字'),
          clientMessageId: 'client-1',
        },
      }),
    ).state;

    expect(completed.messageOrder).toEqual(['server-1']);
    expect(completed.messagesById['local:client-1']).toBeUndefined();
    expect(completed.messagesById['server-1'].clientMessageId).toBe('client-1');
    expect(completed.optimisticByClientMessageId).toEqual({});
  });

  it('keeps an unaccepted prompt failure across a Session snapshot refresh', () => {
    const optimistic = appendOptimisticAgentMessage(createAgentProjection('session-1'), {
      clientMessageId: 'client-failed',
      text: '发送失败后仍可重试',
      nowMs: 10,
    });
    const failed = failOptimisticAgentMessage(
      optimistic,
      'client-failed',
      '当前模型不可用，请切换模型后重试。',
      20,
    );

    const restored = applyAgentSnapshot(failed, {
      messages: [],
      liveEvents: [],
      lastSequence: 7,
      resumeToken: 'session-1:7',
      status: 'idle',
    });

    expect(restored.messagesById['local:client-failed'].status).toBe('failed');
    expect(restored.messagesById['local:client-failed'].completedAtMs).toBe(20);
    expect(restored.turnsById['local-turn:client-failed']).toMatchObject({
      status: 'failed',
      updatedAtMs: 20,
      failure: '当前模型不可用，请切换模型后重试。',
    });
  });

  it('retains unknown events and can abort an active turn without throwing', () => {
    const unknown = reduceAgentEvent(
      createAgentProjection('session-1'),
      parseAgentEvent({
        ...rawAgentEvent(1, 'future_tool_panel', { safe: 'summary' }),
      }),
    ).state;
    expect(unknown.diagnostics[0]).toMatchObject({
      eventType: 'future_tool_panel',
      payload: { safe: 'summary' },
    });

    const streaming = reduceAgentEvent(
      unknown,
      agentEvent(2, 'text_delta', { delta: 'partial' }),
    ).state;
    const aborted = abortAgentTurn(streaming, 'turn-1', 30);
    expect(aborted.turnsById['turn-1'].status).toBe('aborted');
    expect(aborted.messagesById['turn-1:assistant'].status).toBe('aborted');
  });

  it('projects an abort fallback terminal event as aborted instead of completed', () => {
    const streaming = reduceAgentEvent(
      createAgentProjection('session-1'),
      agentEvent(1, 'text_delta', { delta: 'partial' }),
    ).state;
    const stopped = reduceAgentEvent(
      streaming,
      agentEvent(2, 'turn_completed', {
        status: 'aborted',
        aborted: true,
        terminalEvent: 'abort_timeout',
      }),
    ).state;

    expect(stopped.status).toBe('idle');
    expect(stopped.turnsById['turn-1'].status).toBe('aborted');
    expect(stopped.messagesById['turn-1:assistant'].status).toBe('aborted');
  });

  it('hides legacy per-turn user source checkpoints but keeps explicit memory work', () => {
    const captured = reduceAgentEvent(
      createAgentProjection('session-1'),
      agentEvent(1, 'memory_checkpointed', {
        sourceRole: 'user',
        status: 'checkpointed',
        summary: '最终用户消息已保存为记忆来源，等待异步整理',
      }),
    ).state;
    expect(captured.activityOrder).toEqual([]);
    expect(captured.turnOrder).toEqual([]);

    const receipt = reduceAgentEvent(
      captured,
      agentEvent(2, 'memory_checkpointed', {
        sourceRole: 'tool_receipt',
        status: 'checkpointed',
        summary: '已应用工具回执已保存为记忆来源，等待异步整理',
      }),
    ).state;
    expect(receipt.activityOrder).toHaveLength(1);
    expect(receipt.activitiesById[receipt.activityOrder[0]]).toMatchObject({
      kind: 'memory_checkpointed',
      status: 'completed',
    });
  });
});

function rawAgentEvent(
  sequence: number,
  eventType: string,
  payload: Record<string, unknown>,
) {
  return {
    schemaVersion: 'rag-ime.agent-event.v1',
    eventId: `session-1:${sequence}`,
    sessionId: 'session-1',
    turnId: 'turn-1',
    sequence,
    createdAtMs: sequence * 10,
    eventType,
    payload: {
      messageId: 'turn-1:assistant',
      blockId: 'turn-1:assistant:text',
      ...payload,
    },
    resumeToken: `session-1:${sequence}`,
  };
}

function serverMessage(id: string, role: 'user' | 'assistant', turnId: string, text: string) {
  return {
    schemaVersion: 'rag-ime.agent-message.v1',
    id,
    sessionId: 'session-1',
    turnId,
    role,
    status: 'completed',
    blocks: [
      {
        id: `${id}:text`,
        type: 'text',
        status: 'completed',
        presentationKind: 'markdown',
        data: { text },
      },
    ],
    attachments: [],
    citations: [],
    createdAtMs: 20,
    completedAtMs: 21,
  };
}

function textOf(message: { blocks: { data: Record<string, unknown> }[] }): string {
  return String(message.blocks[0]?.data.text ?? '');
}
