import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Todo } from '@/contracts/generated/agent-workflow-state.v1';
import type { RoomWorkItem } from '../room-types';
import {
  RoomTaskDeliveryDetails,
  RoomTaskTodoDetails,
  type RoomWorkspaceDeliveryProjection,
} from './RoomTaskAuthorityDetails';

describe('RoomTaskAuthorityDetails', () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('marks absent authority projections as unreported instead of inventing work', () => {
    render(<>
      <RoomTaskTodoDetails owner="澄·今" />
      <RoomTaskDeliveryDetails owner="澄·今" />
    </>);

    const todo = screen.getByRole('region', { name: '澄·今 的 Todo' });
    const delivery = screen.getByRole('region', { name: '澄·今 的交付结果' });
    expect(todo).toHaveAttribute('data-state', 'missing');
    expect(todo).toHaveTextContent('Todo 未上报');
    expect(todo).toHaveTextContent('这位伙伴尚未上报权威 Todo');
    expect(delivery).toHaveAttribute('data-state', 'missing');
    expect(delivery).toHaveTextContent('工作结果未提交');
    expect(delivery).toHaveTextContent('不会从本地文件状态猜测这位伙伴的贡献');
    expect(delivery).not.toHaveTextContent(/WorkItem|Receipt|收据/);
    expect(delivery).not.toHaveTextContent(/\.tsx|\+\d|−\d/);
  });

  it('renders the exact Session Todo with its statuses and authoritative update time', () => {
    vi.useFakeTimers();
    vi.setSystemTime(10_000);
    render(<RoomTaskTodoDetails owner="澄·今" todo={todoProjection()} />);

    const todo = screen.getByRole('region', { name: '澄·今 的 Todo' });
    expect(todo).toHaveAttribute('data-state', 'reported');
    expect(todo).toHaveTextContent('2 / 4 已收束');
    expect(todo).toHaveTextContent('实现2 / 4');
    expect(todo).toHaveTextContent('接入 Room Todo进行中');
    expect(todo).toHaveTextContent('补齐异常态等待后端字段已阻塞');
    expect(todo).toHaveTextContent('旧方案已放弃');
    expect(todo).toHaveTextContent('只读同步自这位伙伴的权威 Todo');
    expect(todo).toHaveTextContent('3 秒前');
    expect(todo.querySelector('time')).toHaveAttribute(
      'datetime',
      new Date(7_000).toISOString(),
    );
  });

  it('renders only the receipted delivery manifest and its exactly linked WorkItem result', () => {
    const delivery = deliveryProjection();
    render(<RoomTaskDeliveryDetails
      delivery={delivery}
      owner="澄·今"
      workItem={workItem({ id: delivery.workItemId, resultSummary: '工作成果已验收并交付' })}
    />);

    const result = screen.getByRole('region', { name: '澄·今 的交付结果' });
    expect(result).toHaveAttribute('data-state', 'reported');
    expect(result).toHaveTextContent('成果与代码交付已记录');
    expect(result).toHaveTextContent('工作成果已验收并交付');
    expect(result).not.toHaveTextContent('delivery fallback summary');
    const files = within(result).getByRole('region', { name: '交付文件' });
    expect(files).toHaveTextContent('3 个文件 · +14 −5 · 1 个二进制');
    expect(files).toHaveTextContent('src/Room.tsx+12 −3');
    expect(files).toHaveTextContent('dist/room.bin生成文件 · 二进制二进制');
    expect(files).toHaveTextContent('路径已隐藏+2 −2');
    const verification = within(result).getByRole('region', { name: '交付验证' });
    expect(verification).toHaveTextContent('已记录 2 项验证证据');
    expect(verification).toHaveTextContent('Room 任务页聚焦测试已通过');
    expect(verification).not.toHaveTextContent('vitest:RoomTaskAuthorityDetails');
    expect(result).toHaveTextContent('前台安装态尚未验证');
    const receipt = result.querySelector<HTMLDetailsElement>('.room-task-delivery__receipt')!;
    expect(receipt).not.toHaveAttribute('open');
    expect(receipt).toHaveTextContent('vitest:RoomTaskAuthorityDetails');
    expect(receipt).toHaveTextContent(delivery.deliveryRevision);
    expect(receipt).toHaveTextContent(delivery.manifestSha256);
    expect(receipt.querySelector('time')).toHaveAttribute(
      'datetime',
      new Date(delivery.deliveredAtMs).toISOString(),
    );
  });

  it('keeps a receipted role result visible when that role has no code delivery', () => {
    render(<RoomTaskDeliveryDetails
      owner="澄·远"
      roleResult={{
        resultSummary: '复核完成，没有发现阻断问题',
        resultKind: 'complete',
        resultAtMs: 20,
        verificationCount: 1,
        verifications: [{ label: '独立复核', result: 'pass', source: 'quality_gate' }],
        artifactRefs: [],
        residualRisks: [],
      }}
    />);

    const result = screen.getByRole('region', { name: '澄·远 的交付结果' });
    expect(result).toHaveAttribute('data-state', 'reported');
    expect(result).toHaveTextContent('工作成果已记录');
    expect(result).toHaveTextContent('复核完成，没有发现阻断问题');
    expect(result).toHaveTextContent('本角色无代码交付');
    expect(result).toHaveTextContent('这份角色成果不包含工作区代码交付');
    expect(result).not.toHaveTextContent('成果未上报');
  });

  it('does not borrow a result summary from a differently owned WorkItem', () => {
    render(<RoomTaskDeliveryDetails
      delivery={deliveryProjection()}
      owner="澄·今"
      workItem={workItem({ id: 'work-item:other', resultSummary: '别人的结果' })}
    />);

    const result = screen.getByRole('region', { name: '澄·今 的交付结果' });
    expect(result).toHaveTextContent('delivery fallback summary');
    expect(result).not.toHaveTextContent('别人的结果');
  });

  it('keeps protocol labels and criterion identifiers out of the main result area', () => {
    render(<RoomTaskDeliveryDetails
      owner="澄·今"
      roleResult={{
        resultSummary: 'WorkItem 完成，Receipt ID receipt-private 已保存',
        resultKind: 'complete',
        resultAtMs: 20,
        verificationCount: 3,
        verifications: [
          { label: 'AC-27', result: 'pass', source: 'quality_gate' },
          { label: 'criterionId:criterion-private', result: 'recorded', source: 'quality_gate' },
          { label: 'Task task-private 通过 Dispatch', result: 'pass', source: 'quality_gate' },
        ],
        artifactRefs: [],
        residualRisks: [],
      }}
    />);

    const result = screen.getByRole('region', { name: '澄·今 的交付结果' });
    const main = [
      result.querySelector('.room-task-delivery__summary')?.textContent,
      result.querySelector('.room-task-delivery__verification')?.textContent,
    ].join(' ');
    expect(main).toMatch(/工作成果\s*完成/);
    expect(main).toContain('验收标准');
    expect(main).toContain('工作项协作记录通过执行安排');
    expect(main).not.toMatch(
      /WorkItem|Kernel|Root|Dispatch|Task|Receipt|\bID\b|\bAC(?:[-_:][A-Za-z0-9_.:-]+)?\b|criterionId|criterion-private|receipt-private/iu,
    );
  });
});

