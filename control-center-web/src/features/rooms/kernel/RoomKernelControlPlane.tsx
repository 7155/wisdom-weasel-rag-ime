import {
  ArrowRight,
  CircleCheck,
  Clock3,
  FileText,
  Gauge,
  GitBranch,
  LockKeyhole,
  ListChecks,
  ShieldCheck,
  Square,
  TriangleAlert,
  UserRound,
  Wrench,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { useState } from 'react';
import { Button } from '@/components/primitives';
import type { RoomKernelProjection, RootProjection } from '@/contracts/room-kernel-reducer';
import type { RoomKernelReceiptV1 } from '@/contracts/generated/room-kernel-receipt.v1';
import type { RoomTaskV3 } from '@/contracts/generated/room-task.v3';
import type { RoomParticipantPublicProgressProjection } from '@/contracts/room-reducer';
import { RoomRequirementsControlPlane } from '../requirements/RoomRequirementsControlPlane';
import type { RoomRequirementsReadProjection } from '../requirements/room-requirements-read-model';
import { ROOM_PUBLIC_PROGRESS_KIND_LABELS as PUBLIC_PROGRESS_KIND_LABELS, roomParticipantPublicProgressSummary } from '../room-copy';
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

const roomPublicTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  hour: '2-digit',
  minute: '2-digit',
});

