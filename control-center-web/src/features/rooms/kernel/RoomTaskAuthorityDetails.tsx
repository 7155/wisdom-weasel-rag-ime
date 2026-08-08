import {
  Circle,
  CircleAlert,
  CircleCheck,
  CircleMinus,
  FileCheck2,
  FileCode2,
  ListChecks,
  ReceiptText,
  ShieldCheck,
} from 'lucide-react';
import type { ReactNode } from 'react';

import type {
  Todo,
  TodoTask,
} from '@/contracts/generated/agent-workflow-state.v1';
import type {
  PublicVerification,
  WorkspaceDelivery,
  WorkspaceDeliveryFile,
} from '@/contracts/generated/room-task.v3';
import type { RoomWorkItem } from '../room-types';
import { roomPublicActivityText } from '../timeline/room-tool-presentation';
import { RoomTaskUpdatedAt } from './RoomTaskUpdatedAt';

export type RoomWorkspaceDeliveryFile = WorkspaceDeliveryFile;

export type RoomPublicVerification = PublicVerification;

export type RoomTaskRoleResultProjection = {
  resultSummary: string;
  resultKind?: 'complete' | 'dispatch' | 'wait' | 'post' | 'block';
  resultAtMs?: number;
  verificationCount: number;
  verifications: RoomPublicVerification[];
  artifactRefs: string[];
  residualRisks: string[];
};

export type RoomWorkspaceDeliveryProjection = WorkspaceDelivery;

export function RoomTaskTodoDetails({
  owner,
  todo,
}: {
  owner: string;
  todo?: Todo;
}) {
  const settled = todo ? todo.counts.completed + todo.counts.abandoned : 0;
  return <section
    aria-label={`${owner} 的 Todo`}
    className="room-task-authority room-task-todo"
    data-state={todo ? 'reported' : 'missing'}
  >
    <header>
      <span><ListChecks aria-hidden="true" size={15} /><strong>{owner} 的 Todo</strong></span>
      <small>{todo
        ? todo.counts.total
          ? `${settled} / ${todo.counts.total} 已收束`
          : '当前没有 Todo'
        : 'Todo 未上报'}</small>
    </header>
    {!todo ? (
      <p className="room-task-authority__missing">这位伙伴尚未上报权威 Todo。</p>
    ) : todo.phases.length ? (
      <div className="room-task-todo__phases">
        {todo.phases.map((phase) => <section aria-label={phase.name} key={phase.name}>
          <header>
            <strong>{phase.name}</strong>
            <small>{phase.tasks.filter(isSettledTodoTask).length} / {phase.tasks.length}</small>
          </header>
          <ul>{phase.tasks.map((task, index) => <li
            data-state={task.status}
            key={`${phase.name}:${index}:${task.content}`}
          >
            <span aria-hidden="true">{todoTaskIcon(task.status)}</span>
            <span><strong>{task.content}</strong>{task.reason ? <small>{task.reason}</small> : null}</span>
            <small>{todoTaskStatusLabel(task.status)}</small>
          </li>)}</ul>
        </section>)}
      </div>
    ) : (
      <p className="room-task-authority__empty">这位伙伴已确认当前没有 Todo。</p>
    )}
    {todo ? <footer>
      <small>只读同步自这位伙伴的权威 Todo</small>
      <RoomTaskUpdatedAt updatedAtMs={todo.updatedAtMs > 0 ? todo.updatedAtMs : undefined} />
    </footer> : null}
  </section>;
}

