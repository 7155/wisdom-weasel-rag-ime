import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  previewRoomKernelSnapshot,
  previewRoomSnapshot,
  previewRoomTaskSubagentRuns,
} from '@/app/preview-room-data';
import {
  applyRoomKernelSnapshot,
  createRoomKernelProjection,
  type PrivateSessionProjection,
  type RootProjection,
} from '@/contracts/room-kernel-reducer';
import type { Todo } from '@/contracts/generated/agent-workflow-state.v1';
import type { RoomDispatchEnvelopeV2 } from '@/contracts/generated/room-dispatch-envelope.v2';
import type { RoomTaskV3 } from '@/contracts/generated/room-task.v3';
import type { RoomWorkItem } from '../room-types';
import { parseSnapshot } from './RoomKernelLivePanel';
import { RoomTaskFlowGraph, RoomTaskWorkList } from './RoomTaskFlowGraph';

describe('RoomTaskFlowGraph dependency proof', () => {
  afterEach(cleanup);

  it('keeps parallel implementation ahead of integration and independent review without exposing protocol IDs', () => {
    const roomId = 'room-preview';
    const roomSnapshot = previewRoomSnapshot(roomId);
    const kernelSnapshot = parseSnapshot(previewRoomKernelSnapshot(roomId), roomId);
    const projection = applyRoomKernelSnapshot(
      createRoomKernelProjection(roomId),
      kernelSnapshot,
    );
    const root = Object.values(projection.rootsById)[0]!;
    const tasks = Object.values(projection.tasksById)
      .filter((task) => task.rootId === root.rootId);
    const dispatches = Object.values(projection.dispatchesById)
      .filter((dispatch) => dispatch.rootId === root.rootId);
    const participantLabels = Object.fromEntries(
      roomSnapshot.room.participants.map((participant) => [participant.id, participant.displayName]),
    );
    expect(roomSnapshot.room.participants.find((participant) => (
      participant.id === 'participant-future'
    ))).toMatchObject({
      collaborationRole: 'reviewer',
      sessionId: 'session-room-future',
    });

    const interfaceTask = tasks.find((task) => task.objective === '实现 Room 任务图交互')!;
    const dataTask = tasks.find((task) => task.objective === '接通 Room 依赖数据')!;
    const integrationTask = tasks.find((task) => task.objective === '整合任务图与依赖数据')!;
    const reviewTask = tasks.find((task) => task.objective === '独立复核整合版本')!;
    const interfaceDispatch = dispatches.find((dispatch) => dispatch.taskId === interfaceTask.taskId)!;
    const dataDispatch = dispatches.find((dispatch) => dispatch.taskId === dataTask.taskId)!;
    const integrationDispatch = dispatches.find((dispatch) => dispatch.taskId === integrationTask.taskId)!;
    const reviewDispatch = dispatches.find((dispatch) => dispatch.taskId === reviewTask.taskId)!;
    const subagentsByTaskId = previewRoomTaskSubagentRuns(roomId);
    const interfaceSubagent = subagentsByTaskId[interfaceTask.taskId]![0]!;
    expect([interfaceTask.state, dataTask.state]).toEqual(['completed', 'completed']);
    expect(integrationTask).toMatchObject({ reviewState: 'required', state: 'active' });
    expect(Object.keys(subagentsByTaskId)).toEqual([interfaceTask.taskId]);
    expect(interfaceSubagent).toMatchObject({
      state: 'completed',
      task: '核对任务图的可访问性与依赖表达',
      templateId: 'researcher',
      ordinal: 0,
      budget: { maxTurns: 4, maxToolCalls: 8 },
      usage: { turnCount: 2, toolCount: 3 },
      resultSummary: '已确认并行分支、依赖顺序和可访问名称均清晰可读',
      error: '',
    });
    expect(interfaceSubagent).not.toHaveProperty('id');
    expect(interfaceSubagent).not.toHaveProperty('childSessionId');
    expect(interfaceSubagent).not.toHaveProperty('result');

    expect([interfaceDispatch, dataDispatch].map((dispatch) => ({
      alignmentOrdinal: dispatch.alignmentOrdinal,
      dependsOnDispatchIds: dispatch.dependsOnDispatchIds,
      state: dispatch.state,
    }))).toEqual([
      { alignmentOrdinal: 1, dependsOnDispatchIds: [], state: 'committed' },
      { alignmentOrdinal: 1, dependsOnDispatchIds: [], state: 'committed' },
    ]);
    expect(integrationDispatch.dependsOnDispatchIds).toEqual([
      interfaceDispatch.dispatchId,
      dataDispatch.dispatchId,
    ]);
    expect(reviewDispatch.dependsOnDispatchIds).toEqual([integrationDispatch.dispatchId]);
    expect(reviewTask).toMatchObject({
      parentTaskId: integrationTask.taskId,
      reviewOfTaskIds: [integrationTask.taskId],
      reviewTargetRevision: `sha256:${'e'.repeat(64)}`,
      reviewState: 'required',
      state: 'waiting',
    });
    expect(reviewTask.currentOwnerParticipantId).not.toBe(integrationTask.currentOwnerParticipantId);

    render(<>
      <RoomTaskFlowGraph
        dispatches={dispatches}
        finalPostCount={0}
        goal={roomSnapshot.room.workItems[0]!.objective}
        participantLabels={participantLabels}
        participantProgress={[]}
        posts={Object.values(projection.postsById)}
        root={root}
        tasks={tasks}
        subagentsByTaskId={subagentsByTaskId}
      />
      <RoomTaskWorkList
        activities={[
          {
            id: 'public-tool-a',
            turnId: root.rootId,
            participantId: interfaceTask.currentOwnerParticipantId,
            sourceSessionId: 'public-session',
            kind: 'participant_activity',
            status: 'completed',
            summary: '已核对组件可访问性',
            payload: {
              dispatchId: interfaceDispatch.dispatchId,
              sourceEventType: 'tool_finished',
              toolName: 'edit',
              arguments: { path: 'src/RoomFlowGraph.tsx' },
              result: {
                summary: '检查结果可公开复核',
                fileName: 'RoomFlowGraph.tsx',
                additions: 2,
                deletions: 1,
              },
              agentBlocks: [{
                schemaVersion: 'rag-ime.agent-block.v1',
                id: 'tool-artifact:diff:task-graph',
                type: 'diff',
                status: 'completed',
                presentationKind: 'diff',
                data: {
                  fileName: 'RoomFlowGraph.tsx',
                  diff: [
                    '@@ -1,2 +1,3 @@',
                    '-const oldGraph = true;',
                    '+const currentGraph = true;',
                    '+const todoVisible = true;',
                  ].join('\n'),
                  additions: 2,
                  deletions: 1,
                },
              }],
            },
            createdAtMs: 10,
            updatedAtMs: 11,
          },
          {
            id: 'public-tool-protocol-envelope',
            turnId: root.rootId,
            participantId: dataTask.currentOwnerParticipantId,
            sourceSessionId: 'public-session',
            kind: 'participant_activity',
            status: 'completed',
            summary: 'dispatchId: dispatch-private-card',
            payload: {
              dispatchId: dataDispatch.dispatchId,
              sourceEventType: 'tool_finished',
              toolName: 'check',
              result: JSON.stringify({
                rootId: 'root-private-card',
                receiptId: 'receipt-private-card',
              }),
            },
            createdAtMs: 12,
            updatedAtMs: 13,
          },
        ]}
        dispatches={dispatches}
        participantLabels={participantLabels}
        participantProgress={[]}
        posts={Object.values(projection.postsById)}
        root={root}
        tasks={tasks}
        subagentsByTaskId={subagentsByTaskId}
      />
    </>);

    const graph = screen.getByRole('region', { name: '任务依赖图' });
    expect(graph.querySelectorAll('.room-task-flow__task-node')).toHaveLength(4);
    expect(graph.querySelectorAll('.room-task-flow__edges g')).toHaveLength(6);
    expect(graph).toHaveTextContent('4 项 · 2 已完成 · 1 执行中 · 1 等待中');
    expect(graph).toHaveTextContent('并行实现 Room 任务图，整合后交给独立伙伴复核');
    expect(graph).toHaveTextContent('接续 / 汇总');
    expect(graph).toHaveTextContent('复核');

    const dataNode = within(graph).getByRole('article', { name: /接通 Room 依赖数据/ });
    const interfaceNode = within(graph).getByRole('article', { name: /实现 Room 任务图交互/ });
    const integrationNode = within(graph).getByRole('article', { name: /整合任务图与依赖数据/ });
    const reviewNode = within(graph).getByRole('article', { name: /独立复核整合版本/ });

    expect((dataNode as HTMLElement).style.gridColumn).toBe('2');
    expect((interfaceNode as HTMLElement).style.gridColumn).toBe('2');
    expect((dataNode as HTMLElement).style.gridRow).toBe('1');
    expect((interfaceNode as HTMLElement).style.gridRow).toBe('2');
    expect(dataNode).toHaveAttribute('title', expect.stringContaining('无前置任务，可并行'));
    expect(interfaceNode).toHaveAttribute('title', expect.stringContaining('无前置任务，可并行'));
    expect(integrationNode).toHaveAttribute('data-task-stage', '接续 / 整合任务');
    expect((integrationNode as HTMLElement).style.gridColumn).toBe('3');
    expect(reviewNode).toHaveAttribute('data-task-stage', '复核任务');
    expect((reviewNode as HTMLElement).style.gridColumn).toBe('4');
    expect(reviewNode).toHaveAttribute('title', expect.stringContaining('等待 1 项真实前置任务'));
    expect(reviewNode).toHaveTextContent('负责人澄·远');
    expect(reviewNode).toHaveTextContent('等待前置工作');
    expect(dataNode).toHaveTextContent('已交付');
    expect(interfaceNode).toHaveTextContent('已交付');
    expect(integrationNode).toHaveTextContent('正在做');
    expect(reviewNode).toHaveTextContent('下一步等待 1 项前置任务完成');
    expect(graph).not.toHaveTextContent(/验证状态|临时协作者/);

    const workList = screen.getByRole('region', { name: '每项工作的详细进展' });
    const interfaceCard = [...workList.querySelectorAll('.room-task-work-card')].find((card) => (
      card.textContent?.includes('实现 Room 任务图交互')
    ))!;
    expect(interfaceCard).not.toHaveAttribute('open');
    expect(interfaceCard.querySelector('summary')).toHaveTextContent('澄·今');
    expect(interfaceCard.querySelector('summary')).toHaveTextContent('完成情况');
    fireEvent.click(interfaceCard.querySelector('summary')!);
    expect(interfaceCard).toHaveAttribute('open');
    expect(interfaceCard).toHaveTextContent('公开活动1 条，按发生时间排列');
    expect(interfaceCard).toHaveTextContent('已核对组件可访问性');
    fireEvent.click(within(interfaceCard as HTMLElement).getByText('查看工具返回'));
    expect(interfaceCard).toHaveTextContent('检查结果可公开复核');
    expect(within(interfaceCard as HTMLElement).getByLabelText('文件变更')).toHaveTextContent(
      'RoomFlowGraph.tsx',
    );
    expect(interfaceCard).toHaveTextContent('const currentGraph = true;');
    const nestedRun = within(interfaceCard as HTMLElement).getByRole('region', { name: '负责人调用了 1 个临时协作者' });
    expect(nestedRun).toHaveTextContent('临时协作者');
    expect(nestedRun).toHaveTextContent('研究助手 1');
    expect(nestedRun).toHaveTextContent('核对任务图的可访问性与依赖表达');
    expect(nestedRun).toHaveTextContent('2 / 4 回合 · 3 / 8 次工具');
    expect(nestedRun).toHaveTextContent('已返回');
    expect(nestedRun).toHaveTextContent('已确认并行分支、依赖顺序和可访问名称均清晰可读');
    expect(nestedRun.querySelector('time')).toHaveAttribute(
      'datetime',
      new Date(interfaceSubagent.completedAtMs!).toISOString(),
    );

    const userFacingLabels = [
      `${graph.textContent ?? ''} ${workList.textContent ?? ''}`,
      ...Array.from(document.querySelectorAll('[aria-label], [title]')).flatMap((element) => [
        element.getAttribute('aria-label') ?? '',
        element.getAttribute('title') ?? '',
      ]),
    ].join(' ');
    expect(userFacingLabels).not.toMatch(
      /room-preview|root-preview|task-(?:interface|data|integration|review)|dispatch-(?:interface|data|integration|review)|receipt-owner-review|participant-(?:present|firstlight|future)|subagent-run|child-session|session-room-|sha256:[a-f0-9]{64}|researcher|Kernel|Root|Dispatch|Task|Receipt|Session|\bAC\b/,
    );
    expect(userFacingLabels).not.toMatch(/dispatch-private-card|root-private-card|receipt-private-card|\{"rootId"/);
    expect(graph.querySelector('.room-task-flow__dispatch-node')).not.toBeInTheDocument();
  });

  it('keeps a responsibility child parallel until a real dependency is declared', () => {
    const parent = workspaceTask({
      taskId: 'task-parent',
      objective: '实现命令入口',
      currentOwnerParticipantId: 'participant-owner',
      state: 'active',
    });
    const child = workspaceTask({
      taskId: 'task-child',
      parentTaskId: parent.taskId,
      objective: '调查现有链接规则',
      currentOwnerParticipantId: 'participant-researcher',
      state: 'active',
    });

    render(<RoomTaskFlowGraph
      dispatches={[]}
      finalPostCount={0}
      goal="完成链接检查能力"
      participantLabels={{
        'participant-owner': '澄·远',
        'participant-researcher': '澄·瞬',
      }}
      participantProgress={[]}
      posts={[]}
      root={workspaceRoot()}
      tasks={[parent, child]}
    />);

    const graph = screen.getByRole('region', { name: '任务依赖图' });
    const parentNode = within(graph).getByRole('article', { name: /实现命令入口/ });
    const childNode = within(graph).getByRole('article', { name: /调查现有链接规则/ });
    const canvas = graph.querySelector<HTMLElement>('.room-task-flow__canvas')!;
    expect((parentNode as HTMLElement).style.gridColumn).toBe('2');
    expect((childNode as HTMLElement).style.gridColumn).toBe('2');
    expect(canvas.style.getPropertyValue('--room-task-flow-height')).toBe('440px');
    expect(childNode).toHaveAttribute('data-task-stage', '任务目标');
    expect(childNode).toHaveAttribute('title', expect.stringContaining('无前置任务，可并行'));
    expect(graph).not.toHaveTextContent('接续 / 汇总');
  });

  it('does not describe a blocked committed task as waiting for acceptance', () => {
    const view = render(<RoomTaskWorkList
      activities={[]}
      dispatches={[authorityDispatch()]}
      participantLabels={{ 'participant-owner': '澄·今' }}
      participantProgress={[]}
      posts={[]}
      root={workspaceRoot()}
      tasks={[workspaceTask({ state: 'blocked' })]}
    />);

    const card = view.container.querySelector<HTMLElement>('.room-task-work-card')!;
    expect(card).toHaveTextContent('未通过验收');
    expect(card).not.toHaveTextContent('结果已回传，等待验收');
  });

  it('projects the internal report task only through the single result stage', () => {
    const workTask = workspaceTask({
      taskId: 'task-implementation',
      objective: '实现终端界面',
      workspaceLifecycleState: 'integrated',
      workspaceCleanupState: 'cleaned',
    });
    const reportTask = {
      ...workspaceTask({
        taskId: 'task-report',
        objective: '整理并发布最终总结',
        workspacePolicy: 'read_only',
        workspaceLifecycleState: 'integrated',
        workspaceCleanupState: 'cleaned',
      }),
      taskKind: 'report',
      workItemId: 'work-item-implementation',
    } as unknown as RoomTaskV3;

    render(<>
      <RoomTaskFlowGraph
        dispatches={[]}
        finalPostCount={1}
        goal="完成可运行终端界面"
        participantLabels={{ 'participant-owner': '澄·今' }}
        participantProgress={[]}
        posts={[]}
        root={workspaceRoot()}
        tasks={[workTask, reportTask]}
      />
      <RoomTaskWorkList
        activities={[]}
        dispatches={[]}
        participantLabels={{ 'participant-owner': '澄·今' }}
        participantProgress={[]}
        posts={[]}
        root={workspaceRoot()}
        tasks={[workTask, reportTask]}
      />
    </>);

    const graph = screen.getByRole('region', { name: '任务依赖图' });
    expect(graph.querySelectorAll('.room-task-flow__task-node')).toHaveLength(1);
    expect(graph.querySelectorAll('[data-flow-stage="result"]')).toHaveLength(1);
    expect(graph).toHaveTextContent('1 项');
    expect(graph).not.toHaveTextContent('整理并发布最终总结');
    const workList = screen.getByRole('region', { name: '每项工作的详细进展' });
    expect(workList.querySelectorAll('.room-task-work-card')).toHaveLength(1);
    expect(workList).not.toHaveTextContent('整理并发布最终总结');
  });
});

describe('RoomTaskWorkList workspace lifecycle projection', () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('keeps business semantics in the expanded card and raw workspace evidence in a collapsed audit disclosure', () => {
    const task = workspaceTask({
      workspaceLifecycleState: 'cleaned',
      workspaceCleanupState: 'cleaned',
      workspaceIntegrationState: 'applied',
    });
    render(<>
      <RoomTaskFlowGraph
        dispatches={[]}
        finalPostCount={0}
        goal="完成隔离工作区交付"
        participantLabels={{ 'participant-owner': '澄·今' }}
        participantProgress={[]}
        posts={[]}
        root={workspaceRoot()}
        tasks={[task]}
      />
      {workspaceWorkList(task)}
    </>);

    const graph = screen.getByRole('region', { name: '任务依赖图' });
    expect(graph.querySelectorAll('.room-task-flow__task-node')).toHaveLength(1);
    expect(graph.querySelector('.room-task-workspace')).not.toBeInTheDocument();

    const card = document.querySelector<HTMLDetailsElement>('.room-task-work-card')!;
    expect(card).not.toHaveAttribute('open');
    expect(card.querySelector('summary')).not.toHaveTextContent('需要处理');
    expect(card.querySelector('summary')).not.toHaveTextContent('/private/room-worker');
    fireEvent.click(card.querySelector('summary')!);

    const business = card.querySelector('.room-task-workspace__business')!;
    expect(business).toHaveTextContent('隔离工作区已绑定独立可写工作区');
    expect(business).toHaveTextContent('负责人和责任澄·今 · 在自己的工作区完成并交回结果');
    expect(business).toHaveTextContent('共同基线已从共同基线准备；具体位置与版本留在审计详情');
    expect(business).toHaveTextContent('交付状态结果已交回协调伙伴');
    expect(business).toHaveTextContent('整合状态已纳入共同结果');
    expect(business).toHaveTextContent('收尾状态工作区已安全清理');
    expect(business).not.toHaveTextContent('/private/room-worker');
    expect(business).not.toHaveTextContent('git:base-private');
    expect(business).not.toHaveTextContent('a'.repeat(64));

    const audit = card.querySelector<HTMLDetailsElement>('.room-task-workspace__audit')!;
    expect(audit).not.toHaveAttribute('open');
    expect(audit.querySelector('summary')).toHaveTextContent('审计详情路径、校验值与内部关联');
    expect(audit.querySelector('summary')).not.toHaveTextContent('/private/room-worker');
    expect(audit).toHaveTextContent('负责人工作位置/private/room-worker');
    expect(audit).toHaveTextContent('共同基线版本git:base-private');
    expect(audit).toHaveTextContent(`开始时快照校验${'a'.repeat(64)}`);
    expect(audit).toHaveTextContent('工作区绑定记录workspace-binding-private');
  });

  it('shows a fixed authoritative update time and advances only the client elapsed seconds', () => {
    vi.useFakeTimers();
    vi.setSystemTime(10_000);
    const task = workspaceTask({ workspaceLifecycleState: 'work_started' });
    const view = render(workspaceWorkList(task, { [task.taskId]: 7_000 }));
    const card = view.container.querySelector<HTMLDetailsElement>('.room-task-work-card')!;
    fireEvent.click(card.querySelector('summary')!);
    const workspace = card.querySelector('.room-task-workspace')!;
    const timestamp = workspace.querySelector('time')!;
    const absolute = timestamp.textContent;
    expect(timestamp).toHaveAttribute('datetime', new Date(7_000).toISOString());
    expect(workspace).toHaveTextContent(/最近更新 .* · 3 秒前/);

    act(() => vi.advanceTimersByTime(2_000));

    expect(timestamp).toHaveTextContent(absolute ?? '');
    expect(workspace).toHaveTextContent(/最近更新 .* · 5 秒前/);
    view.unmount();

    const missing = render(workspaceWorkList(task));
    fireEvent.click(missing.container.querySelector('.room-task-work-card > summary')!);
    expect(missing.container.querySelector('.room-task-workspace')).toHaveTextContent(
      '更新时间未上报',
    );
  });

  it.each([
    {
      name: 'retained without delivery evidence',
      overrides: {
        workspaceLifecycleState: 'retained' as const,
        workspaceCleanupState: 'retained' as const,
        ...withoutWorkspaceDelivery(),
      },
      attention: false,
      lifecycle: '工作区已保留',
      delivery: '结果是否完整交付仍待核对',
    },
    {
      name: 'integration conflict',
      overrides: {
        workspaceLifecycleState: 'conflict' as const,
        workspaceCleanupState: 'retained' as const,
        ...withoutWorkspaceDelivery(),
      },
      attention: true,
      lifecycle: '整合发生冲突，需要处理',
      delivery: '整合发生冲突，交付状态待核对',
    },
    {
      name: 'orphaned workspace',
      overrides: {
        workspaceLifecycleState: 'orphaned' as const,
        workspaceCleanupState: 'retained' as const,
        ...withoutWorkspaceDelivery(),
      },
      attention: true,
      lifecycle: '工作区失去负责人，需要重新接管',
      delivery: '交付归属需要重新确认',
    },
    {
      name: 'explicit attention on a materialized workspace',
      overrides: {
        workspaceLifecycleState: 'materialized' as const,
        workspaceCleanupState: 'not_authorized' as const,
        workspaceAttentionRequired: true,
        ...withoutWorkspaceDelivery(),
      },
      attention: true,
      lifecycle: '工作区已准备',
      delivery: '尚在工作，未交回结果',
    },
    {
      name: 'cancelled workspace retained for inspection',
      overrides: {
        workspaceLifecycleState: 'cancelled' as const,
        workspaceCleanupState: 'retained' as const,
        workspaceAttentionRequired: false,
        ...withoutWorkspaceDelivery(),
      },
      attention: true,
      lifecycle: '工作区任务已停止',
      delivery: '结果尚未完整交付',
    },
    {
      name: 'abandoned workspace with completed cleanup',
      overrides: {
        workspaceLifecycleState: 'abandoned' as const,
        workspaceCleanupState: 'cleaned' as const,
        workspaceAttentionRequired: false,
        ...withoutWorkspaceDelivery(),
      },
      attention: false,
      lifecycle: '工作区已确认放弃',
      delivery: '已记录放弃，交付状态以留存记录为准',
    },
    {
      name: 'failed cleanup',
      overrides: {
        workspaceLifecycleState: 'cleanup_failed' as const,
        workspaceCleanupState: 'failed' as const,
        workspaceAttentionRequired: false,
        ...withoutWorkspaceDelivery(),
      },
      attention: true,
      lifecycle: '工作区清理失败',
      delivery: '交付状态尚未上报',
    },
  ])('renders $name from canonical task fields', ({
    attention,
    delivery,
    lifecycle,
    overrides,
  }) => {
    const task = workspaceTask(overrides);
    const view = render(workspaceWorkList(task));
    const card = view.container.querySelector<HTMLDetailsElement>('.room-task-work-card')!;
    const summary = card.querySelector('summary')!;
    if (attention) expect(card).toHaveAttribute('data-workspace-attention', 'true');
    else expect(card).not.toHaveAttribute('data-workspace-attention');
    if (attention) expect(summary).toHaveTextContent('需要处理');
    else expect(summary).not.toHaveTextContent('需要处理');
    fireEvent.click(summary);
    expect(card).toHaveTextContent(lifecycle);
    expect(card).toHaveTextContent(delivery);
    expect(Boolean(card.querySelector('[role="alert"]'))).toBe(attention);
  });
});

  describe('RoomTaskWorkList participant authority projection', () => {
  afterEach(cleanup);

  it('shows one participant Todo and receipted delivery in the Task card without leaking raw refs into the main result', () => {
    const manifestSha256 = '9'.repeat(64);
    const task = workspaceTask({
      workItemId: 'work-item-owner',
      resultSummary: '已完成权威双面板并通过前端验证',
      resultKind: 'complete',
      resultAtMs: 6_000,
      verificationCount: 1,
      verifications: [{ label: '前端聚焦测试', result: 'pass', source: 'quality_gate' }],
      artifactRefs: ['artifact:task-result-private'],
      residualRisks: ['尚未完成真实前台输入验收'],
      workspaceDelivery: {
        schemaVersion: 'wisdom-weasel.room-workspace-delivery.v1',
        ownerParticipantId: 'participant-owner',
        ownerSessionId: 'session-owner',
        workItemId: 'work-item-owner',
        taskId: 'task-workspace',
        deliveryRevision: 'delivery:private-revision',
        baseCommit: 'git:base-private',
        workspaceSnapshotSha256: '7'.repeat(64),
        patchSha256: '8'.repeat(64),
        deliveredAtMs: 5_000,
        resultSummary: '工作区交付已生成',
        manifestSha256,
        files: [{
          path: 'control-center-web/src/RoomTaskCard.tsx',
          additions: 42,
          deletions: 7,
          binary: false,
          generated: false,
          redacted: false,
        }],
        totals: {
          fileCount: 1,
          additions: 42,
          deletions: 7,
          binaryFiles: 0,
          generatedFiles: 0,
          redactedFiles: 0,
        },
        artifactRefs: ['artifact:delivery-private'],
        verificationCount: 1,
        verifications: [{ label: '前端聚焦测试', result: 'pass', source: 'quality_gate' }],
        verificationRefs: ['verification-ref-private'],
        residualRisks: ['尚未完成真实前台输入验收'],
      },
    });
    const dispatch = authorityDispatch();
    const todo = authorityTodo();
    const session: PrivateSessionProjection = {
      sessionId: 'session-owner',
      participantId: 'participant-owner',
      rootId: task.rootId,
      taskId: task.taskId,
      taskKind: task.taskKind,
      workItemId: 'work-item-owner',
      dispatchId: dispatch.dispatchId,
      generation: 1,
      state: 'completed',
      updatedAtMs: 5_500,
      todo,
    };
    const workItem: RoomWorkItem = {
      id: 'work-item-owner',
      roomId: 'room-workspace',
      topicId: 'topic-workspace',
      rootTurnId: 'turn-workspace',
      rootWorkId: 'work-item-owner',
      parentWorkId: '',
      objective: task.objective,
      expectedOutput: task.expectedOutput,
      acceptanceCriteria: ['Todo 和交付来自权威投影'],
      accountableParticipantId: 'participant-owner',
      currentOwnerParticipantId: 'participant-owner',
      offeredToParticipantId: 'participant-owner',
      createdByParticipantId: 'participant-owner',
      clientMessageId: 'client-message-private',
      state: 'done',
      depth: 0,
      revision: 1,
      resultSummary: '旧 WorkItem 摘要不应覆盖最新 Task 结果',
      artifactRefs: ['artifact:work-item-private'],
      evidenceRefs: ['work-item-evidence-private'],
      blocker: {},
      acceptedTurnId: 'turn-workspace',
      createdAtMs: 1_000,
      updatedAtMs: 5_000,
      completedAtMs: 5_000,
    };

    render(<RoomTaskWorkList
      activities={[]}
      dispatches={[dispatch]}
      participantLabels={{ 'participant-owner': '澄·今' }}
      participantProgress={[]}
      posts={[]}
      root={workspaceRoot()}
      sessionsById={{ 'session-owner': session }}
      tasks={[task]}
      workItems={[workItem]}
    />);

    const card = document.querySelector<HTMLDetailsElement>('.room-task-work-card')!;
    expect(card.querySelector('summary')).toHaveTextContent('Todo 1/2 · 当前：完成交付清单');
    fireEvent.click(card.querySelector('summary')!);
    const todoRegion = within(card).getByRole('region', { name: '澄·今 的 Todo' });
    expect(todoRegion).toHaveTextContent('实现权威 Todo 投影');
    expect(todoRegion).toHaveTextContent('完成交付清单');
    expect(todoRegion).toHaveTextContent('1 / 2 已收束');
    expect(card.querySelector('.room-task-work-card__body')?.lastElementChild).toBe(todoRegion);

    const deliveryRegion = within(card).getByRole('region', { name: '澄·今 的交付结果' });
    expect(deliveryRegion.querySelector('.room-task-delivery__summary')).toHaveTextContent(
      '已完成权威双面板并通过前端验证',
    );
    expect(deliveryRegion.querySelector('.room-task-delivery__summary')).not.toHaveTextContent(
      '旧 WorkItem 摘要不应覆盖最新 Task 结果',
    );
    expect(deliveryRegion.querySelector('.room-task-delivery__files')).toHaveTextContent(
      'control-center-web/src/RoomTaskCard.tsx',
    );
    expect(deliveryRegion.querySelector('.room-task-delivery__files')).toHaveTextContent('+42 −7');
    expect(deliveryRegion.querySelector('.room-task-delivery__verification')).toHaveTextContent(
      '前端聚焦测试已通过',
    );

    const mainResult = [
      deliveryRegion.querySelector('.room-task-delivery__summary')?.textContent,
      deliveryRegion.querySelector('.room-task-delivery__files')?.textContent,
      deliveryRegion.querySelector('.room-task-delivery__verification')?.textContent,
    ].join(' ');
    expect(mainResult).not.toContain(manifestSha256);
    expect(mainResult).not.toContain('verification-ref-private');
    expect(mainResult).not.toContain('artifact:delivery-private');

    const audit = deliveryRegion.querySelector<HTMLDetailsElement>('.room-task-delivery__receipt')!;
    expect(audit).not.toHaveAttribute('open');
    expect(audit).toHaveTextContent(manifestSha256);
    expect(audit).toHaveTextContent('verification-ref-private');
    expect(audit).toHaveTextContent('artifact:delivery-private');
    expect(deliveryRegion).toHaveTextContent('尚未完成真实前台输入验收');
  });

  it('replaces a generic progress placeholder with the concrete task objective', () => {
    render(<RoomTaskWorkList
      activities={[{
        id: 'activity:summary',
        turnId: 'root-workspace',
        participantId: 'participant-owner',
        sourceSessionId: 'session-owner',
        kind: 'reasoning',
        status: 'running',
        summary: '当前任务推进有新进展',
        payload: {
          dispatchId: 'dispatch-owner',
          sourceEventType: 'reasoning_summary',
        },
        createdAtMs: 5,
      }]}
      dispatches={[authorityDispatch()]}
      participantLabels={{ 'participant-owner': '澄·今' }}
      participantProgress={[]}
      posts={[]}
      root={workspaceRoot()}
      tasks={[workspaceTask({ objective: '实现 Markdown 链接检查命令', state: 'active' })]}
    />);

    expect(screen.queryByText('当前任务推进有新进展')).not.toBeInTheDocument();
    expect(screen.getAllByText('正在推进：实现 Markdown 链接检查命令').length).toBeGreaterThan(0);
  });
});

