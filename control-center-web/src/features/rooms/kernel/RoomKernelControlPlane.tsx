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
import { RoomRequirementsControlPlane } from '../requirements/RoomRequirementsControlPlane';
import type { RoomRequirementsReadProjection } from '../requirements/room-requirements-read-model';
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
  requirementsByRootId = {},
}: {
  projection: RoomKernelProjection;
  budgetsByRootId: Record<string, RootBudgetSummary>;
  contextReceiptsByRootId: Record<string, RuntimeReceiptSummary>;
  capabilityReceiptsByRootId: Record<string, RuntimeReceiptSummary>;
  commandTransport?: RoomKernelCommandTransport;
  commandDisabledReason?: string;
  panicEnabled?: boolean;
  requirementsByRootId?: Record<string, RoomRequirementsReadProjection>;
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
    if (!window.confirm('“停止全部任务”会取消这个协作空间中正在运行的伙伴、工具和后续任务。确认继续？')) return;
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
      setPanicError(error instanceof Error ? error.message : '停止请求没有收到确认，请稍后重试');
    } finally {
      setPanicPending(false);
    }
  };
  return <section className="room-kernel-control" aria-label="协作任务进展">
    <header className="room-kernel-control__header"><span><strong>任务进展</strong><small>{roots.length} 个任务</small></span><span className="room-kernel-control__actions">{projection.needsSnapshot ? <b data-state="warning">正在恢复状态</b> : <b data-state="healthy">状态已同步</b>}{panicEnabled ? <Button variant="quiet" size="small" leadingIcon={<TriangleAlert size={13} />} disabled={!commandTransport || panicPending} onClick={() => void requestPanic()}>{panicPending ? '正在停止' : '停止全部任务'}</Button> : null}</span></header>
    {panicReceipt ? <p className="room-kernel-control__panic-receipt" role="status" title={panicReceipt.receiptId}>{receiptStatusLabel(panicReceipt)}</p> : null}
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
        requirements={requirementsByRootId[root.rootId]}
      />)}
      {!roots.length ? <p className="room-kernel-control__empty">当前没有任务。</p> : null}
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
  requirements,
}: {
  root: RootProjection;
  projection: RoomKernelProjection;
  budget?: RootBudgetSummary;
  contextReceipt?: RuntimeReceiptSummary;
  capabilityReceipt?: RuntimeReceiptSummary;
  commandTransport?: RoomKernelCommandTransport;
  commandDisabledReason?: string;
  requirements?: RoomRequirementsReadProjection;
}) {
  const posts = projection.postOrder
    .map((postId) => projection.postsById[postId])
    .filter((post) => post?.rootId === root.rootId);
  const sessions = Object.values(projection.sessionsById)
    .filter((session) => session.rootId === root.rootId)
    .sort((left, right) => left.sessionId.localeCompare(right.sessionId));
  const receipt = projection.terminalReceiptByRootId[root.rootId];
  const cancelReceipt = projection.cancelReceiptByRootId[root.rootId];
  const unresolvedSurfaces = projection.cancellationSurfaces.filter((item) => (
    item.rootId === root.rootId && item.state !== 'terminated'
  ));
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
      setCommandError(error instanceof Error ? error.message : '停止请求没有收到确认，请稍后重试');
    } finally {
      setPending(false);
    }
  };
  const taskTitle = rootTaskTitle(root, requirements);
  return <article className="room-kernel-root" data-root-state={root.state}>
    <header className="room-kernel-root__header">
      <span title={`${root.rootId} · generation ${root.generation}`}><small>任务 · 第 {root.generation} 次尝试</small><strong>{taskTitle}</strong><i data-state={root.state}>{rootStateLabel(root, receipt)}</i></span>
      {!root.isFinal ? <Button variant="quiet" size="small" leadingIcon={<Square size={13} />} disabled={!commandTransport || pending || commandAwaitingProjection} title={commandTransport ? commandAwaitingProjection ? '正在等待停止结果' : '停止这个任务及其伙伴、工具和后续任务' : commandDisabledReason || '当前连接没有停止任务的权限'} onClick={() => void requestStop()}>{pending ? '正在停止' : commandAwaitingProjection ? '已请求停止' : '停止此任务'}</Button> : <span className="room-kernel-root__terminal"><CircleCheck size={15} />任务已结束</span>}
    </header>
    {unresolvedSurfaces.length ? <section className="room-kernel-root__unresolved" role="alert">
      <TriangleAlert size={16} />
      <span><strong>还有后台工作没有确认停止</strong><small>为了避免产生迟到结果，当前任务暂时保持锁定。可以再次停止，或请管理员停止全部任务并等待状态确认。</small></span>
      <ul>{unresolvedSurfaces.map((item) => <li key={`${item.cancelId}:${item.surface}`}><code>{item.surface}</code><b>{item.state}</b><small>{surfaceTargets(item.detail)}</small></li>)}</ul>
    </section> : null}
    <div className="room-kernel-root__summary">
      <span><ShieldCheck size={14} /><small>当前负责人</small><strong>{root.owner || '等待分派'}</strong></span>
      <BudgetMetric icon={<Gauge size={14} />} label="协作轮次" used={budget?.usedDispatches} maximum={budget?.maxDispatches} />
      <BudgetMetric icon={<FileText size={14} />} label="上下文用量" used={budget?.usedTokens} maximum={budget?.maxTokens} />
      <BudgetMetric icon={<Clock3 size={14} />} label="运行时间" used={budget?.elapsedMs} maximum={budget?.maxWallTimeMs} formatter={durationLabel} />
    </div>
    <section className="room-kernel-root__receipts" aria-label={`${root.rootId} 运行回执`}>
      <ReceiptSummary icon={<LockKeyhole size={14} />} label="上下文" receipt={contextReceipt} />
      <ReceiptSummary icon={<Wrench size={14} />} label="技能与工具" receipt={capabilityReceipt} />
      <span><CircleCheck size={14} /><small>任务验收</small><strong>{receipt ? qualityGateLabel(receipt) : '等待伙伴和工具结束'}</strong></span>
      <span><ShieldCheck size={14} /><small>额外交付检查</small><strong>{receipt ? deliveryGateLabel(receipt) : '等待任务结束'}</strong></span>
      <span data-receipt-state={commandReceipt?.status ?? cancelReceipt?.status}><Square size={14} /><small>停止状态</small><strong title={commandReceipt?.receiptId ?? cancelReceipt?.receiptId}>{commandReceipt ? receiptStatusLabel(commandReceipt) : cancelReceipt ? receiptStatusLabel(cancelReceipt) : commandTransport ? '尚未请求' : '当前连接没有停止权限'}</strong></span>
    </section>
    {commandError ? <p className="room-kernel-control__command-error" role="alert">{commandError}</p> : null}
    <div className="room-kernel-root__planes">
      <section className="room-kernel-posts" aria-label={`${root.rootId} 公开交付`}><header><strong>公开交付</strong><small>只有明确提交的结果会出现在这里</small></header>{posts.length ? posts.map((post) => <article key={post!.postId}><span><b>{postKindLabel(post!.kind)}</b><small>{post!.authorActorRef}</small></span><p>{post!.content}</p></article>) : <p className="room-kernel-control__empty">还没有公开交付。</p>}</section>
      <section className="room-kernel-sessions" aria-label={`${root.rootId} 伙伴运行状态`}><header><strong>伙伴运行状态</strong><small>这里只显示进度，不公开伙伴的私有思考</small></header>{sessions.length ? sessions.map((session) => <details key={session.sessionId}><summary title={session.sessionId}><LockKeyhole size={13} /><span><strong>伙伴运行</strong><small>{sessionStateLabel(session.state)} · 第 {session.generation} 次尝试</small></span></summary><dl><div><dt>运行记录</dt><dd>{session.sessionId}</dd></div><div><dt>公开范围</dt><dd>只公开状态，不公开私有对话正文</dd></div>{session.capabilityManifest ? <><div><dt>能力版本</dt><dd>{session.capabilityManifest.status} · 第 {session.capabilityManifest.capabilityEpoch} 版</dd></div><div><dt>可用能力清单</dt><dd title={session.capabilityManifest.manifestHash}>{session.capabilityManifest.manifestId} · {shortHash(session.capabilityManifest.manifestHash)}</dd></div><div><dt>工作配置</dt><dd title={session.capabilityManifest.compiledRuntimeProfileRef.contentHash}>{session.capabilityManifest.compiledRuntimeProfileRef.profileId} · {session.capabilityManifest.compiledRuntimeProfileRef.revision}</dd></div></> : null}{session.requirementObservation ? <><div><dt>需求目录</dt><dd>{session.requirementObservation.catalogRevisionId || '目录缺失'} · {session.requirementObservation.state}</dd></div><div><dt>验证记录</dt><dd>{session.requirementObservation.warnings.length ? `观察提醒 ${session.requirementObservation.warnings.length} 项` : `${session.requirementObservation.proofReceiptRefs.length} 个回执`}</dd></div></> : null}</dl></details>) : <p className="room-kernel-control__empty">当前没有伙伴运行记录。</p>}</section>
    </div>
    {requirements ? <details className="room-kernel-root__evidence">
      <summary><FileText size={15} /><span><strong>查看验收与证据详情</strong><small>原始需求、验收标准和系统核验记录</small></span></summary>
      <RoomRequirementsControlPlane projection={requirements} />
    </details> : null}
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