export function RoomTaskDeliveryDetails({
  delivery,
  owner,
  roleResult,
  workItem,
}: {
  delivery?: RoomWorkspaceDeliveryProjection;
  owner: string;
  roleResult?: RoomTaskRoleResultProjection;
  workItem?: RoomWorkItem;
}) {
  const linkedWorkItem = delivery && workItem?.id !== delivery.workItemId
    ? undefined
    : workItem;
  const resultSummary = publicAuthorityText(roleResult?.resultSummary.trim()
    || linkedWorkItem?.resultSummary.trim()
    || delivery?.resultSummary.trim()
    || '');
  const verificationRefs = uniqueText([
    ...(linkedWorkItem?.evidenceRefs ?? []),
    ...(delivery?.verificationRefs ?? []),
  ]);
  const artifactRefs = uniqueText([
    ...(linkedWorkItem?.artifactRefs ?? []),
    ...(roleResult?.artifactRefs ?? []),
    ...(delivery?.artifactRefs ?? []),
  ]);
  const verifications = uniqueVerifications([
    ...(roleResult?.verifications ?? []),
    ...(delivery?.verifications ?? []),
  ]);
  const publicVerifications = publicVerificationRows(verifications);
  const verificationCount = Math.max(
    roleResult?.verificationCount ?? 0,
    delivery?.verificationCount ?? 0,
    verificationRefs.length,
    verifications.length,
  );
  const residualRisks = uniqueText([
    ...(roleResult?.residualRisks ?? []),
    ...(delivery?.residualRisks ?? []),
  ]);
  const hasRoleResult = Boolean(linkedWorkItem || roleResult || delivery);
  return <section
    aria-label={`${owner} 的交付结果`}
    className="room-task-authority room-task-delivery"
    data-state={hasRoleResult ? 'reported' : 'missing'}
  >
    <header>
      <span><FileCheck2 aria-hidden="true" size={15} /><strong>{owner} 的交付结果</strong></span>
      <small>{delivery
        ? linkedWorkItem || roleResult ? '成果与代码交付已记录' : '代码交付已记录'
        : linkedWorkItem || roleResult ? '工作成果已记录' : '工作结果未提交'}</small>
    </header>
    {!hasRoleResult ? <p className="room-task-authority__missing">
      这位伙伴还没有提交工作结果；不会从本地文件状态猜测这位伙伴的贡献。
    </p> : <>
      <div className="room-task-delivery__summary">
        <ReceiptText aria-hidden="true" size={15} />
        <span><small>结果</small><strong>{resultSummary || '结果摘要未上报'}</strong></span>
      </div>
      <section className="room-task-delivery__files" aria-label="交付文件">
        <header>
          <span><FileCode2 aria-hidden="true" size={14} /><strong>改动文件</strong></span>
          <small>{delivery ? deliveryTotalsLabel(delivery) : '本角色无代码交付'}</small>
        </header>
        {delivery?.files.length ? <ul>{delivery.files.map((file) => <li key={file.path}>
          <span>
            <strong>{file.redacted ? '路径已隐藏' : file.path}</strong>
            {file.generated || file.binary ? <small>{[
              file.generated ? '生成文件' : '',
              file.binary ? '二进制' : '',
            ].filter(Boolean).join(' · ')}</small> : null}
          </span>
          <code>{deliveryFileStat(file)}</code>
        </li>)}</ul> : <p>{delivery
          ? '本次交付没有文件改动。'
          : '这份角色成果不包含工作区代码交付。'}</p>}
      </section>
      <section className="room-task-delivery__verification" aria-label="交付验证">
        <header><span><ShieldCheck aria-hidden="true" size={14} /><strong>验证</strong></span></header>
        {verificationCount ? <p className="room-task-delivery__verification-count">
          <CircleCheck aria-hidden="true" size={14} />
          <span>已记录 {verificationCount} 项验证证据</span>
        </p> : <p>验证明细未上报。</p>}
        {publicVerifications.length ? <ul>{publicVerifications.map((verification) => <li
          data-state={verification.result}
          key={`${verification.label}:${verification.result}`}
        >
          <span aria-hidden="true">{verificationIcon(verification.result)}</span>
          <span><strong>{verification.label}</strong><small>{verificationResultLabel(verification.result)}</small></span>
        </li>)}</ul> : null}
      </section>
      {residualRisks.length ? <section className="room-task-delivery__risks" aria-label="剩余风险">
        <header><CircleAlert aria-hidden="true" size={14} /><strong>剩余风险</strong></header>
        <ul>{residualRisks.map((risk) => <li key={risk}>{risk}</li>)}</ul>
      </section> : null}
      {delivery || verificationRefs.length || artifactRefs.length ? <details className="room-task-delivery__receipt">
        <summary><ReceiptText aria-hidden="true" size={14} /><span><strong>成果与交付审计</strong><small>原始证据引用与内容指纹</small></span></summary>
        <dl>
          {delivery ? <>
            <div><dt>交付版本</dt><dd><code>{delivery.deliveryRevision}</code></dd></div>
            <div><dt>清单指纹</dt><dd><code>{delivery.manifestSha256}</code></dd></div>
            <div><dt>交付时间</dt><dd><time dateTime={new Date(delivery.deliveredAtMs).toISOString()}>{deliveryTimeFormatter.format(new Date(delivery.deliveredAtMs))}</time></dd></div>
          </> : null}
          {verificationRefs.length ? <div><dt>验证证据</dt><dd><ul>{verificationRefs.map((ref) => <li key={ref}><code>{ref}</code></li>)}</ul></dd></div> : null}
          {artifactRefs.length ? <div><dt>交付产物</dt><dd><ul>{artifactRefs.map((ref) => <li key={ref}><code>{ref}</code></li>)}</ul></dd></div> : null}
        </dl>
      </details> : null}
    </>}
  </section>;
}

const deliveryTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
});

function isSettledTodoTask(task: TodoTask): boolean {
  return task.status === 'completed' || task.status === 'abandoned';
}

function todoTaskIcon(status: TodoTask['status']): ReactNode {
  if (status === 'completed') return <CircleCheck size={14} />;
  if (status === 'blocked') return <CircleAlert size={14} />;
  if (status === 'abandoned') return <CircleMinus size={14} />;
  return <Circle size={14} />;
}

function todoTaskStatusLabel(status: TodoTask['status']): string {
  return {
    pending: '待处理',
    in_progress: '进行中',
    blocked: '已阻塞',
    completed: '已完成',
    abandoned: '已放弃',
  }[status];
}

function deliveryFileStat(file: RoomWorkspaceDeliveryFile): string {
  if (file.binary || file.additions === null || file.deletions === null) return '二进制';
  return `+${file.additions} −${file.deletions}`;
}

function deliveryTotalsLabel(delivery: RoomWorkspaceDeliveryProjection): string {
  const totals = delivery.totals;
  const text = `${totals.fileCount} 个文件 · +${totals.additions} −${totals.deletions}`;
  return totals.binaryFiles ? `${text} · ${totals.binaryFiles} 个二进制` : text;
}

function uniqueText(values: string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))];
}

function uniqueVerifications(values: RoomPublicVerification[]): RoomPublicVerification[] {
  const seen = new Set<string>();
  return values.filter((verification) => {
    const key = `${verification.source}\0${verification.label}\0${verification.result}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function publicVerificationRows(values: RoomPublicVerification[]): Array<{
  label: string;
  result: RoomPublicVerification['result'];
}> {
  const seen = new Set<string>();
  return values.flatMap((verification) => {
    const label = publicAuthorityText(verification.label) || '验证记录';
    const key = `${label}\0${verification.result}`;
    if (seen.has(key)) return [];
    seen.add(key);
    return [{ label, result: verification.result }];
  });
}

function publicAuthorityText(value: string): string {
  const withoutProtocolIds = value
    .replace(
      /\b(?:WorkItem|Kernel|Root|Dispatch|Task|Receipt)\s+ID(?:\s*(?:[:=#_-]\s*)?[A-Za-z0-9_.:-]+)?\b/giu,
      '协作记录',
    )
    .replace(
      /\b(?:WorkItem|Kernel|Root|Dispatch|Task|Receipt)(?:Id)?[-_:][A-Za-z0-9_.:-]+\b/giu,
      '协作记录',
    )
    .replace(/\bAC(?:[-_:#/][A-Za-z0-9_.:-]+|\s+\d+)?\b/giu, '验收标准')
    .replace(
      /\bcriterion(?:Id)?(?:\s*[:=#_-]\s*[A-Za-z0-9_.:-]+)?\b/giu,
      '验收标准',
    )
    .replace(/\bWorkItem\b/giu, '工作成果')
    .replace(/\bReceipt\b/giu, '验证记录');
  return roomPublicActivityText(withoutProtocolIds);
}

function verificationIcon(result: RoomPublicVerification['result']): ReactNode {
  if (result === 'pass') return <CircleCheck size={14} />;
  if (result === 'fail') return <CircleAlert size={14} />;
  return <Circle size={14} />;
}

function verificationResultLabel(result: RoomPublicVerification['result']): string {
  return {
    pass: '已通过',
    fail: '未通过',
    not_verified: '尚未验证',
    recorded: '已记录',
  }[result];
}
