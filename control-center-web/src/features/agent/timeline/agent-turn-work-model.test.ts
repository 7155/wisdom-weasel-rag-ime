import { describe, expect, it } from 'vitest';
import type { AgentActivityProjection, AgentMessageProjection } from '@/contracts/agent-reducer';
import { buildAgentTurnWorkModel, type AgentTurnSequenceEntry } from './agent-turn-work-model';

describe('Agent turn work projection', () => {
  it('keeps the explicit final response visible and marks preceding process as collapsible', () => {
    const entries: AgentTurnSequenceEntry[] = [
      message('draft', '先检查项目。'),
      activityGroup(activity('tool-read', 'tool_finished')),
      message('final', '检查完成，入口已经修复。'),
    ];

    expect(buildAgentTurnWorkModel('completed', entries)).toMatchObject({
      canCollapse: true,
      finalMessageId: 'final',
      hiddenActivityCount: 1,
      hiddenMessageCount: 1,
      resultCount: 1,
      toolCount: 1,
      items: [
        { role: 'work' },
        { role: 'work' },
        { role: 'result' },
      ],
    });
  });

  it.each(['queued', 'running', 'waiting'] as const)(
    'fails open while a turn is %s',
    (status) => {
      const model = buildAgentTurnWorkModel(status, [
        activityGroup(activity('tool-read', 'tool_finished')),
        message('answer', '暂时结果'),
      ]);

      expect(model.canCollapse).toBe(false);
      expect(model.finalMessageId).toBe('');
    },
  );

  it.each(['failed', 'aborted'] as const)(
    'collapses %s process work while the last partial narrative stays visible',
    (status) => {
      const model = buildAgentTurnWorkModel(status, [
        message('draft', '先检查项目。'),
        activityGroup(activity('tool-read', 'tool_finished')),
        message('answer', '暂时结果'),
      ]);

      expect(model.canCollapse).toBe(true);
      expect(model.finalMessageId).toBe('answer');
      expect(model.items.map((item) => item.role)).toEqual(['work', 'work', 'result']);
    },
  );

  it.each(['failed', 'aborted'] as const)(
    'collapses %s tool work even when no narrative result exists',
    (status) => {
      const model = buildAgentTurnWorkModel(status, [
        activityGroup(activity('tool-read', 'tool_finished')),
      ]);

      expect(model.canCollapse).toBe(true);
      expect(model.finalMessageId).toBe('');
      expect(model.hiddenActivityCount).toBe(1);
    },
  );

  it('fails open when a failed turn holds only its narrative', () => {
    const model = buildAgentTurnWorkModel('failed', [message('answer', '暂时结果')]);

    expect(model.canCollapse).toBe(false);
    expect(model.finalMessageId).toBe('answer');
    expect(model.items).toHaveLength(1);
    expect(model.items[0]).toMatchObject({ role: 'result' });
  });

  it('fails open when a completed turn has no narrative final response', () => {
    const model = buildAgentTurnWorkModel('completed', [
      activityGroup(activity('tool-read', 'tool_finished')),
      structuredMessage('artifact-only', 'artifact'),
    ]);

    expect(model.canCollapse).toBe(false);
    expect(model.finalMessageId).toBe('');
    expect(model.items[1]).toMatchObject({ role: 'result' });
  });

  it('keeps response-tail evidence visible without reordering later work', () => {
    const entries: AgentTurnSequenceEntry[] = [
      message('draft', '开始生成。'),
      structuredMessage('patch', 'diff'),
      activityGroup(activity('verify', 'tool_finished')),
      message('final', '修改和验证都完成了。'),
    ];
    const model = buildAgentTurnWorkModel('completed', entries);

    expect(model.items.map((item) => `${item.entry.kind}:${item.role}`)).toEqual([
      'message:work',
      'message:result',
      'activity-group:work',
      'message:result',
    ]);
    expect(model.items.map((item) => item.entry)).toEqual(entries);
  });
});

function message(id: string, value: string): Extract<AgentTurnSequenceEntry, { kind: 'message' }> {
  return {
    kind: 'message',
    message: {
      schemaVersion: 'rag-ime.agent-message.v1',
      id,
      sessionId: 'session-1',
      turnId: 'turn-1',
      role: 'assistant',
      status: 'completed',
      blocks: [{
        schemaVersion: 'rag-ime.agent-block.v1',
        id: `${id}:text`,
        type: 'text',
        status: 'completed',
        presentationKind: 'markdown',
        data: { text: value },
      }],
      attachments: [],
      citations: [],
      createdAtMs: 1,
      completedAtMs: 2,
    },
  };
}

function structuredMessage(id: string, type: 'artifact' | 'diff'): AgentTurnSequenceEntry {
  const base = message(id, '').message;
  return {
    kind: 'message',
    message: {
      ...base,
      blocks: [{
        schemaVersion: 'rag-ime.agent-block.v1',
        id: `${id}:${type}`,
        type,
        status: 'completed',
        presentationKind: type,
        data: { title: '结果', patch: '--- a\n+++ b' },
      } as AgentMessageProjection['blocks'][number]],
    },
  };
}

function activityGroup(value: AgentActivityProjection): AgentTurnSequenceEntry {
  return { kind: 'activity-group', key: `activity:${value.id}`, activities: [value] };
}

function activity(id: string, kind: string): AgentActivityProjection {
  return {
    id,
    turnId: 'turn-1',
    kind,
    status: 'completed',
    summary: id,
    payload: { toolCallId: id },
    createdAtMs: 1,
    updatedAtMs: 2,
  };
}