function rootTaskTitle(
  root: RootProjection,
  requirements?: RoomRequirementsReadProjection,
): string {
  const original = requirements?.anchors[0]?.originalText.trim();
  if (!original) return `任务 ${shortHash(root.rootId)}`;
  const firstLine = original.split(/\r?\n/u, 1)[0]?.trim() ?? '';
  return firstLine.length > 120 ? `${firstLine.slice(0, 117)}...` : firstLine;
}

function rootStateLabel(root: RootProjection, receipt?: RoomKernelReceiptV1): string {
  if (root.isFinal) return deliveryGatePassed(receipt) ? '已完成并通过检查' : '已结束，仍有检查提醒';
  return ({ pending: '排队中', running: '执行中', waiting: '等待中', blocked: '已阻塞', cancelling: '正在停止', completed: '正在确认交付', failed: '正在确认未完成原因', cancelled: '正在确认已停止', cancelled_with_unknowns: '已请求停止，仍在核对后台任务' } as Record<RootProjection['state'], string>)[root.state];
}

function surfaceTargets(detail: Record<string, unknown>): string {
  const targetIds = Array.isArray(detail.targetIds) ? detail.targetIds.filter((item): item is string => typeof item === 'string') : [];
  return targetIds.length ? targetIds.join(', ') : '尚未确认具体目标';
}

