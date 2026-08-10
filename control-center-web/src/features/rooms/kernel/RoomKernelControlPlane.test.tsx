import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { RoomKernelReceiptV1 } from '@/contracts/generated/room-kernel-receipt.v1';
import { createRoomKernelProjection, type RoomKernelProjection, type RootProjection } from '@/contracts/room-kernel-reducer';
import type { RoomParticipantPublicProgressProjection } from '@/contracts/room-reducer';
import { RoomKernelControlPlane } from './RoomKernelControlPlane';
import {
  createFixtureRoomKernelCommandTransport,
  type RoomKernelCommandTransport,
} from './room-kernel-command-transport';
import type { RoomTaskSubagentRun } from './RoomTaskFlowGraph';

describe('RoomKernelControlPlane', () => {
  afterEach(cleanup);

  it('renders public results while keeping private participant details behind an optional disclosure', () => {
    renderPlane(projection());
    expect(screen.getAllByRole('region', { name: '公开结果与回复' })[0]).toHaveTextContent('经过明确提交的研究发现');
    const sessions = screen.getAllByRole('region', { name: '伙伴运行状态' })[0]!;
    expect(sessions).not.toHaveTextContent('Session 私有正文');
    const taskFlow = screen.getAllByRole('region', { name: '任务依赖图' })[0]!;
    expect(within(taskFlow).getByText('核对索引证据')).toBeInTheDocument();
    expect(within(taskFlow).getByText('审查员')).toBeInTheDocument();
    expect(taskFlow).not.toHaveTextContent(/推进：证据回执|尚未验证|当前动作|下一步/);
    expect(within(taskFlow).getByText('等待共同结果')).toBeInTheDocument();
    expect(taskFlow.querySelector('.room-task-flow__dispatch-node')).not.toBeInTheDocument();
    const taskWork = screen.getAllByRole('region', { name: '每项工作的详细进展' })[0]!;
    const workCard = taskWork.querySelector('.room-task-work-card')!;
    expect(workCard).not.toHaveAttribute('open');
    expect(workCard.querySelector('summary')).toHaveTextContent('核对索引证据审查员 · 执行中完成情况尚未验证');
    fireEvent.click(workCard.querySelector('summary')!);
    expect(workCard).toHaveTextContent('当前动作推进：证据回执');
    const progressDisclosure = screen.getAllByText('查看每位伙伴的进度')[0]!.closest('details');
    expect(progressDisclosure).not.toHaveAttribute('open');
    fireEvent.click(screen.getAllByText('查看每位伙伴的进度')[0]!);
    expect(progressDisclosure).toHaveAttribute('open');
    const auditSummary = screen.getAllByText('查看运行确认与验收记录')[0]!;
    const auditDisclosure = auditSummary.closest('details');
    expect(auditDisclosure).not.toHaveAttribute('open');
    fireEvent.click(auditSummary);
    expect(screen.getAllByRole('region', { name: '运行确认' })[0]).toHaveTextContent('当前连接没有停止权限');
  });

  it('renders a stable task dependency graph without Agent, Dispatch, or Receipt nodes', () => {
    const state = projection();
    state.tasksById['task-a'] = {
      ...state.tasksById['task-a']!,
      currentOwnerParticipantId: 'researcher',
      contextEvidenceRefs: ['evidence:task-a'],
      state: 'completed',
      revision: 2,
    };
    state.tasksById['task-b'] = {
      ...state.tasksById['task-a']!,
      parentTaskId: 'task-a',
      taskId: 'task-b',
      currentOwnerParticipantId: 'researcher',
      objective: '整合证据与实现结果',
      expectedOutput: '可复核的整合结果',
      state: 'active',
      revision: 1,
    };
    state.tasksById['task-review'] = {
      ...state.tasksById['task-a']!,
      taskId: 'task-review',
      taskKind: 'review',
      currentOwnerParticipantId: 'reviewer',
      objective: '独立复核整合结果',
      expectedOutput: '复核结论',
      reviewOfTaskIds: ['task-b'],
      reviewAuthorParticipantIds: ['reviewer'],
      reviewState: 'required',
      state: 'waiting',
      revision: 1,
    };
    state.dispatchesById['dispatch-a'] = {
      schemaVersion: 'wisdom-weasel.room-dispatch-envelope.v2',
      dispatchId: 'dispatch-a',
      rootId: 'root-a',
      taskId: 'task-a',
      parentDispatchId: null,
      generation: 3,
      hopCount: 0,
      depth: 0,
      budgetCost: 1,
      targetSessionId: 'session-research',
      targetParticipantId: 'researcher',
      triggerId: 'trigger-a',
      intentKind: 'execute',
      idempotencyKey: 'dispatch-a',
      attempt: 1,
      capabilityEpoch: 1,
      runtimeProfileRevision: 'runtime-1',
      dependsOnDispatchIds: ['dispatch:outside-snapshot'],
      state: 'committed',
    };
    state.dispatchesById['dispatch-b'] = {
      ...state.dispatchesById['dispatch-a']!,
      dispatchId: 'dispatch-b',
      taskId: 'task-b',
      triggerId: 'trigger-b',
      idempotencyKey: 'dispatch-b',
      dependsOnDispatchIds: ['dispatch-a'],
      state: 'running',
    };
    state.dispatchesById['dispatch-review'] = {
      ...state.dispatchesById['dispatch-a']!,
      dispatchId: 'dispatch-review',
      taskId: 'task-review',
      targetSessionId: 'session-review',
      targetParticipantId: 'reviewer',
      triggerId: 'trigger-review',
      intentKind: 'review',
      idempotencyKey: 'dispatch-review',
      dependsOnDispatchIds: ['dispatch-b'],
      state: 'pending',
    };
    state.postOrder.push('post-task-a-result');
    state.postsById['post-task-a-result'] = {
      schemaVersion: 'wisdom-weasel.room-post.v2',
      postId: 'post-task-a-result',
      roomId: 'room-a',
      rootId: 'root-a',
      generation: 3,
      taskId: 'task-a',
      dispatchId: 'dispatch-a',
      authorActorRef: 'researcher',
      kind: 'result',
      visibility: 'room',
      content: '索引证据已经核对完成',
      idempotencyKey: 'post-task-a-result',
      publicationSource: { kind: 'room_commit', ref: 'commit-task-a-result' },
      createdAtMs: 20,
    };

    renderPlane(state);

    const graph = screen.getAllByRole('region', { name: '任务依赖图' })[0]!;
    expect(graph.querySelectorAll('.room-task-flow__task-node')).toHaveLength(3);
    expect(graph.querySelectorAll('.room-task-flow__edges g')).toHaveLength(4);
    expect(within(graph).getByRole('progressbar', { name: /3 项任务/ })).toHaveAttribute(
      'aria-valuenow',
      '1',
    );
    expect(graph.querySelector('.room-task-flow__dispatch-node')).not.toBeInTheDocument();
    const completed = within(graph).getByRole('article', { name: /索引证据已经核对完成/ });
    expect(completed).toHaveTextContent('任务结果');
    expect(completed).toHaveTextContent('索引证据已经核对完成');
    expect(completed).toHaveTextContent('负责人研究员');
    expect(within(completed).getByRole('progressbar', { name: /任务已完成/ })).toHaveAttribute(
      'aria-valuenow',
      '1',
    );
    expect(completed).toHaveTextContent('最近提交：索引证据已经核对完成');
    expect(completed).not.toHaveTextContent('当前状态');
    expect(completed).not.toHaveTextContent(/下一步|验证状态/);
    expect(completed).toHaveAttribute('title', expect.not.stringMatching(/Dispatch|dispatch/));
    const integration = within(graph).getByRole('article', { name: /整合证据与实现结果/ });
    expect(integration).toHaveAttribute('data-task-stage', '接续 / 整合任务');
    expect(integration).toHaveAttribute('title', expect.stringMatching(/等待 1 项真实前置任务/));
    const review = within(graph).getByRole('article', { name: /独立复核整合结果/ });
    expect(review).toHaveTextContent('审查员');
    expect(within(review).getByRole('progressbar', { name: /前置 0 \/ 1 已完成/ })).toHaveAttribute(
      'aria-valuenow',
      '0',
    );
    expect(graph).not.toHaveTextContent(/运行尝试|dispatch-a|dispatch:outside-snapshot|receipt:/);
    expect(screen.getByRole('region', { name: '协作任务进展' }).querySelector(
      '.lucide-arrow-right, .lucide-chevron-right',
    )).toBeNull();
    const workList = screen.getAllByRole('region', { name: '每项工作的详细进展' })[0]!;
    const completedCard = [...workList.querySelectorAll('.room-task-work-card')].find((card) => (
      card.textContent?.includes('索引证据已经核对完成')
    ))!;
    fireEvent.click(completedCard.querySelector('summary')!);
    expect(completedCard).toHaveTextContent(/下一步交给\s*研究员\s*接续/);
    expect(completedCard).toHaveTextContent('已记录 1 项验证证据，等待验收');
  });

  it('projects only the newest authoritative Root into one task graph', () => {
    const state = projection();
    state.rootsById['root-a'] = {
      ...state.rootsById['root-a']!,
      state: 'cancelled_with_unknowns',
      createdAtMs: 1,
      updatedAtMs: 10_000,
    };
    state.tasksById['task-a'] = {
      ...state.tasksById['task-a']!,
      objective: '旧轮次任务不应继续占据任务图',
      state: 'active',
    };
    state.rootsById['root-b'] = {
      ...root('root-b', 1, 'reviewer', 'running', 2),
      state: 'running',
      createdAtMs: 2,
      updatedAtMs: 2,
    };
    state.tasksById['task-new-root'] = {
      ...state.tasksById['task-a']!,
      taskId: 'task-new-root',
      rootId: 'root-b',
      ownershipReceiptId: null,
      objective: '新一轮客户导入正在执行',
      expectedOutput: '新 Root 的可复核结果',
      state: 'active',
    };

    renderPlane(state);

    expect(screen.getAllByRole('region', { name: '任务依赖图' })).toHaveLength(1);
    const graph = screen.getByRole('region', { name: '任务依赖图' });
    expect(graph).toHaveTextContent('新一轮客户导入正在执行');
    expect(graph).toHaveTextContent('等待共同结果');
    expect(graph).not.toHaveTextContent('旧轮次任务不应继续占据任务图');
    expect(screen.queryByText('任务已停止')).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: '协作任务进展' })).toHaveTextContent('1 个共同目标 · 1 项工作');
  });

  it('shows privacy-bounded task collaborators with human labels, budget, public result, generic failure, and timing', () => {
    const subagents: RoomTaskSubagentRun[] = [
      {
        templateId: 'worker',
        ordinal: 0,
        task: '实现任务卡中的紧凑进度',
        state: 'running',
        budget: {
          maxTurns: 6,
          maxToolCalls: 8,
          maxTotalTokens: 12_000,
          maxDurationMs: 180_000,
          maxOutputChars: 8_000,
        },
        usage: { turnCount: 2, toolCount: 3, totalTokens: 1_200 },
        resultSummary: '',
        error: '',
        createdAtMs: 1_000,
        startedAtMs: 2_000,
        updatedAtMs: 3_000,
        completedAtMs: null,
      },
      {
        templateId: 'reviewer',
        ordinal: 1,
        task: '独立复核任务卡的公开信息边界',
        state: 'failed',
        budget: {
          maxTurns: 4,
          maxToolCalls: 6,
          maxTotalTokens: 8_000,
          maxDurationMs: 120_000,
          maxOutputChars: 6_000,
        },
        usage: { turnCount: 4, toolCount: 5, totalTokens: 3_200 },
        resultSummary: '已返回可复核的界面结论',
        error: '任务内协作者未能完成；负责人可检查任务状态后决定是否重试。',
        createdAtMs: 1_000,
        startedAtMs: 2_000,
        updatedAtMs: 4_000,
        completedAtMs: 4_000,
      },
      {
        templateId: 'researcher',
        ordinal: 2,
        task: '整理可公开的任务内结论',
        state: 'completed',
        budget: {
          maxTurns: 5,
          maxToolCalls: 7,
          maxTotalTokens: 10_000,
          maxDurationMs: 150_000,
          maxOutputChars: 7_000,
        },
        usage: { turnCount: 3, toolCount: 4, totalTokens: 2_400 },
        resultSummary: '已返回可复核的界面结论',
        error: '',
        createdAtMs: 1_000,
        startedAtMs: 2_000,
        updatedAtMs: 5_000,
        completedAtMs: 5_000,
      },
    ];
    renderPlane(projection(), undefined, false, [], { 'task-a': subagents });

    const graph = screen.getAllByRole('region', { name: '任务依赖图' })[0]!;
    expect(graph).not.toHaveTextContent('临时协作者');
    const workList = screen.getAllByRole('region', { name: '每项工作的详细进展' })[0]!;
    const workCard = workList.querySelector('.room-task-work-card')!;
    fireEvent.click(workCard.querySelector('summary')!);
    const collaborators = within(workCard as HTMLElement).getByRole('region', {
      name: '负责人调用了 3 个临时协作者',
    });
    expect(collaborators).toHaveTextContent('执行助手 1');
    expect(collaborators).toHaveTextContent('复核助手 2');
    expect(collaborators).toHaveTextContent('研究助手 3');
    expect(collaborators).toHaveTextContent('2 / 6 回合 · 3 / 8 次工具');
    expect(collaborators).toHaveTextContent('任务内协作者未能完成；负责人可检查任务状态后决定是否重试。');
    expect(collaborators).toHaveTextContent('已返回可复核的界面结论');
    expect(collaborators).toHaveTextContent(/更新 \d{2}:\d{2}/);
    expect(collaborators).toHaveTextContent(/结束 \d{2}:\d{2}/);
    expect(collaborators).not.toHaveTextContent(/run-secret|session-secret|batch-secret|private transcript/i);
  });

  it('presents optional handoff details without exposing protocol identifiers', () => {
    renderPlane(projection());
    const summary = screen.getByText('查看分工与交接详情');
    const ownership = summary.closest('details');
    expect(ownership).not.toBeNull();
    fireEvent.click(summary);
    expect(ownership).toHaveTextContent('核对索引证据');
    expect(ownership).toHaveTextContent('当前伙伴审查员');
    expect(ownership).toHaveTextContent('研究员审查员第 1 版');
    expect(ownership).toHaveTextContent('分工关系直接分配');
    expect(ownership).not.toHaveTextContent('task-a');
    expect(ownership).not.toHaveTextContent('receipt:ownership:1');
  });

  it('renders each participant in a distinct work lane with public progress', () => {
    const progress: RoomParticipantPublicProgressProjection[] = [
      {
        rootId: 'root-a',
        dispatchId: 'dispatch-review',
        participantId: 'reviewer',
        sourceSessionId: 'session-private-a',
        kind: 'reasoning',
        status: 'running',
        summary: '正在核对恢复后的任务边界',
        updatedAtMs: 12,
      },
      {
        rootId: 'root-a',
        dispatchId: 'dispatch-research',
        participantId: 'researcher',
        sourceSessionId: 'session-research',
        kind: 'tool',
        status: 'running',
        summary: 'read',
        data: { toolName: 'read' },
        updatedAtMs: 13,
      },
    ];
    renderPlane(projection(), undefined, false, progress);

    const phase = screen.getAllByRole('region', { name: '伙伴并行进度' })[0]!;
    const lanes = phase.querySelectorAll('.room-kernel-participant-lane');
    expect(lanes).toHaveLength(2);
    expect([...lanes].every((lane) => lane.className === 'room-kernel-participant-lane')).toBe(true);
    expect(phase).toHaveTextContent('主持整合与回复 · 唯一最终回复 · 已有本角色分工');
    expect(phase).toHaveTextContent('最终独立复核 · 已有本角色分工');
    expect(phase).toHaveTextContent('需求对齐与分工');
    expect(phase).toHaveTextContent('正在核对恢复后的任务边界');
    expect(phase).toHaveTextContent('读取文件正在处理');
    expect(phase).not.toHaveTextContent(/\bread\b/);
    expect(phase).not.toHaveTextContent('Session 私有正文');
  });

  it('shows implementation, integration, and independent-review stages from task state', () => {
    const implementing = projection();
    implementing.tasksById['task-implementation'] = {
      ...implementing.tasksById['task-a']!,
      taskId: 'task-implementation',
      parentTaskId: 'task-a',
      currentOwnerParticipantId: 'researcher',
      state: 'active',
    };
    const first = renderPlane(implementing);
    expect(
      screen.getAllByRole('region', { name: '伙伴并行进度' })[0],
    ).toHaveTextContent('第 2 步并行实现与调研');
    first.unmount();

    const integrating = projection();
    integrating.tasksById['task-implementation'] = {
      ...integrating.tasksById['task-a']!,
      taskId: 'task-implementation',
      parentTaskId: 'task-a',
      currentOwnerParticipantId: 'researcher',
      workspacePolicy: 'isolated_writable',
      workspaceIntegrationState: 'pending',
      state: 'completed',
    };
    const second = renderPlane(integrating);
    expect(
      screen.getAllByRole('region', { name: '伙伴并行进度' })[0],
    ).toHaveTextContent('第 2 步集成与验证');
    second.unmount();

    const reviewing = projection();
    reviewing.tasksById['task-review'] = {
      ...reviewing.tasksById['task-a']!,
      taskId: 'task-review',
      parentTaskId: 'task-a',
      taskKind: 'review',
      currentOwnerParticipantId: 'reviewer',
      reviewState: 'in_review',
      state: 'review',
    };
    renderPlane(reviewing);
    expect(
      screen.getAllByRole('region', { name: '伙伴并行进度' })[0],
    ).toHaveTextContent('第 3 步独立复核');
  });

  it('reveals shared final check only after every owned slice settles and keeps the final Room reply after it', () => {
    const running = projection();
    const first = renderPlane(running);
    expect(screen.queryByRole('region', { name: '一起检查' })).not.toBeInTheDocument();
    first.unmount();

    const settled = projection();
    settled.tasksById['task-a'] = { ...settled.tasksById['task-a']!, state: 'completed' };
    settled.rootsById['root-a'] = {
      ...settled.rootsById['root-a']!,
      state: 'completed',
      isFinal: true,
      terminalReceiptId: 'terminal-a',
    };
    settled.terminalReceiptByRootId['root-a'] = receipt({
      receiptId: 'terminal-a',
      commandId: null,
      receiptKind: 'terminal',
      details: { qualityGateVerdict: 'ready_to_deliver' },
    });
    settled.postOrder.push('post-final');
    settled.postsById['post-final'] = {
      schemaVersion: 'wisdom-weasel.room-post.v2',
      postId: 'post-final',
      roomId: 'room-a',
      rootId: 'root-a',
      generation: 3,
      authorActorRef: '研究员',
      kind: 'result',
      visibility: 'room',
      content: '每位伙伴的部分都已核验，这是最终回复。',
      idempotencyKey: 'post-final',
      publicationSource: { kind: 'room_commit', ref: 'commit-final' },
      createdAtMs: 20,
    };
    renderPlane(settled);

    const sharedCheck = screen.getByRole('region', { name: '一起检查' });
    const publicDelivery = screen.getAllByRole('region', { name: '公开结果与回复' })[0]!;
    expect(sharedCheck).toHaveTextContent('每个人的部分都已完成检查');
    expect(publicDelivery.firstElementChild?.nextElementSibling).toHaveAttribute('data-terminal', 'true');
    expect(publicDelivery).toHaveTextContent('每位伙伴的部分都已核验，这是最终回复。');
    expect(sharedCheck.compareDocumentPosition(publicDelivery) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('does not present an authoritative failed terminal receipt as success', () => {
    const failed = projection();
    failed.tasksById['task-a'] = { ...failed.tasksById['task-a']!, state: 'failed' };
    failed.rootsById['root-a'] = {
      ...failed.rootsById['root-a']!,
      state: 'failed',
      isFinal: true,
      terminalReceiptId: 'terminal-failed',
    };
    failed.terminalReceiptByRootId['root-a'] = receipt({
      receiptId: 'terminal-failed',
      commandId: null,
      receiptKind: 'terminal',
      details: { qualityGateVerdict: 'blocked' },
    });

    renderPlane(failed);

    const sharedCheck = screen.getByRole('region', { name: '一起检查' });
    expect(sharedCheck).toHaveAttribute('data-state', 'attention');
    expect(sharedCheck).toHaveTextContent('任务结束，但未通过检查');
    expect(sharedCheck).toHaveTextContent('任务未成功完成');
    expect(sharedCheck).not.toHaveTextContent('完成确认已到达');
    expect(sharedCheck).not.toHaveTextContent('每个人的部分都已完成检查');
  });

  it.each([
    ['completed', true],
    ['failed', false],
    ['cancelled', false],
    ['cancelled_with_unknowns', false],
  ] as const)('keeps one latest authoritative reply when the task ends as %s', (state, isFinal) => {
    const terminal = projection();
    terminal.rootsById['root-a'] = {
      ...terminal.rootsById['root-a']!,
      state,
      isFinal,
      terminalReceiptId: isFinal ? 'terminal-a' : null,
    };
    terminal.postOrder.push('post-earlier', 'post-latest');
    terminal.postsById['post-earlier'] = {
      schemaVersion: 'wisdom-weasel.room-post.v2',
      postId: 'post-earlier',
      roomId: 'room-a',
      rootId: 'root-a',
      generation: 3,
      authorActorRef: '研究员',
      kind: 'progress',
      visibility: 'room',
      content: '较早的公开进度',
      idempotencyKey: 'post-earlier',
      publicationSource: { kind: 'room_commit', ref: 'commit-earlier' },
      createdAtMs: 10,
    };
    terminal.postsById['post-latest'] = {
      ...terminal.postsById['post-earlier']!,
      postId: 'post-latest',
      kind: 'result',
      content: '本轮最后一份权威公开回复',
      idempotencyKey: 'post-latest',
      publicationSource: { kind: 'room_commit', ref: 'commit-latest' },
      createdAtMs: 20,
    };

    renderPlane(terminal);

    const publicDelivery = screen.getAllByRole('region', { name: '公开结果与回复' })[0]!;
    expect(publicDelivery).toHaveTextContent('本轮最后一份权威公开回复');
    expect(publicDelivery).not.toHaveTextContent('较早的公开进度');
    expect(publicDelivery.querySelectorAll('[data-terminal="true"]')).toHaveLength(1);
  });


  it('shows exactly one terminal summary from the authoritative reporter', () => {
    const terminal = projection();
    terminal.rootsById['root-a'] = {
      ...terminal.rootsById['root-a']!,
      state: 'completed',
      isFinal: true,
      reporterParticipantId: 'reviewer',
      reporterSelectionReceiptId: 'receipt:reporter:1',
      terminalReceiptId: 'terminal-a',
    };
    const basePost = {
      schemaVersion: 'wisdom-weasel.room-post.v2' as const,
      roomId: 'room-a',
      rootId: 'root-a',
      generation: 3,
      kind: 'result',
      visibility: 'room' as const,
    };
    terminal.postOrder.push('reporter-old', 'reporter-final', 'non-reporter-later');
    terminal.postsById['reporter-old'] = {
      ...basePost,
      postId: 'reporter-old',
      authorActorRef: 'reviewer',
      content: '较早的汇报人总结',
      idempotencyKey: 'reporter-old',
      publicationSource: { kind: 'room_commit', ref: 'commit-reporter-old' },
      createdAtMs: 10,
    };
    terminal.postsById['reporter-final'] = {
      ...terminal.postsById['reporter-old']!,
      postId: 'reporter-final',
      content: '唯一可见的最终汇报人总结',
      idempotencyKey: 'reporter-final',
      publicationSource: { kind: 'room_commit', ref: 'commit-reporter-final' },
      createdAtMs: 20,
    };
    terminal.postsById['non-reporter-later'] = {
      ...terminal.postsById['reporter-old']!,
      postId: 'non-reporter-later',
      authorActorRef: 'researcher',
      content: '不应冒充最终总结的参与者结果',
      idempotencyKey: 'non-reporter-later',
      publicationSource: { kind: 'room_commit', ref: 'commit-non-reporter' },
      createdAtMs: 30,
    };

    renderPlane(terminal);

    const publicDelivery = screen.getAllByRole('region', { name: '公开结果与回复' })[0]!;
    expect(publicDelivery).toHaveTextContent('唯一可见的最终汇报人总结');
    expect(publicDelivery).toHaveTextContent('汇报人 · 审查员');
    expect(publicDelivery).not.toHaveTextContent('较早的汇报人总结');
    expect(publicDelivery).not.toHaveTextContent('不应冒充最终总结的参与者结果');
    expect(publicDelivery.querySelectorAll('[data-terminal="true"]')).toHaveLength(1);
  });
  it('keeps the shared-check phase visible while peer review tasks are still running', () => {
    const state = projection();
    state.tasksById['task-a'] = { ...state.tasksById['task-a']!, state: 'completed' };
    state.tasksById['review-a'] = {
      ...state.tasksById['task-a']!,
      taskId: 'review-a',
      taskKind: 'review',
      currentOwnerParticipantId: 'researcher',
      ownershipReceiptId: null,
      objective: '检查伙伴公开结果',
      reviewOfTaskIds: ['task-a'],
      reviewAuthorParticipantIds: ['researcher'],
      reviewState: 'in_review',
      state: 'active',
    };
    state.rootsById['root-a'] = {
      ...state.rootsById['root-a']!,
      state: 'running',
      isFinal: false,
      terminalReceiptId: null,
    };
    renderPlane(state);

    const sharedCheck = screen.getByRole('region', { name: '一起检查' });
    expect(sharedCheck).toHaveTextContent('伙伴正在互相检查');
    expect(sharedCheck).toHaveTextContent('0 / 1 位伙伴已经完成检查');
    expect(sharedCheck).not.toHaveTextContent('最终回复');
  });

  it('does not expose a production Stop write without a command transport', () => {
    renderPlane(projection());
    const buttons = screen.getAllByRole('button', { name: '停止此任务' });
    expect(buttons[0]).toBeDisabled();
    expect(buttons[0]).toHaveAttribute('title', '当前连接没有停止任务的权限');
  });

  it('sends canonical room root generation command through fixture transport and displays receipt', async () => {
    const handler = vi.fn((command) => receipt({
      receiptId: 'cancel-root-a', commandId: command.commandId, rootId: command.rootId,
      generation: command.generation + 1, receiptKind: 'root_cancelled',
    }));
    const transport = createFixtureRoomKernelCommandTransport(handler);
    renderPlane(projection(), transport);

    fireEvent.click(screen.getAllByRole('button', { name: '停止此任务' })[0]!);
    await waitFor(() => expect(handler).toHaveBeenCalledTimes(1));
    expect(handler.mock.calls[0]?.[0]).toMatchObject({
      schemaVersion: 'wisdom-weasel.room-kernel-command.v1', roomId: 'room-a', rootId: 'root-a',
      targetKind: 'root', targetId: 'root-a', generation: 3, commandKind: 'cancel_root',
    });
    expect(await screen.findByText('停止请求已接受')).toBeInTheDocument();
  });

  it('stops only the exact active dispatch while keeping its Root and sibling task available', async () => {
    const state = projection();
    state.tasksById['task-b'] = {
      ...state.tasksById['task-a']!,
      taskId: 'task-b',
      currentOwnerParticipantId: 'researcher',
      ownershipReceiptId: null,
      objective: '继续整理索引结果',
      expectedOutput: '第二份证据回执',
    };
    state.dispatchesById['dispatch-a'] = {
      schemaVersion: 'wisdom-weasel.room-dispatch-envelope.v2',
      dispatchId: 'dispatch-a',
      rootId: 'root-a',
      taskId: 'task-a',
      parentDispatchId: null,
      generation: 3,
      hopCount: 0,
      depth: 0,
      budgetCost: 1,
      targetSessionId: 'session-review',
      targetParticipantId: 'reviewer',
      triggerId: 'trigger-a',
      intentKind: 'execute',
      idempotencyKey: 'dispatch-a',
      attempt: 1,
      capabilityEpoch: 1,
      runtimeProfileRevision: 'runtime-1',
      state: 'running',
    };
    state.dispatchesById['dispatch-b'] = {
      ...state.dispatchesById['dispatch-a']!,
      dispatchId: 'dispatch-b',
      taskId: 'task-b',
      targetSessionId: 'session-research',
      targetParticipantId: 'researcher',
      triggerId: 'trigger-b',
      idempotencyKey: 'dispatch-b',
    };
    const handler = vi.fn((command) => receipt({
      receiptId: `cancel-${command.targetId}`,
      commandId: command.commandId,
      rootId: command.rootId,
      generation: command.generation,
      receiptKind: 'target_cancelled',
    }));
    renderPlane(state, createFixtureRoomKernelCommandTransport(handler));

    fireEvent.click(screen.getByRole('button', { name: '停止审查员的这次运行' }));

    await waitFor(() => expect(handler).toHaveBeenCalledTimes(1));
    expect(handler.mock.calls[0]?.[0]).toMatchObject({
      roomId: 'room-a',
      rootId: 'root-a',
      generation: 3,
      commandKind: 'cancel_target',
      targetKind: 'dispatch',
      targetId: 'dispatch-a',
    });
    expect(screen.getByRole('button', { name: '停止此任务' })).toBeEnabled();
    expect(screen.getByRole('button', { name: '停止研究员的这次运行' })).toBeEnabled();
  });

  it('continues only failed work from a blocked Root through the typed command path', async () => {
    const state = projection();
    state.rootsById['root-a'] = {
      ...state.rootsById['root-a']!,
      state: 'blocked',
      isFinal: false,
      terminalReceiptId: null,
    };
    state.tasksById['task-a'] = { ...state.tasksById['task-a']!, state: 'blocked' };
    state.dispatchesById['dispatch-a'] = {
      ...state.dispatchesById['dispatch-a']!,
      state: 'failed',
    };
    const handler = vi.fn((command) => receipt({
      receiptId: 'retry-root-a',
      commandId: command.commandId,
      rootId: command.rootId,
      generation: command.generation,
      receiptKind: 'root_retried',
    }));
    renderPlane(state, createFixtureRoomKernelCommandTransport(handler));

    fireEvent.click(screen.getByRole('button', { name: '继续此任务' }));

    await waitFor(() => expect(handler).toHaveBeenCalledTimes(1));
    expect(handler.mock.calls[0]?.[0]).toMatchObject({
      roomId: 'room-a',
      rootId: 'root-a',
      generation: 3,
      commandKind: 'retry_root',
      targetKind: 'root',
      targetId: 'root-a',
    });
    expect(await screen.findByText('继续请求已接受')).toBeInTheDocument();
  });

  it('targets only the newest authoritative Root', async () => {
    const state = projection();
    state.rootsById['root-b'] = {
      ...root('root-b', 1, 'reviewer', 'running', 2),
      createdAtMs: 2,
    };
    const handler = vi.fn((command) => receipt({
      receiptId: `cancel-${command.rootId}`, commandId: command.commandId, rootId: command.rootId,
      generation: command.generation + 1, receiptKind: 'root_cancelled',
    }));
    renderPlane(state, createFixtureRoomKernelCommandTransport(handler));
    const button = screen.getByRole('button', { name: '停止此任务' });
    button.focus();
    fireEvent.keyDown(button, { key: 'Enter' });
    fireEvent.click(button);
    await waitFor(() => expect(handler).toHaveBeenCalledTimes(1));
    expect(handler.mock.calls[0]?.[0]).toMatchObject({ rootId: 'root-b', generation: 1 });
  });

  it('shows final only from the read projection terminal receipt', () => {
    const state = projection();
    state.rootsById['root-a'] = { ...state.rootsById['root-a']!, state: 'completed', terminalReceiptId: 'terminal-a', isFinal: true };
    state.terminalReceiptByRootId['root-a'] = receipt({
      receiptId: 'terminal-a', commandId: null, receiptKind: 'terminal', rootId: 'root-a', generation: 3,
      details: {
        qualityGateVerdict: 'ready_to_deliver',
        deliveryGateObservation: {
          gateObservationRef: 'gate-a', gateStatus: 'warn_blocked', mode: 'observe_warn',
          enforcementApplied: false, reasons: ['unresolved_unknown'],
        },
      },
    });
    renderPlane(state);
    expect(screen.getByText('任务已完成')).toBeInTheDocument();
    expect(screen.getAllByText('已结束，仍有检查提醒')).not.toHaveLength(0);
    expect(screen.getByText('全部验收项已有有效证据')).toBeInTheDocument();
    expect(screen.getByText('发现阻塞或未知项')).toBeInTheDocument();
    expect(screen.queryByText('已完成并通过检查')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '停止此任务' })).not.toBeInTheDocument();
  });

  it('exposes Room panic only for an admin gate and requires explicit inline confirmation', async () => {
    const handler = vi.fn((command) => receipt({
      receiptId: 'panic-room-a', commandId: command.commandId, rootId: null,
      generation: 0, receiptKind: 'panic', status: 'applied',
    }));
    renderPlane(projection(), createFixtureRoomKernelCommandTransport(handler), true);
    fireEvent.click(screen.getByRole('button', { name: '停止全部任务' }));
    expect(screen.getByRole('alert')).toHaveTextContent('正在运行的伙伴、工具和后续任务');
    expect(handler).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: '继续运行' }));
    expect(screen.queryByRole('button', { name: '确认停止全部' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '停止全部任务' }));
    fireEvent.click(screen.getByRole('button', { name: '确认停止全部' }));
    await waitFor(() => expect(handler).toHaveBeenCalledTimes(1));
    expect(handler.mock.calls[0]?.[0]).toMatchObject({
      roomId: 'room-a', rootId: null, commandKind: 'panic', targetKind: null, generation: 0,
    });
    expect(await screen.findByText('停止请求已接受')).toBeInTheDocument();
  });

  it('shows Room goals and semantic task progress without runtime topology jargon', () => {
    renderPlane(projection());
    const overview = screen.getByRole('region', { name: '共同目标与工作总进度' });
    expect(overview).toHaveTextContent('共同目标');
    expect(overview).toHaveTextContent('任务完成');
    expect(overview).toHaveTextContent('当前任务');
    expect(overview).not.toHaveTextContent(/Dispatch|执行批次/);
  });

  it('keeps the internal final report out of peer-visible work counts', () => {
    const state = projection();
    state.tasksById['task-report'] = {
      ...state.tasksById['task-a']!,
      taskId: 'task-report',
      taskKind: 'report',
      currentOwnerParticipantId: 'researcher',
      objective: '整理最终答复',
      expectedOutput: '唯一最终答复',
      state: 'completed',
    };

    renderPlane(state);

    const controlPlane = screen.getByRole('region', { name: '协作任务进展' });
    const overview = within(controlPlane).getByRole('region', { name: '共同目标与工作总进度' });
    expect(controlPlane).toHaveTextContent('1 个共同目标 · 1 项工作');
    expect(overview).toHaveTextContent('0 / 1 已完成');
    expect(overview).toHaveTextContent('1 项正在做 · 0 项等待');
    expect(overview).not.toHaveTextContent('1 / 2 已完成');
  });
});