export function RoomKernelControlPlane({
  budgetsByRootId,
  capabilityReceiptsByRootId,
  contextReceiptsByRootId,
  commandTransport,
  commandDisabledReason,
  panicEnabled = false,
  participantLabels = {},
  participantProgress = [],
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
  participantLabels?: Record<string, string>;
  participantProgress?: RoomParticipantPublicProgressProjection[];
  requirementsByRootId?: Record<string, RoomRequirementsReadProjection>;
}) {
  const roots = Object.values(projection.rootsById).sort((left, right) => {
    const recency = roomRootRecency(right) - roomRootRecency(left);
    return recency || left.rootId.localeCompare(right.rootId);
  });
  const tasks = Object.values(projection.tasksById);
  const dispatches = Object.values(projection.dispatchesById);
  const completedTasks = tasks.filter((task) => task.state === 'completed').length;
  const activeDispatches = dispatches.filter((dispatch) => (
    ['pending', 'leased', 'running', 'retry_wait', 'timer_wait', 'unknown'].includes(
      dispatch.state,
    )
  )).length;
  const attentionRoots = roots.filter((root) => (
    ['waiting', 'blocked', 'cancelling', 'cancelled_with_unknowns', 'failed'].includes(
      root.state,
    )
  )).length;
  const [panicPending, setPanicPending] = useState(false);
  const [panicConfirming, setPanicConfirming] = useState(false);
  const [panicReceipt, setPanicReceipt] = useState<RoomKernelReceiptV1 | null>(null);
  const [panicError, setPanicError] = useState('');
  const requestPanic = async () => {
    if (!panicEnabled || !commandTransport || panicPending || !panicConfirming) return;
    setPanicConfirming(false);
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
      setPanicError(roomCommandError(error));
    } finally {
      setPanicPending(false);
    }
  };
  return <section className="room-kernel-control" aria-label="协作任务进展">
    <header className="room-kernel-control__header">
      <span>
        <strong>任务进展</strong>
        <small>{roots.length} 个整体任务 · {tasks.length} 个分工 · {dispatches.length} 个执行批次</small>
      </span>
      <span className="room-kernel-control__actions">
        {projection.needsSnapshot
          ? <b data-state="warning">正在恢复状态</b>
          : <b data-state="healthy">状态已同步</b>}
        {panicEnabled && !panicConfirming ? (
          <Button
            variant="quiet"
            size="small"
            leadingIcon={<TriangleAlert size={13} />}
            disabled={!commandTransport || panicPending}
            onClick={() => setPanicConfirming(true)}
          >
            {panicPending ? '正在停止' : '停止全部任务'}
          </Button>
        ) : null}
      </span>
    </header>
    {panicConfirming ? <div className="room-kernel-control__panic-confirmation" role="alert"><p>这会取消当前协作空间中正在运行的伙伴、工具和后续任务。</p><div><Button disabled={panicPending} onClick={() => setPanicConfirming(false)} size="small" variant="quiet">继续运行</Button><Button disabled={!commandTransport} loading={panicPending} onClick={() => void requestPanic()} size="small" variant="danger">确认停止全部</Button></div></div> : null}
    {panicReceipt ? <p className="room-kernel-control__panic-receipt" role="status">{receiptStatusLabel(panicReceipt)}</p> : null}
    {panicError ? <p className="room-kernel-control__command-error" role="alert">{panicError}</p> : null}
    <section className="room-kernel-control__overview" aria-label="整体任务、分工与协作执行总进度">
      <span data-state={attentionRoots ? 'attention' : 'steady'}>
        <GitBranch size={15} />
        <small>整体任务</small>
        <strong>{attentionRoots ? `${attentionRoots} 个需要关注` : `${roots.length} 个状态明确`}</strong>
      </span>
      <span data-state={completedTasks === tasks.length && tasks.length ? 'complete' : 'steady'}>
        <ListChecks size={15} />
        <small>分工</small>
        <strong>{tasks.length ? `${completedTasks} / ${tasks.length} 已完成` : '等待任务拆分'}</strong>
      </span>
      <span data-state={activeDispatches ? 'active' : 'steady'}>
        <Wrench size={15} />
        <small>协作执行</small>
        <strong>{dispatches.length ? `${activeDispatches} 个活跃 · 共 ${dispatches.length} 个` : '等待分派'}</strong>
      </span>
    </section>
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
        participantLabels={participantLabels}
        requirements={requirementsByRootId[root.rootId]}
        participantProgress={participantProgress}
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
  participantLabels,
  participantProgress,
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
  participantLabels: Record<string, string>;
  participantProgress: RoomParticipantPublicProgressProjection[];
  requirements?: RoomRequirementsReadProjection;
}) {
  const posts = projection.postOrder
    .map((postId) => projection.postsById[postId])
    .filter((post) => post?.rootId === root.rootId)
    .sort((left, right) => right!.createdAtMs - left!.createdAtMs);
  const terminal = roomRootIsTerminal(root);
  const visiblePosts = terminal ? posts.slice(0, 1) : posts;
  const sessions = Object.values(projection.sessionsById)
    .filter((session) => session.rootId === root.rootId)
    .sort((left, right) => left.sessionId.localeCompare(right.sessionId));
  const tasks = Object.values(projection.tasksById)
    .filter((task) => task.rootId === root.rootId)
    .sort((left, right) => left.taskId.localeCompare(right.taskId));
  const dispatches = Object.values(projection.dispatchesById)
    .filter((dispatch) => dispatch.rootId === root.rootId);
  const completedTasks = tasks.filter((task) => task.state === 'completed').length;
  const settledDispatches = dispatches.filter((dispatch) => (
    ['committed', 'dead_letter', 'failed', 'cancelled'].includes(dispatch.state)
  )).length;
  const activeDispatches = dispatches.length - settledDispatches;
  const taskProgress = tasks.length ? Math.round((completedTasks / tasks.length) * 100) : 0;
  const individualTasks = tasks.filter((task) => task.taskKind !== 'review');
  const reviewTasks = tasks.filter((task) => task.taskKind === 'review');
  const individualWorkSettled = individualTasks.length > 0 && individualTasks.every((task) => (
    ['completed', 'failed', 'cancelled'].includes(task.state)
  ));
  const sharedCheckVisible = reviewTasks.length > 0 || individualWorkSettled || (
    root.isFinal && tasks.every((task) => ['completed', 'failed', 'cancelled'].includes(task.state))
  );
  const ownershipReceipts = Object.values(projection.receiptsById)
    .filter((item) => item.rootId === root.rootId && item.details.operation === 'task_owner_transfer')
    .sort((left, right) => left.createdAtMs - right.createdAtMs);
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
      setCommandError(roomCommandError(error));
    } finally {
      setPending(false);
    }
  };
  const taskTitle = rootTaskTitle(root, requirements);
  return <article className="room-kernel-root" data-root-state={root.state}>
    <header className="room-kernel-root__header">
      <span><small>任务 · 第 {root.generation} 次尝试</small><strong>{taskTitle}</strong><i data-state={root.state}>{rootStateLabel(root, receipt)}</i></span>
      {!terminal || root.state === 'cancelled_with_unknowns' ? <Button variant="quiet" size="small" leadingIcon={<Square size={13} />} disabled={!commandTransport || pending || commandAwaitingProjection} title={commandTransport ? commandAwaitingProjection ? '正在等待停止结果' : '停止这个任务及其伙伴、工具和后续任务' : commandDisabledReason || '当前连接没有停止任务的权限'} onClick={() => void requestStop()}>{pending ? '正在停止' : commandAwaitingProjection ? '已请求停止' : root.state === 'cancelled_with_unknowns' ? '再次确认停止' : '停止此任务'}</Button> : <span className="room-kernel-root__terminal" data-state={root.state}>{root.state === 'completed' ? <CircleCheck size={15} /> : root.state === 'failed' ? <TriangleAlert size={15} /> : <Square size={15} />}{terminalRootLabel(root)}</span>}
    </header>
    {unresolvedSurfaces.length ? <section className="room-kernel-root__unresolved" role="alert">
      <TriangleAlert size={16} />
      <span><strong>还有后台工作没有确认停止</strong><small>为了避免产生迟到结果，当前任务暂时保持锁定。可以再次停止，或请管理员停止全部任务并等待状态确认。</small></span>
      <details>
        <summary>查看 {unresolvedSurfaces.length} 项停止详情</summary>
        <ul>{unresolvedSurfaces.map((item) => <li key={`${item.cancelId}:${item.surface}`}><span>{cancellationSurfaceLabel(item.surface)}</span><b>{cancellationSurfaceStateLabel(item.state)}</b><small>{surfaceTargets(item.detail)}</small></li>)}</ul>
      </details>
    </section> : null}
    <section className="room-kernel-root__progress" aria-label="整体任务、每个人的部分与协作执行进度">
      <span data-state={root.state}>
        <GitBranch size={14} />
        <small>整体</small>
        <strong>{rootStateLabel(root, receipt)}</strong>
      </span>
      <span data-state={completedTasks === tasks.length && tasks.length ? 'completed' : 'active'}>
        <ListChecks size={14} />
        <small>分工</small>
        <strong>{tasks.length ? `${completedTasks} / ${tasks.length} 已完成` : '等待安排'}</strong>
      </span>
      <span data-state={activeDispatches ? 'running' : 'completed'}>
        <Wrench size={14} />
        <small>协作执行</small>
        <strong>{dispatches.length ? `${activeDispatches} 正在工作 · ${settledDispatches} 已结束` : '等待伙伴开始'}</strong>
      </span>
      <div
        aria-label={tasks.length ? `分工完成 ${taskProgress}%` : '分工尚未拆分'}
        aria-valuemax={100}
        aria-valuemin={0}
        aria-valuenow={taskProgress}
        role="progressbar"
      >
        <span style={{ width: `${taskProgress}%` }} />
      </div>
    </section>
    <RoomParallelWorkPhase
      dispatches={dispatches}
      participantLabels={participantLabels}
      participantProgress={participantProgress}
      root={root}
      tasks={tasks}
    />
    <div className="room-kernel-root__summary">
      <span><ShieldCheck size={14} /><small>帮大家对齐进度</small><strong>{participantLabel(root.facilitatorParticipantId, participantLabels)}</strong></span>
      <BudgetMetric icon={<Gauge size={14} />} label="协作轮次" used={budget?.usedDispatches} maximum={budget?.maxDispatches} />
      <BudgetMetric icon={<FileText size={14} />} label="上下文用量" used={budget?.usedTokens} maximum={budget?.maxTokens} />
      <BudgetMetric icon={<Clock3 size={14} />} label="运行时间" used={budget?.elapsedMs} maximum={budget?.maxWallTimeMs} formatter={durationLabel} />
    </div>
    <section className="room-kernel-root__receipts" aria-label="运行确认">
      <ReceiptSummary icon={<LockKeyhole size={14} />} label="上下文" receipt={contextReceipt} />
      <ReceiptSummary icon={<Wrench size={14} />} label="技能与工具" receipt={capabilityReceipt} />
      <span><CircleCheck size={14} /><small>任务验收</small><strong>{receipt ? qualityGateLabel(receipt) : '等待伙伴和工具结束'}</strong></span>
      <span><ShieldCheck size={14} /><small>额外交付检查</small><strong>{receipt ? deliveryGateLabel(receipt) : '等待任务结束'}</strong></span>
      <span data-receipt-state={commandReceipt?.status ?? cancelReceipt?.status}><Square size={14} /><small>停止状态</small><strong>{commandReceipt ? receiptStatusLabel(commandReceipt) : cancelReceipt ? receiptStatusLabel(cancelReceipt) : commandTransport ? '尚未请求' : '当前连接没有停止权限'}</strong></span>
    </section>
    <TaskOwnershipFlow
      participantLabels={participantLabels}
      receipts={ownershipReceipts}
      tasks={tasks}
    />
    {sharedCheckVisible ? (
      <RoomSharedFinalCheck
        individualTasks={individualTasks}
        participantLabels={participantLabels}
        receipt={receipt}
        reviewTasks={reviewTasks}
        root={root}
      />
    ) : null}
    {commandError ? <p className="room-kernel-control__command-error" role="alert">{commandError}</p> : null}
    <div className="room-kernel-root__planes">
      <section className="room-kernel-posts" aria-label="公开结果与回复">
        <header>
          <strong>{terminal ? '最终回复' : '公开结果与回复'}</strong>
          <small>{terminal ? '第 3 步 · 最后结果' : '最新公开进度保持可见'}</small>
        </header>
        {visiblePosts.length ? visiblePosts.map((post, index) => (
          <article
            data-latest={index === 0 || undefined}
            data-terminal={terminal && index === 0 || undefined}
            key={post!.postId}
          >
            <span>
              <b>{postKindLabel(post!.kind)}</b>
              <small>{publicActorLabel(post!.authorActorRef, participantLabels)}</small>
              <time dateTime={new Date(post!.createdAtMs).toISOString()}>
                {roomPublicTimeFormatter.format(new Date(post!.createdAtMs))}
              </time>
            </span>
            <p>{post!.content}</p>
          </article>
        )) : <p className="room-kernel-control__empty">还没有公开结果。</p>}
      </section>
      <section className="room-kernel-sessions" aria-label="伙伴运行状态">
        <header>
          <strong>伙伴运行状态</strong>
          <small>只显示公开进度摘要，不公开私有思考或对话正文</small>
        </header>
        {sessions.length ? sessions.map((session) => {
          const dispatch = dispatches.find((item) => item.targetSessionId === session.sessionId);
          const publicUpdate = participantProgress
            .filter((item) => (
              item.rootId === root.rootId
              && (
                item.sourceSessionId === session.sessionId
                || Boolean(dispatch && item.participantId === dispatch.targetParticipantId)
              )
            ))
            .sort((left, right) => right.updatedAtMs - left.updatedAtMs)[0];
          return <details data-state={session.state} key={session.sessionId}>
            <summary>
              <LockKeyhole size={13} />
              <span>
                <strong>{dispatch
                  ? participantLabel(dispatch.targetParticipantId, participantLabels)
                  : '伙伴运行'}</strong>
                <small>{sessionStateLabel(session.state)} · 第 {session.generation} 次尝试</small>
              </span>
              {publicUpdate ? (
                <span className="room-kernel-sessions__public-update" data-kind={publicUpdate.kind}>
                  <strong>{PUBLIC_PROGRESS_KIND_LABELS[publicUpdate.kind]}</strong>
                  <span>{publicUpdate.summary}</span>
                  <time dateTime={new Date(publicUpdate.updatedAtMs).toISOString()}>
                    {roomPublicTimeFormatter.format(new Date(publicUpdate.updatedAtMs))}
                  </time>
                </span>
              ) : null}
            </summary>
            <dl>
              <div><dt>运行状态</dt><dd>{sessionStateLabel(session.state)}</dd></div>
              <div><dt>公开范围</dt><dd>只公开状态和公开摘要，不公开私有对话正文</dd></div>
              {session.capabilityManifest ? <>
                <div><dt>可用能力</dt><dd>{session.capabilityManifest.status === 'active' ? '当前可用' : '已撤销'} · 第 {session.capabilityManifest.capabilityEpoch} 版</dd></div>
                <div><dt>工作配置</dt><dd>{session.capabilityManifest.status === 'active' ? '已加载当前配置' : '配置已停止使用'}</dd></div>
              </> : null}
              {session.requirementObservation ? <>
                <div><dt>需求准备</dt><dd>{requirementObservationStateLabel(session.requirementObservation.state)}</dd></div>
                <div><dt>验证记录</dt><dd>{session.requirementObservation.warnings.length ? `观察提醒 ${session.requirementObservation.warnings.length} 项` : `${session.requirementObservation.proofReceiptRefs.length} 条系统记录`}</dd></div>
              </> : null}
            </dl>
          </details>;
        }) : <p className="room-kernel-control__empty">当前没有伙伴运行记录。</p>}
      </section>
    </div>
    {requirements ? <details className="room-kernel-root__evidence">
      <summary><FileText size={15} /><span><strong>查看验收与证据详情</strong><small>原始需求、验收标准和系统核验记录</small></span></summary>
      <RoomRequirementsControlPlane projection={requirements} />
    </details> : null}
  </article>;
}