function workspaceWorkList(
  task: RoomTaskV3,
  taskUpdatedAtMsById: Record<string, number> = {},
) {
  return <RoomTaskWorkList
    activities={[]}
    dispatches={[]}
    participantLabels={{ 'participant-owner': '澄·今' }}
    participantProgress={[]}
    posts={[]}
    root={workspaceRoot()}
    taskUpdatedAtMsById={taskUpdatedAtMsById}
    tasks={[task]}
  />;
}

function authorityDispatch(): RoomDispatchEnvelopeV2 {
  return {
    schemaVersion: 'wisdom-weasel.room-dispatch-envelope.v2',
    dispatchId: 'dispatch-owner',
    rootId: 'root-workspace',
    taskId: 'task-workspace',
    parentDispatchId: null,
    generation: 1,
    hopCount: 1,
    depth: 1,
    budgetCost: 1,
    targetSessionId: 'session-owner',
    targetParticipantId: 'participant-owner',
    triggerId: 'trigger-owner',
    intentKind: 'execute',
    idempotencyKey: 'dispatch-owner',
    attempt: 1,
    capabilityEpoch: 1,
    runtimeProfileRevision: 'profile-owner',
    alignmentOrdinal: 1,
    dependsOnDispatchIds: [],
    attachmentIds: [],
    state: 'committed',
  };
}