function deliveryGatePassed(receipt?: RoomKernelReceiptV1): boolean {
  const observation = receipt?.details?.deliveryGateObservation;
  return typeof observation === 'object' && observation !== null
    && 'gateStatus' in observation && observation.gateStatus === 'observed_pass';
}

function deliveryGateLabel(receipt: RoomKernelReceiptV1): string {
  if (deliveryGatePassed(receipt)) return '同伴与证据观察通过';
  const observation = receipt.details?.deliveryGateObservation;
  if (typeof observation === 'object' && observation !== null && 'gateStatus' in observation) {
    return observation.gateStatus === 'warn_blocked' ? '发现阻塞或未知项' : '额外检查尚未完成';
  }
  return '额外检查尚未上报';
}

function qualityGateLabel(receipt: RoomKernelReceiptV1): string {
  const verdict = receipt.details?.qualityGateVerdict;
  if (verdict === 'ready_to_deliver') return '全部验收项已有有效证据';
  if (verdict === 'not_ready') return '还有验收项未完成';
  return '任务收工检查已由系统处理';
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
  return ({
    applied: '停止请求已接受',
    noop: '已经停止，无需重复操作',
    rejected: '停止请求被拒绝',
    unknown: '仍在确认停止状态',
  } as const)[receipt.status];
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