type ParticipantLaneState = 'idle' | 'waiting' | 'running' | 'review' | 'blocked' | 'settled';

const PARTICIPANT_LANE_STATE_LABELS: Record<ParticipantLaneState, string> = {
  idle: '已加入',
  waiting: '等待中',
  running: '执行中',
  review: '验收中',
  blocked: '需要关注',
  settled: '已落定',
};

function RoomParallelWorkPhase({
  dispatches,
  participantLabels,
  participantProgress,
  root,
  tasks,
}: {
  dispatches: RoomKernelProjection['dispatchesById'][string][];
  participantLabels: Record<string, string>;
  participantProgress: RoomParticipantPublicProgressProjection[];
  root: RootProjection;
  tasks: RoomTaskV3[];
}) {
  const participantIds = [...new Set([
    ...Object.keys(participantLabels),
    ...tasks.map((task) => task.currentOwnerParticipantId),
    ...dispatches.map((dispatch) => dispatch.targetParticipantId),
    root.facilitatorParticipantId,
    root.reporterParticipantId ?? '',
  ].filter(Boolean))];
  if (!participantIds.length) return null;

  return <section className="room-kernel-parallel-phase" aria-label="伙伴并行进度">
    <header>
      <span><small>第 1 步</small><strong>各自工作</strong></span>
      <p>每位伙伴平等展示自己的部分、当前状态和公开进度。</p>
      <b>{participantIds.length} 位伙伴</b>
    </header>
    <div className="room-kernel-participant-lanes">
      {participantIds.map((participantId) => {
        const ownedTasks = tasks.filter((task) => task.currentOwnerParticipantId === participantId);
        const ownedDispatches = dispatches.filter((dispatch) => dispatch.targetParticipantId === participantId);
        const sessionIds = new Set(ownedDispatches.map((dispatch) => dispatch.targetSessionId));
        const publicUpdate = participantProgress.find((item) => (
          item.rootId === root.rootId
          && (
            item.participantId === participantId
            || sessionIds.has(item.sourceSessionId)
          )
        ));
        const hasOwnWork = ownedTasks.length > 0 || ownedDispatches.length > 0 || Boolean(publicUpdate);
        const state = participantLaneState(ownedTasks, ownedDispatches, publicUpdate);
        const additionalRoles = [
          participantId === root.facilitatorParticipantId ? '同时帮大家对齐进度' : '',
          participantId === root.reporterParticipantId ? '同时整理共同结果' : '',
        ].filter(Boolean);
        const roleSummary = [
          ...additionalRoles,
          hasOwnWork ? '完成自己的部分' : '等待自己的部分开始',
        ].join(' · ');
        return <article
          className="room-kernel-participant-lane"
          data-participant-id={participantId}
          data-state={state}
          key={participantId}
        >
          <header>
            <UserRound size={16} />
            <span>
              <strong>{participantLabel(participantId, participantLabels)}</strong>
              <small>{roleSummary}</small>
            </span>
            <i>{PARTICIPANT_LANE_STATE_LABELS[state]}</i>
          </header>
          <div className="room-kernel-participant-lane__tasks">
            <strong>当前分工</strong>
            {ownedTasks.length ? <ul>{ownedTasks.map((task) => (
              <li data-state={task.state} key={task.taskId}>
                <span>{task.objective}</span>
                <small>{taskStateLabel(task.state)}</small>
              </li>
            ))}</ul> : <p>目前没有单独分到的部分</p>}
          </div>
          <p className="room-kernel-participant-lane__dispatch">
            <GitBranch size={13} />
            <span>{ownedDispatches.length
              ? `${ownedDispatches.filter((item) => ['leased', 'running'].includes(item.state)).length} 项正在推进 · 共 ${ownedDispatches.length} 项`
              : '等待开始自己的部分'}</span>
          </p>
          <div className="room-kernel-participant-lane__public">
            <strong>{publicUpdate
              ? PUBLIC_PROGRESS_KIND_LABELS[publicUpdate.kind]
              : '公开进度'}</strong>
            <p>{publicUpdate ? roomParticipantPublicProgressSummary(publicUpdate) : '等待这位伙伴发布公开状态、思路摘要或工具进度。'}</p>
            {publicUpdate ? (
              <time dateTime={new Date(publicUpdate.updatedAtMs).toISOString()}>
                {roomPublicTimeFormatter.format(new Date(publicUpdate.updatedAtMs))}
              </time>
            ) : null}
          </div>
        </article>;
      })}
    </div>
  </section>;
}

