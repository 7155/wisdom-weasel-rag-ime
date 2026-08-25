import { describe, expect, it } from 'vitest';
import type { AgentSubagentRunV1 } from '@/contracts/generated/agent-subagent-run.v1';
import type { RoomFocusProjection } from '../room-focus-projection';
import { buildRoomFeed, buildSessionFeed, feedTimeLabel, STARFIELD_FEED_LIMIT } from './starfield-feed';

function run(
  id: string,
  state: AgentSubagentRunV1['state'],
  updatedAtMs: number,
): AgentSubagentRunV1 {
  return {
    schemaVersion: 'rag-ime.agent-subagent-run.v1',
    id,
    nodeId: `node:${id}`,
    attemptId: `attempt:${id}`,
    attemptNumber: 1,
    predecessorAttemptId: '',
    ownerRunId: '',
    parentRunId: '',
    depth: 1,
    batchId: 'batch',
    childSessionId: `child:${id}`,
    todoTask: '',
    todoPhase: '',
    templateId: 'researcher',
    templateVersion: '1',
    ordinal: 0,
    task: `任务 ${id}`,
    expectedOutput: '',
    acceptanceCriteria: [],
    launchDigest: {
      schemaVersion: 'rag-ime.agent-subagent-launch-digest.v1',
      contextMode: 'fresh',
      templateId: 'researcher',
      templateVersion: '1',
      modelProfile: 'default',
      thinkingLevel: 'medium',
      toolProfileVersion: 'subagent-readonly-v1',
      toolAllowlistMode: 'profile',
      tools: [],
      piSkillsEnabled: false,
      codexSkillsEnabled: false,
      workspaceAccess: 'read_only',
      workspaceRootCount: 0,
      outputContract: { required: false, schemaSha256: '' },
      extensionRuntime: 'pi_host_managed',
    },
    contract: { status: 'not_requested', error: '', toolCallId: '', validatedAtMs: null },
    state,
    budget: { maxTurns: 8, maxToolCalls: 12, maxTotalTokens: 16_000, maxDurationMs: 60_000, maxOutputChars: 8_000 },
    usage: { turnCount: 1, toolCount: 1, totalTokens: 100 },
    result: {},
    error: '',
    resultContextScheduledAtMs: null,
    createdAtMs: 1_000,
    startedAtMs: null,
    updatedAtMs,
    completedAtMs: null,
  };
}