function authorityTodo(): Todo {
  return {
    schemaVersion: 'rag-ime.agent-todo.v1',
    id: 'todo-owner',
    sessionId: 'session-owner',
    revision: 2,
    actor: 'agent-runtime',
    updatedAtMs: 5_500,
    roomLineage: {
      schemaVersion: 'wisdom-weasel.room-todo-lineage.v1',
      roomId: 'room-workspace',
      rootId: 'root-workspace',
      taskId: 'task-workspace',
      workItemId: 'work-item-owner',
      dispatchId: 'dispatch-owner',
      sessionId: 'session-owner',
      participantId: 'participant-owner',
      generation: 1,
      taskRevision: 7,
      ownershipRevision: 1,
      workItemRevision: 1,
    },
    phases: [{
      name: '交付',
      tasks: [
        { content: '实现权威 Todo 投影', status: 'completed' },
        { content: '完成交付清单', status: 'in_progress' },
      ],
    }],
    counts: {
      total: 2,
      pending: 0,
      inProgress: 1,
      blocked: 0,
      completed: 1,
      abandoned: 0,
    },
  };
}

function withoutWorkspaceDelivery() {
  return {
    workspaceDeliveryRevision: undefined,
    workspaceDeliveryHead: undefined,
    workspaceDeliverySnapshotSha256: undefined,
    workspaceIntegrationPatchSha256: undefined,
    workspaceIntegratedRevision: undefined,
    workspaceIntegratedSnapshotSha256: undefined,
    workspaceIntegrationState: 'pending' as const,
    workspaceIntegrationRef: null,
  };
}