function RoomSharedFinalCheck({
  individualTasks,
  participantLabels,
  receipt,
  reviewTasks,
  root,
}: {
  individualTasks: RoomTaskV3[];
  participantLabels: Record<string, string>;
  receipt?: RoomKernelReceiptV1;
  reviewTasks: RoomTaskV3[];
  root: RootProjection;
}) {
  const completedReviews = reviewTasks.filter((task) => task.state === 'completed').length;
  const needsAttention = [...individualTasks, ...reviewTasks].some((task) => (
    ['failed', 'cancelled', 'blocked'].includes(task.state)
  ));
  const state = root.isFinal ? 'complete' : needsAttention ? 'attention' : 'checking';
  return <section
    aria-label="一起检查"
    className="room-kernel-shared-check"
    data-phase="shared-final-check"
    data-state={state}
  >
    <header>
      <span><small>第 2 步</small><strong>一起检查</strong></span>
      <i>{root.isFinal ? '完成确认已到达' : needsAttention ? '有结果需要核对' : '伙伴正在互相检查'}</i>
    </header>
    <p>{root.isFinal
      ? '每个人的部分都已完成检查；最终回复显示在下方公开结果中。'
      : reviewTasks.length
        ? `${completedReviews} / ${reviewTasks.length} 位伙伴已经完成检查。`
        : '每个人都完成了自己的部分，正在等待伙伴开始互相检查。'}</p>
    <dl>
      <div><dt>各自工作</dt><dd>{individualTasks.filter((task) => task.state === 'completed').length} / {individualTasks.length}</dd></div>
      <div><dt>一起检查</dt><dd>{completedReviews} / {reviewTasks.length || '等待开始'}</dd></div>
      <div><dt>整理共同结果</dt><dd>{root.reporterParticipantId
        ? participantLabel(root.reporterParticipantId, participantLabels)
        : '等待系统确认'}</dd></div>
      <div><dt>最终确认</dt><dd>{receipt ? qualityGateLabel(receipt) : '等待完成确认'}</dd></div>
    </dl>
  </section>;
}

