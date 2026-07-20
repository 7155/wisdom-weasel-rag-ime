import {
  CircleCheck,
  Clock3,
  FileText,
  Gauge,
  LockKeyhole,
  ShieldCheck,
  Square,
  TriangleAlert,
  Wrench,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { useState } from 'react';
import { Button } from '@/components/primitives';
import type { RoomKernelProjection, RootProjection } from '@/contracts/room-kernel-reducer';
import type { RoomKernelReceiptV1 } from '@/contracts/generated/room-kernel-receipt.v1';
import {
  buildCancelRootCommand,
  buildPanicCommand,
  type RoomKernelCommandTransport,
} from './room-kernel-command-transport';
import './room-kernel-control-plane.css';

export type RootBudgetSummary = {
  maxDispatches: number;
  usedDispatches: number;
  maxTokens: number;
  usedTokens: number;
  maxWallTimeMs: number;
  elapsedMs: number;
};

export type RuntimeReceiptSummary = {
  revision: string;
  status: 'pending' | 'sealed' | 'rejected' | 'missing';
  contentHash: string;
};

export function RoomKernelControlPlane({
  budgetsByRootId,
  capabilityReceiptsByRootId,
  contextReceiptsByRootId,
  commandTransport,
  commandDisabledReason,
  panicEnabled = false,
  projection,
}: {
  projection: RoomKernelProjection;
  budgetsByRootId: Record<string, RootBudgetSummary>;
  contextReceiptsByRootId: Record<string, RuntimeReceiptSummary>;
  capabilityReceiptsByRootId: Record<string, RuntimeReceiptSummary>;
  commandTransport?: RoomKernelCommandTransport;
  commandDisabledReason?: string;
  panicEnabled?: boolean;
}) {
  const roots = Object.values(projection.rootsById).sort((left, right) => (
    left.updatedAtMs === right.updatedAtMs
      ? left.rootId.localeCompare(right.rootId)
      : right.updatedAtMs - left.updatedAtMs
  ));
  const [panicPending, setPanicPending] = useState(false);
  const [panicReceipt, setPanicReceipt] = useState<RoomKernelReceiptV1 | null>(null);
  const [panicError, setPanicError] = useState('');
  const requestPanic = async () => {
    if (!panicEnabled || !commandTransport || panicPending) return;
    if (!window.confirm('紧急停止会取消这个 Room 中所有正在执行的根任务。确认继续？')) return;
    setPanicPending(true);
    setPanicReceipt(null);
    setPanicError('');
    const commandId = `ui-panic:${projection.roomId}:${Date.now()}`;
    try {
      setPanicReceipt(await commandTransport.execute(buildPanicCommand(
        projection.roomId,
        { commandId, sourceId: 'room-kernel-control-plane', createdAtMs: Date.now() },
      )));
    } catch (error) {
      setPanicError(error instanceof Error ? error.message : '紧急停止未返回有效回执');
    } finally {
      setPanicPending(false);
    }
  };
  return <section className="room-kernel-control" aria-label="Room 协作控制面">
    <header className="room-kernel-control__header"><span><strong>协作控制面</strong><small>{roots.length} 个根任务 · cursor {projection.lastSequence}</small></span><span className="room-kernel-control__actions">{projection.needsSnapshot ? <b data-state="warning">等待状态快照</b> : <b data-state="healthy">状态已同步</b>}{panicEnabled ? <Button variant="quiet" size="small" leadingIcon={<TriangleAlert size={13} />} disabled={!commandTransport || panicPending} onClick={() => void requestPanic()}>{panicPending ? '正在停止' : '紧急停止'}</Button> : null}</span></header>
    {panicReceipt ? <p className="room-kernel-control__panic-receipt" role="status">{receiptStatusLabel(panicReceipt)} · {panicReceipt.receiptId}</p> : null}
    {panicError ? <p className="room-kernel-control__command-error" role="alert">{panicError}</p> : null}
    <div className="room-kernel-control__roots">
      {roots.map((root) => <RootControlSection
        key={`${root.rootId}:${root.generation}`}
        root={root}
        projection={projection}
        budget={budgetsByRootId[root.rootId]}
        contextReceipt={contextReceiptsByRootId[root.rootId]}
        capabilityReceipt={capabilityReceiptsByRootId[root.rootId]}
        commandTransport={commandTransport}
        commandDisabledReason={commandDisabledReason}
      />)}
      {!roots.length ? <p className="room-kernel-control__empty">当前没有根任务。</p> : null}
    </div>
  </section>;
}

function RootControlSection({
  budget,
  capabilityReceipt,
  contextReceipt,
  commandTransport,
  commandDisabledReason,
  projection,
  root,
}: {
  root: RootProjection;
  projection: RoomKernelProjection;
  budget?: RootBudgetSummary;
  contextReceipt?: RuntimeReceiptSummary;
  capabilityReceipt?: RuntimeReceiptSummary;
  commandTransport?: RoomKernelCommandTransport;
  commandDisabledReason?: string;
}) {
  const posts = projection.postOrder
    .map((postId) => projection.postsById[postId])
    .filter((post) => post?.rootId === root.rootId);
  const sessions = Object.values(projection.sessionsById)
    .filter((session) => session.rootId === root.rootId)
    .sort((left, right) => left.sessionId.localeCompare(right.sessionId));
  const receipt = projection.terminalReceiptByRootId[root.rootId];
  const cancelReceipt = projection.cancelReceiptByRootId[root.rootId];
  const [pending, setPending] = useState(false);
  const [commandReceipt, setCommandReceipt] = useState<RoomKernelReceiptV1 | null>(null);
  const [commandError, setCommandError] = useState('');
  const commandAwaitingProjection = Boolean(commandReceipt && commandReceipt.status !== 'rejected');
  const requestStop = async () => {
    if (!commandTransport || pending) return;
    setPending(true);
    setCommandReceipt(null);
    setCommandError('');
    const commandId = `ui-cancel:${root.rootId}:${root.generation}:${Date.now()}`;
    try {
      const nextReceipt = await commandTransport.execute(buildCancelRootCommand(
        { roomId: projection.roomId, rootId: root.rootId, generation: root.generation },
        { commandId, sourceId: 'room-kernel-control-plane', createdAtMs: Date.now() },
      ));
      setCommandReceipt(nextReceipt);
    } catch (error) {
      setCommandError(error instanceof Error ? error.message : '取消命令未返回有效回执');
    } finally {
      setPending(false);
    }
  };
  return <article className="room-kernel-root" data-root-state={root.state}>
    <header className="room-kernel-root__header">
      <span><small>Root · generation {root.generation}</small><strong>{root.rootId}</strong><i data-state={root.state}>{rootStateLabel(root)}</i></span>
      {!root.isFinal ? <Button variant="quiet" size="small" leadingIcon={<Square size={13} />} disabled={!commandTransport || pending || commandAwaitingProjection} title={commandTransport ? commandAwaitingProjection ? '等待 canonical Root 投影更新' : '提交带 generation 的取消命令' : commandDisabledReason || '后端 command route 尚未接入'} onClick={() => void requestStop()}>{pending ? '正在提交' : commandAwaitingProjection ? '已提交' : '停止'}</Button> : <span className="room-kernel-root__terminal"><CircleCheck size={15} />终态已确认</span>}
    </header>
    <div className="room-kernel-root__summary">
      <span><ShieldCheck size={14} /><small>当前负责人</small><strong>{root.owner || '等待分派'}</strong></span>
      <BudgetMetric icon={<Gauge size={14} />} label="Dispatch" used={budget?.usedDispatches} maximum={budget?.maxDispatches} />
      <BudgetMetric icon={<FileText size={14} />} label="Token" used={budget?.usedTokens} maximum={budget?.maxTokens} />
      <BudgetMetric icon={<Clock3 size={14} />} label="墙钟" used={budget?.elapsedMs} maximum={budget?.maxWallTimeMs} formatter={durationLabel} />
    </div>
    <section className="room-kernel-root__receipts" aria-label={`${root.rootId} 运行回执`}>
      <ReceiptSummary icon={<LockKeyhole size={14} />} label="Context" receipt={contextReceipt} />
      <ReceiptSummary icon={<Wrench size={14} />} label="Capability" receipt={capabilityReceipt} />
      <span><CircleCheck size={14} /><small>Terminal</small><strong>{receipt ? `${receipt.receiptKind}/${receipt.status} · ${receipt.receiptId}` : '等待全链静止'}</strong></span>
      <span data-receipt-state={commandReceipt?.status ?? cancelReceipt?.status}><Square size={14} /><small>Cancel</small><strong>{commandReceipt ? `${receiptStatusLabel(commandReceipt)} · ${commandReceipt.receiptId}` : cancelReceipt ? `${receiptStatusLabel(cancelReceipt)} · ${cancelReceipt.receiptId}` : commandTransport ? '尚未请求' : '只读，控制命令未授权'}</strong></span>
    </section>
    {commandError ? <p className="room-kernel-control__command-error" role="alert">{commandError}</p> : null}
    <div className="room-kernel-root__planes">
      <section className="room-kernel-posts" aria-label={`${root.rootId} 公开 Posts`}><header><strong>公开 Posts</strong><small>仅显式提交</small></header>{posts.length ? posts.map((post) => <article key={post!.postId}><span><b>{postKindLabel(post!.kind)}</b><small>{post!.authorActorRef}</small></span><p>{post!.content}</p></article>) : <p className="room-kernel-control__empty">还没有公开提交。</p>}</section>
      <section className="room-kernel-sessions" aria-label={`${root.rootId} 私有 Sessions`}><header><strong>私有 Session Inspector</strong><small>过程不进入 Room</small></header>{sessions.length ? sessions.map((session) => <details key={session.sessionId}><summary><LockKeyhole size={13} /><span><strong>{session.sessionId}</strong><small>{sessionStateLabel(session.state)} · generation {session.generation}</small></span></summary><dl><div><dt>公开状态</dt><dd>仅状态元数据</dd></div><div><dt>Transcript</dt><dd>私有，不投影到 Room</dd></div>{session.capabilityManifest ? <><div><dt>Capability</dt><dd>{session.capabilityManifest.status} · epoch {session.capabilityManifest.capabilityEpoch}</dd></div><div><dt>Manifest</dt><dd title={session.capabilityManifest.manifestHash}>{session.capabilityManifest.manifestId} · {shortHash(session.capabilityManifest.manifestHash)}</dd></div><div><dt>Profile</dt><dd title={session.capabilityManifest.compiledRuntimeProfileRef.contentHash}>{session.capabilityManifest.compiledRuntimeProfileRef.profileId} · {session.capabilityManifest.compiledRuntimeProfileRef.revision}</dd></div></> : null}</dl></details>) : <p className="room-kernel-control__empty">当前没有绑定 Session。</p>}</section>
    </div>
  </article>;
}

function BudgetMetric({
  formatter = compactNumber,
  icon,
  label,
  maximum,
  used,
}: {
  icon: ReactNode;
  label: string;
  used?: number;
  maximum?: number;
  formatter?: (value: number) => string;
}) {
  const available = used !== undefined && maximum !== undefined && maximum > 0;
  const ratio = available ? Math.min(1, Math.max(0, used / maximum)) : 0;
  return <span>{icon}<small>{label}</small><strong>{available ? `${formatter(used)} / ${formatter(maximum)}` : '未上报'}</strong><i aria-hidden="true"><b style={{ width: `${ratio * 100}%` }} /></i></span>;
}

function ReceiptSummary({ icon, label, receipt }: { icon: ReactNode; label: string; receipt?: RuntimeReceiptSummary }) {
  return <span>{icon}<small>{label}</small><strong>{receipt ? `${runtimeReceiptStatusLabel(receipt.status)} · ${receipt.revision}` : '未上报'}</strong></span>;
}

function rootStateLabel(root: RootProjection): string {
  if (root.isFinal) return '已完成并确认';
  return ({ pending: '排队中', running: '执行中', waiting: '等待中', blocked: '已阻塞', cancelling: '取消中', completed: '已完成，等待终态回执', failed: '失败，等待终态回执', cancelled: '已取消，等待终态回执', cancelled_with_unknowns: '已取消，仍有未知执行' } as Record<RootProjection['state'], string>)[root.state];
}

function sessionStateLabel(value: string): string {
  return ({ idle: '空闲', queued: '排队中', running: '执行中', completed: '本地已完成', failed: '本地失败', cancelled: '本地已取消' } as Record<string, string>)[value] ?? value;
}

function runtimeReceiptStatusLabel(value: RuntimeReceiptSummary['status']): string {
  return ({ pending: '待封存', sealed: '已封存', rejected: '已拒绝', missing: '缺失' } as const)[value];
}

function shortHash(value: string): string {
  return value.length > 12 ? `${value.slice(0, 12)}...` : value;
}

function receiptStatusLabel(receipt: RoomKernelReceiptV1): string {
  const status = ({ applied: '已接受', noop: '无需重复执行', rejected: '已拒绝', unknown: '状态未知' } as const)[receipt.status];
  return `${status} · ${receipt.receiptKind}`;
}

function postKindLabel(value: string): string {
  return ({ user_request: '用户请求', answer: '回答', finding: '发现', decision: '决定', question: '问题', result: '结果', blocker: '阻塞', announcement: '公告' } as Record<string, string>)[value] ?? value;
}

function compactNumber(value: number): string {
  return new Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 1 }).format(value);
}

function durationLabel(value: number): string {
  if (value < 1_000) return `${value}ms`;
  const seconds = Math.round(value / 1_000);
  return seconds < 60 ? `${seconds}s` : `${Math.round(seconds / 60)}m`;
}