function todoProjection(): Todo {
  return {
    schemaVersion: 'rag-ime.agent-todo.v1',
    id: 'todo:session-owner',
    sessionId: 'session-owner',
    revision: 4,
    actor: 'agent-runtime',
    updatedAtMs: 7_000,
    roomLineage: null,
    phases: [{
      name: '实现',
      tasks: [
        { content: '接入 Room Todo', status: 'in_progress' },
        { content: '补齐异常态', status: 'blocked', reason: '等待后端字段' },
        { content: '完成聚焦测试', status: 'completed' },
        { content: '旧方案', status: 'abandoned' },
      ],
    }],
    counts: {
      total: 4,
      pending: 0,
      inProgress: 1,
      blocked: 1,
      completed: 1,
      abandoned: 1,
    },
  };
}

function deliveryProjection(): RoomWorkspaceDeliveryProjection {
  return {
    schemaVersion: 'wisdom-weasel.room-workspace-delivery.v1',
    ownerParticipantId: 'participant-owner',
    ownerSessionId: 'session-owner',
    workItemId: 'work-item:owner',
    taskId: 'task:owner',
    deliveryRevision: `sha256:${'a'.repeat(64)}`,
    baseCommit: 'git:base',
    workspaceSnapshotSha256: 'c'.repeat(64),
    patchSha256: 'd'.repeat(64),
    deliveredAtMs: 12_345,
    resultSummary: 'delivery fallback summary',
    manifestSha256: 'b'.repeat(64),
    files: [
      {
        path: 'src/Room.tsx',
        additions: 12,
        deletions: 3,
        binary: false,
        generated: false,
        redacted: false,
      },
      {
        path: 'dist/room.bin',
        additions: null,
        deletions: null,
        binary: true,
        generated: true,
        redacted: false,
      },
      {
        path: 'private/hidden.txt',
        additions: 2,
        deletions: 2,
        binary: false,
        generated: false,
        redacted: true,
      },
    ],
    totals: {
      fileCount: 3,
      additions: 14,
      deletions: 5,
      binaryFiles: 1,
      generatedFiles: 1,
      redactedFiles: 1,
    },
    artifactRefs: ['artifact:room-ui'],
    verificationCount: 2,
    verifications: [{
      label: 'Room 任务页聚焦测试',
      result: 'pass',
      source: 'quality_gate',
    }],
    verificationRefs: ['vitest:RoomTaskAuthorityDetails'],
    residualRisks: ['前台安装态尚未验证'],
  };
}

function workItem(overrides: Partial<RoomWorkItem> = {}): RoomWorkItem {
  return {
    id: 'work-item:owner',
    roomId: 'room:1',
    topicId: '',
    rootTurnId: 'root:1',
    rootWorkId: 'work-item:owner',
    parentWorkId: '',
    objective: '实现 Room 任务页',
    expectedOutput: '可核对结果',
    acceptanceCriteria: ['显示权威 Todo 和交付收据'],
    accountableParticipantId: 'participant-owner',
    currentOwnerParticipantId: 'participant-owner',
    offeredToParticipantId: '',
    createdByParticipantId: 'participant-owner',
    clientMessageId: 'message:1',
    state: 'done',
    depth: 1,
    revision: 1,
    resultSummary: '工作成果已验收并交付',
    artifactRefs: ['artifact:room-ui'],
    evidenceRefs: ['vitest:RoomTaskAuthorityDetails'],
    blocker: {},
    acceptedTurnId: 'turn:1',
    createdAtMs: 1,
    updatedAtMs: 2,
    completedAtMs: 2,
    ...overrides,
  };
}