function workspaceTask(overrides: Partial<RoomTaskV3> = {}): RoomTaskV3 {
  return {
    schemaVersion: 'wisdom-weasel.room-task.v3',
    taskId: 'task-workspace',
    rootId: 'root-workspace',
    parentTaskId: null,
    taskKind: 'work',
    currentOwnerParticipantId: 'participant-owner',
    ownershipRevision: 1,
    ownershipReceiptId: null,
    objective: '完成隔离工作区交付',
    expectedOutput: '交回可整合结果',
    requirementItemIds: [],
    acceptanceCriterionIds: [],
    contextEvidenceRefs: [],
    invitationId: null,
    reviewOfTaskIds: [],
    reviewAuthorParticipantIds: [],
    reviewState: 'not_required',
    workspacePolicy: 'isolated_writable',
    workspaceRoot: '/private/room-worker',
    workspaceBaseRoot: '/private/shared-base',
    workspaceBaseCommit: 'git:base-private',
    workspaceSnapshotSha256: 'a'.repeat(64),
    workspaceBindingId: 'workspace-binding-private',
    workspaceRepositoryId: 'b'.repeat(64),
    workspaceLifecycleState: 'cleaned',
    workspaceCleanupState: 'cleaned',
    workspaceAttentionRequired: false,
    workspaceDeliveryRevision: `sha256:${'c'.repeat(64)}`,
    workspaceDeliveryHead: 'git:delivery-private',
    workspaceDeliverySnapshotSha256: 'd'.repeat(64),
    workspaceIntegrationPatchSha256: 'e'.repeat(64),
    workspaceIntegratedRevision: 'git:integrated-private',
    workspaceIntegratedSnapshotSha256: 'f'.repeat(64),
    workspaceIntegrationState: 'applied',
    workspaceIntegrationRef: 'integration-private',
    revision: 7,
    state: 'completed',
    ...overrides,
  };
}

function workspaceRoot(): RootProjection {
  return {
    schemaVersion: 'wisdom-weasel.room-root-execution.v3',
    rootId: 'root-workspace',
    roomId: 'room-workspace',
    generation: 1,
    state: 'running',
    facilitatorParticipantId: 'participant-owner',
    reporterParticipantId: null,
    reporterSelectionReceiptId: null,
    requirementAnchorRef: 'requirement-anchor',
    createdByActorRef: 'actor-owner',
    terminalReceiptId: null,
    activeProfileRef: null,
    budgetPolicyRef: 'budget-default',
    independentReviewRequired: false,
    isFinal: false,
    updatedAtMs: 1,
  };
}