function participantLaneState(
  tasks: RoomTaskV3[],
  dispatches: RoomKernelProjection['dispatchesById'][string][],
  publicUpdate?: RoomParticipantPublicProgressProjection,
): ParticipantLaneState {
  if (
    tasks.some((task) => ['blocked', 'failed'].includes(task.state))
    || dispatches.some((dispatch) => ['dead_letter', 'failed', 'unknown'].includes(dispatch.state))
    || publicUpdate?.status === 'failed'
  ) return 'blocked';
  if (tasks.some((task) => task.state === 'review')) return 'review';
  if (
    tasks.some((task) => task.state === 'active')
    || dispatches.some((dispatch) => ['leased', 'running'].includes(dispatch.state))
    || publicUpdate?.status === 'running'
  ) return 'running';
  if (
    tasks.some((task) => ['pending', 'waiting'].includes(task.state))
    || dispatches.some((dispatch) => ['pending', 'retry_wait', 'timer_wait'].includes(dispatch.state))
    || publicUpdate?.status === 'waiting'
  ) return 'waiting';
  if (
    (tasks.length > 0 && tasks.every((task) => ['completed', 'cancelled'].includes(task.state)))
    || (dispatches.length > 0 && dispatches.every((dispatch) => ['committed', 'cancelled'].includes(dispatch.state)))
  ) return 'settled';
  return 'idle';
}