function renderPlane(
  state: RoomKernelProjection,
  commandTransport?: RoomKernelCommandTransport,
  panicEnabled = false,
  participantProgress: RoomParticipantPublicProgressProjection[] = [],
  subagentsByTaskId: Record<string, RoomTaskSubagentRun[]> = {},
) {
  return render(<RoomKernelControlPlane
    projection={state}
    budgetsByRootId={{
      'root-a': { maxDispatches: 8, usedDispatches: 3, maxTokens: 32_000, usedTokens: 12_000, maxWallTimeMs: 300_000, elapsedMs: 80_000 },
      'root-b': { maxDispatches: 4, usedDispatches: 1, maxTokens: 16_000, usedTokens: 2_000, maxWallTimeMs: 180_000, elapsedMs: 20_000 },
    }}
    contextReceiptsByRootId={{ 'root-a': { revision: 'context-17', status: 'sealed', contentHash: `sha256:${'a'.repeat(64)}` } }}
    capabilityReceiptsByRootId={{ 'root-a': { revision: 'capability-9', status: 'sealed', contentHash: `sha256:${'b'.repeat(64)}` } }}
    participantLabels={{ researcher: '研究员', reviewer: '审查员' }}
    participantRoles={{ researcher: 'coordinator', reviewer: 'reviewer' }}
    commandTransport={commandTransport}
    panicEnabled={panicEnabled}
    participantProgress={participantProgress}
    subagentsByTaskId={subagentsByTaskId}
  />);
}