describe('starfield feed', () => {
  it('leads a busy Session with the core planet and lists real runs newest first', () => {
    const feed = buildSessionFeed(
      [run('run-a', 'completed', 1_000), run('run-b', 'running', 5_000)],
      { busy: true, sessionTitle: '当前 Session', nowMs: 10_000 },
    );

    expect(feed.map((item) => item.id)).toEqual(['session:busy', 'run:run-b', 'run:run-a']);
    expect(feed[0]).toMatchObject({ actor: '当前 Session', tone: 'working', bodyId: 'center' });
    expect(feed[1]).toMatchObject({ actor: '研究员', stateLabel: '进行中', tone: 'working', bodyId: 'run-b' });
    expect(feed[2]).toMatchObject({ stateLabel: '已完成', tone: 'done', bodyId: 'run-a' });

    const idle = buildSessionFeed([run('run-a', 'completed', 1_000)], { busy: false, sessionTitle: 'S', nowMs: 10_000 });
    expect(idle.map((item) => item.id)).toEqual(['run:run-a']);
  });

  it('caps the Session feed at a readable length', () => {
    const runs = Array.from({ length: 20 }, (_, index) => run(`run-${index}`, 'completed', index));
    expect(buildSessionFeed(runs, { busy: true, sessionTitle: 'S', nowMs: 100 })).toHaveLength(STARFIELD_FEED_LIMIT);
  });

  it('leads the Room feed with the shared objective, then live work, then real handoffs', () => {
    const focus: RoomFocusProjection = {
      goal: { title: '交付星空 v2', description: '把真实工作放到星空前面', rootId: 'root', state: 'running' },
      workItems: [],
      flow: [],
      partners: [
        {
          participantId: 'p-earth',
          sessionId: 's-earth',
          displayName: 'Earth 伙伴',
          celestialName: 'Earth',
          state: 'running',
          ownedWorkItemIds: ['w1'],
          currentAction: '正在实现依赖图',
          unread: false,
        },
        {
          participantId: 'p-mars',
          sessionId: 's-mars',
          displayName: 'Mars 伙伴',
          celestialName: 'Mars',
          state: 'completed',
          ownedWorkItemIds: [],
          currentAction: '等待新的工作项',
          unread: false,
        },
        {
          participantId: 'p-venus',
          sessionId: 's-venus',
          displayName: 'Venus 伙伴',
          celestialName: 'Venus',
          state: 'blocked',
          ownedWorkItemIds: ['w2'],
          currentAction: '等待工作目录授权',
          unread: false,
        },
      ],
      handoffs: [
        { id: 'h-old', sourceParticipantId: 'p-earth', targetParticipantId: 'p-mars', task: '早期交接', state: 'completed', createdAtMs: 1_000 },
        { id: 'h-live', sourceParticipantId: 'p-earth', targetParticipantId: 'p-mars', task: '复核依赖图', state: 'dispatched', createdAtMs: 2_000 },
      ],
      rootEvidence: [],
      counts: { active: 1, review: 0, blocked: 0, completed: 1 },
    };
    const feed = buildRoomFeed(focus, { hosted: true });

    // Objective first, then the partner who needs the user, then live work.
    expect(feed.map((item) => item.id)).toEqual([
      'room:goal', 'partner:p-venus', 'partner:p-earth', 'handoff:h-live', 'handoff:h-old',
    ]);
    expect(feed[0]).toMatchObject({
      actor: 'Sol · 交付星空 v2',
      text: '把真实工作放到星空前面',
      stateLabel: '进行中',
      bodyId: 'center',
    });
    expect(feed[1]).toMatchObject({ actor: 'Venus', text: '等待工作目录授权', tone: 'attention' });
    expect(feed[2]).toMatchObject({ actor: 'Earth', text: '正在实现依赖图', tone: 'working', bodyId: 'p-earth' });
    expect(feed[3]).toMatchObject({ actor: 'Earth → Mars', stateLabel: '交接中', tone: 'working', bodyId: 'p-mars' });
    expect(feed[4]).toMatchObject({ stateLabel: '已交付', tone: 'done' });
  });

  it('drops the Sol reference from the goal row when nobody hosts the Room', () => {
    const focus: RoomFocusProjection = {
      goal: { title: '无主持人的目标', description: '', rootId: 'root', state: 'waiting' },
      workItems: [],
      flow: [],
      partners: [],
      handoffs: [],
      rootEvidence: [],
      counts: { active: 0, review: 0, blocked: 0, completed: 0 },
    };
    const [goal] = buildRoomFeed(focus, { hosted: false });

    expect(goal).toMatchObject({ actor: '无主持人的目标', text: '这间 Room 的共同目标' });
    // No Sol on stage means no body to highlight from the goal row.
    expect(goal?.bodyId).toBeUndefined();
  });

  it('formats feed timestamps as short user words', () => {
    const now = 10 * 86_400_000;
    expect(feedTimeLabel(0, now)).toBe('现在');
    expect(feedTimeLabel(now - 20_000, now)).toBe('刚刚');
    expect(feedTimeLabel(now - 5 * 60_000, now)).toBe('5 分钟前');
    expect(feedTimeLabel(now - 3 * 3_600_000, now)).toBe('3 小时前');
    expect(feedTimeLabel(now - 2 * 86_400_000, now)).toBe('2 天前');
  });
});