function TaskOwnershipFlow({
  participantLabels,
  receipts,
  tasks,
}: {
  participantLabels: Record<string, string>;
  receipts: RoomKernelReceiptV1[];
  tasks: RoomTaskV3[];
}) {
  if (!tasks.length) return null;
  return <details className="room-kernel-tasks" aria-label="分工与交接详情">
    <summary>
      <span><strong>查看分工与交接详情</strong><small>展开后可查看系统记录和内部标识</small></span>
      <b>{tasks.length} 项</b>
    </summary>
    <ol>{tasks.map((task) => {
      const transfers = receipts.filter((receipt) => receipt.details.taskId === task.taskId);
      return <li key={task.taskId} data-task-state={task.state}>
        <article>
          <header>
            <span><UserRound size={15} /><strong>{task.objective}</strong></span>
            <i>{taskStateLabel(task.state)}</i>
          </header>
          <dl>
            <div><dt>当前伙伴</dt><dd>{participantLabel(task.currentOwnerParticipantId, participantLabels)}</dd></div>
            <div><dt>分工关系</dt><dd>{task.parentTaskId ? '从上一项分工继续' : '直接分配'}</dd></div>
            <div><dt>交接版本</dt><dd>第 {task.ownershipRevision} 版</dd></div>
          </dl>
          <div className="room-kernel-tasks__handoffs">
            <strong>交接记录</strong>
            {transfers.length ? transfers.map((receipt) => <p key={receipt.receiptId}>
              <span>{participantLabel(textDetail(receipt, 'fromParticipantId'), participantLabels)}</span>
              <ArrowRight size={13} aria-hidden="true" />
              <span>{participantLabel(textDetail(receipt, 'toParticipantId'), participantLabels)}</span>
              <small>第 {integerDetail(receipt, 'ownershipRevision')} 版</small>
            </p>) : <small>尚未发生交接</small>}
          </div>
        </article>
      </li>;
    })}</ol>
  </details>;
}