function projection(): RoomKernelProjection {
  const state = createRoomKernelProjection('room-a');
  state.lastSequence = 12;
  state.rootsById['root-a'] = root('root-a', 3, 'researcher', 'running', 12);
  state.tasksById['task-a'] = {
    schemaVersion: 'wisdom-weasel.room-task.v3', taskId: 'task-a', rootId: 'root-a', parentTaskId: null,
    taskKind: 'work', currentOwnerParticipantId: 'reviewer', ownershipRevision: 1,
    ownershipReceiptId: 'receipt:ownership:1', objective: '核对索引证据', expectedOutput: '证据回执',
    requirementItemIds: ['requirement:1'], acceptanceCriterionIds: ['criterion:1'],
    contextEvidenceRefs: [], invitationId: null, reviewOfTaskIds: [],
    reviewAuthorParticipantIds: [], reviewState: 'not_required', revision: 1, state: 'active',
  };
  state.receiptsById['receipt:ownership:1'] = receipt({
    receiptId: 'receipt:ownership:1',
    details: {
      operation: 'task_owner_transfer', taskId: 'task-a',
      fromParticipantId: 'researcher', toParticipantId: 'reviewer', ownershipRevision: 1,
    },
    createdAtMs: 8,
  });
  state.postOrder.push('post-a');
  state.postsById['post-a'] = {
    schemaVersion: 'wisdom-weasel.room-post.v2', postId: 'post-a', roomId: 'room-a', rootId: 'root-a', generation: 3,
    authorActorRef: '研究员', kind: 'finding', visibility: 'room', content: '经过明确提交的研究发现',
    idempotencyKey: 'post-a', publicationSource: { kind: 'room_commit', ref: 'commit-a' }, createdAtMs: 1,
  };
  state.sessionsById['session-private-a'] = {
    sessionId: 'session-private-a',
    rootId: 'root-a',
    taskId: null,
    taskKind: null,
    workItemId: null,
    dispatchId: null,
    generation: 3,
    state: 'completed',
    updatedAtMs: 10,
  };
  return state;
}

function root(rootId: string, generation: number, facilitatorParticipantId: string, state: RootProjection['state'], updatedAtMs: number): RootProjection {
  return {
    schemaVersion: 'wisdom-weasel.room-root-execution.v3', rootId, roomId: 'room-a', generation, state,
    facilitatorParticipantId, reporterParticipantId: null, reporterSelectionReceiptId: null,
    requirementAnchorRef: `requirement:${rootId}`, createdByActorRef: 'user:1', terminalReceiptId: null,
    activeProfileRef: null, budgetPolicyRef: 'budget:default',
    independentReviewRequired: false, createdAtMs: 1, isFinal: false, updatedAtMs,
  };
}

function receipt(overrides: Partial<RoomKernelReceiptV1>): RoomKernelReceiptV1 {
  return {
    schemaVersion: 'wisdom-weasel.room-kernel-receipt.v1', receiptId: 'receipt-a', rootId: 'root-a', commandId: 'command-a',
    receiptKind: 'accepted', status: 'applied', generation: 3, details: {}, createdAtMs: 4, ...overrides,
  };
}