function taskStateLabel(value: RoomTaskV3['state']): string {
  return ({
    pending: '待开始',
    active: '执行中',
    review: '一起检查',
    waiting: '等待中',
    blocked: '已阻塞',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
  } as const)[value];
}

function participantLabel(participantId: string, labels: Record<string, string>): string {
  return labels[participantId] || '协作伙伴';
}

function textDetail(receipt: RoomKernelReceiptV1, field: string): string {
  const value = receipt.details[field];
  return typeof value === 'string' && value ? value : '未知伙伴';
}

function integerDetail(receipt: RoomKernelReceiptV1, field: string): number {
  const value = receipt.details[field];
  return typeof value === 'number' && Number.isInteger(value) ? value : 0;
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
  return <span>{icon}<small>{label}</small><strong>{receipt ? runtimeReceiptStatusLabel(receipt.status) : '未上报'}</strong></span>;
}

function rootTaskTitle(
  root: RootProjection,
  requirements?: RoomRequirementsReadProjection,
): string {
  const original = requirements?.anchors[0]?.originalText.trim();
  if (!original) return '本轮协作任务';
  const firstLine = original.split(/\r?\n/u, 1)[0]?.trim() ?? '';
  return firstLine.length > 120 ? `${firstLine.slice(0, 117)}...` : firstLine;
}

function rootStateLabel(root: RootProjection, receipt?: RoomKernelReceiptV1): string {
  if (root.state === 'failed') return '未完成';
  if (root.state === 'cancelled') return '已停止';
  if (root.state === 'cancelled_with_unknowns') return '已停止，后台状态待确认';
  if (root.isFinal) return deliveryGatePassed(receipt) ? '已完成并通过检查' : '已结束，仍有检查提醒';
  return ({ pending: '排队中', running: '执行中', waiting: '等待中', blocked: '已阻塞', cancelling: '正在停止', completed: '已完成' } as Partial<Record<RootProjection['state'], string>>)[root.state] ?? '状态待确认';
}

function surfaceTargets(detail: Record<string, unknown>): string {
  const targetIds = Array.isArray(detail.targetIds) ? detail.targetIds.filter((item): item is string => typeof item === 'string') : [];
  return targetIds.length ? `${targetIds.length} 个后台目标` : '尚未确认具体目标';
}

function deliveryGatePassed(receipt?: RoomKernelReceiptV1): boolean {
  const observation = receipt?.details?.deliveryGateObservation;
  return typeof observation === 'object' && observation !== null
    && 'gateStatus' in observation && observation.gateStatus === 'observed_pass';
}

function deliveryGateLabel(receipt: RoomKernelReceiptV1): string {
  if (deliveryGatePassed(receipt)) return '伙伴结果和验证记录已通过检查';
  const observation = receipt.details?.deliveryGateObservation;
  if (typeof observation === 'object' && observation !== null && 'gateStatus' in observation) {
    return observation.gateStatus === 'warn_blocked' ? '发现阻塞或未知项' : '结果还没有检查完';
  }
  return '等待一起检查结果';
}

function qualityGateLabel(receipt: RoomKernelReceiptV1): string {
  const verdict = receipt.details?.qualityGateVerdict;
  if (verdict === 'ready_to_deliver') return '全部验收项已有有效证据';
  if (verdict === 'not_ready') return '还有验收项未完成';
  return '系统已完成一起检查';
}

function sessionStateLabel(value: string): string {
  return ({ idle: '空闲', queued: '排队中', running: '执行中', completed: '已完成', failed: '未完成', cancelled: '已停止' } as Record<string, string>)[value] ?? '状态更新中';
}

function requirementObservationStateLabel(value: 'prepared' | 'active' | 'terminal'): string {
  return ({ prepared: '已经准备', active: '正在跟进', terminal: '已经结束' } as const)[value];
}

function runtimeReceiptStatusLabel(value: RuntimeReceiptSummary['status']): string {
  return ({ pending: '待封存', sealed: '已封存', rejected: '已拒绝', missing: '缺失' } as const)[value];
}

function roomRootRecency(root: RootProjection): number {
  return Math.max(root.updatedAtMs, root.createdAtMs);
}

function roomRootIsTerminal(root: RootProjection): boolean {
  return ['completed', 'failed', 'cancelled', 'cancelled_with_unknowns'].includes(root.state);
}

function terminalRootLabel(root: RootProjection): string {
  if (root.state === 'completed') return '任务已完成';
  if (root.state === 'failed') return '任务未完成';
  return '任务已停止';
}

function cancellationSurfaceLabel(value: string): string {
  return ({
    provider: '模型服务',
    tool: '工具运行',
    exec: '命令执行',
    retry: '重试任务',
    compaction: '上下文整理',
    branch_summary: '工作摘要',
    timer: '等待计时',
    continuation: '后续任务',
    session: '伙伴运行',
  } as Record<string, string>)[value] ?? '后台工作';
}

function cancellationSurfaceStateLabel(value: string): string {
  return ({
    requested: '正在停止',
    acknowledged: '已收到停止请求',
    terminated: '已停止',
    unknown: '等待确认',
  } as Record<string, string>)[value] ?? '仍在核对';
}

function roomCommandError(error: unknown): string {
  const message = error instanceof Error ? error.message.trim() : '';
  if (/\b(?:kernel|root|receipt|generation|command)\b/iu.test(message)) {
    return '停止结果与当前任务状态不一致，请刷新任务进度后重试';
  }
  return message || '停止请求没有收到确认，请稍后重试';
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
  return ({ user_request: '用户请求', answer: '回答', finding: '发现', decision: '决定', question: '问题', result: '结果', blocker: '阻塞', announcement: '公告' } as Record<string, string>)[value] ?? '公开更新';
}
function publicActorLabel(actorRef: string, labels: Record<string, string>): string {
  if (labels[actorRef]) return labels[actorRef];
  return actorRef && !actorRef.includes(':') ? actorRef : '协作伙伴';
}

function compactNumber(value: number): string {
  return new Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 1 }).format(value);
}

function durationLabel(value: number): string {
  if (value < 1_000) return `${value}ms`;
  const seconds = Math.round(value / 1_000);
  return seconds < 60 ? `${seconds}s` : `${Math.round(seconds / 60)}m`;
}
