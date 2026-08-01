import {
  ArrowDown,
  ArrowUp,
  CirclePause,
  CirclePlay,
  Flag,
  ListChecks,
  Pencil,
  Plus,
  RotateCcw,
  ShieldCheck,
  Trash2,
  X,
} from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { useControlTransport } from '@/app/control-transport';
import { Button, IconButton, Input, TextArea } from '@/components/primitives';
import type { AgentPlanProjection } from '@/contracts/agent-reducer';
import type {
  ActGate,
  AgentWorkflowStateV1,
  Goal,
  Plan,
  PlanItem,
} from '@/contracts/generated/agent-workflow-state.v1';
import type { JsonValue } from '@/platform/transport';
import { AgentPlanCard } from '../timeline/AgentPlanCard';

type MutationInput = {
  sessionId: string;
  target: 'plan' | 'goal';
  body: { [key: string]: JsonValue };
};

export function AgentWorkflowPanel({
  sessionId,
  fallbackPlan,
  fallbackGoal,
  fallbackActGate,
  currentTurnStartedAtMs,
  onWorkflowResolved,
}: {
  sessionId: string;
  fallbackPlan?: AgentPlanProjection;
  fallbackGoal?: Goal;
  fallbackActGate?: ActGate;
  currentTurnStartedAtMs?: number;
  onWorkflowResolved?: (workflow: AgentWorkflowStateV1) => void;
}) {
  const transport = useControlTransport();
  const queryClient = useQueryClient();
  const workflowQuery = useQuery({
    queryKey: ['agent', 'workflow', sessionId],
    queryFn: async ({ signal }) => {
      const next = await transport.request<AgentWorkflowStateV1>({
        pathId: 'agent.session.workflow.get',
        params: { sessionId },
        signal,
      });
      return assertWorkflowOwner(next, sessionId);
    },
    enabled: Boolean(sessionId),
    retry: false,
    staleTime: 1_000,
  });
  const hasLivePlan = Boolean(fallbackPlan);
  const hasLiveGoal = Boolean(fallbackGoal);
  const hasLiveActGate = Boolean(fallbackActGate);
  const hasLiveWorkflow = hasLivePlan || hasLiveGoal || hasLiveActGate;
  const workflow = useMemo(() => {
    const liveWorkflow = fallbackWorkflow(
      sessionId,
      fallbackPlan,
      fallbackGoal,
      fallbackActGate,
    );
    return mergeWorkflowState(
      workflowQuery.data,
      liveWorkflow,
      hasLivePlan,
      hasLiveGoal,
      hasLiveActGate,
    );
  }, [
    fallbackActGate,
    fallbackGoal,
    fallbackPlan,
    hasLiveActGate,
    hasLiveGoal,
    hasLivePlan,
    sessionId,
    workflowQuery.data,
  ]);
  useEffect(() => {
    onWorkflowResolved?.(workflow);
  }, [onWorkflowResolved, workflow]);
  const mutation = useMutation({
    mutationFn: async ({ sessionId: ownerSessionId, target, body }: MutationInput) => {
      const next = await transport.request<AgentWorkflowStateV1>({
        pathId: target === 'plan'
          ? 'agent.session.plan.mutate'
          : 'agent.session.goal.mutate',
        params: { sessionId: ownerSessionId },
        body,
      });
      return assertWorkflowOwner(next, ownerSessionId);
    },
    onSuccess: (next, variables) => {
      queryClient.setQueryData(['agent', 'workflow', variables.sessionId], next);
    },
  });

  if (workflowQuery.isPending && !workflowQuery.data && !hasLiveWorkflow) {
    return (
      <div className="agent-workflow-panel" aria-label="任务与目标">
        <section className="agent-workflow-section">
          <p role="status">正在读取计划与长期目标</p>
        </section>
      </div>
    );
  }

  if (
    workflowQuery.error
    && !workflowQuery.data
    && !hasLiveWorkflow
    && !isAbsentWorkflow(workflowQuery.error)
  ) {
    return (
      <div className="agent-workflow-panel" aria-label="任务与目标">
        <section className="agent-workflow-section">
          <div className="agent-workflow-recovery" role="alert">
            <span>暂时无法读取最新计划与长期目标。为避免误用旧状态，相关操作已暂停。</span>
            <Button
              size="small"
              loading={workflowQuery.isFetching}
              onClick={() => void workflowQuery.refetch()}
            >
              重新读取
            </Button>
          </div>
        </section>
      </div>
    );
  }

  if (
    workflowQuery.error
    && !workflowQuery.data
    && !hasLiveWorkflow
    && isAbsentWorkflow(workflowQuery.error)
  ) {
    return (
      <div className="agent-workflow-panel" aria-label="任务与目标">
        <section className="agent-workflow-section">
          <div className="agent-workflow-recovery" data-state="room-managed" role="status">
            <span>当前没有需要单独维护的计划。如果这段工作来自协作空间，分工、公开进度和最终回复会继续在那里显示。</span>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="agent-workflow-panel" aria-label="任务与目标">
      {workflowQuery.error && !isAbsentWorkflow(workflowQuery.error) ? (
        <div className="agent-workflow-recovery" role="alert">
          <span>
            {workflowQuery.data
              ? '状态刷新失败，当前显示上一次确认的结果。'
              : '实时读取失败，当前继续显示这段对话已经确认的计划与目标。'}
          </span>
          <Button
            size="small"
            loading={workflowQuery.isFetching}
            onClick={() => void workflowQuery.refetch()}
          >
            重新读取
          </Button>
        </div>
      ) : null}
      <PlanReview
        key={`plan:${sessionId}`}
        plan={workflow.plan}
        gate={workflow.actGate}
        currentTurnStartedAtMs={currentTurnStartedAtMs}
        pending={mutation.isPending && mutation.variables?.sessionId === sessionId}
        error={mutation.variables?.sessionId === sessionId && mutation.variables.target === 'plan'
          ? mutation.error
          : null}
        mutate={(body) => mutation.mutateAsync({ sessionId, target: 'plan', body })}
      />
      <GoalMode
        key={`goal:${sessionId}`}
        goal={workflow.goal}
        pending={mutation.isPending && mutation.variables?.sessionId === sessionId}
        error={mutation.variables?.sessionId === sessionId && mutation.variables.target === 'goal'
          ? mutation.error
          : null}
        mutate={(body) => mutation.mutateAsync({ sessionId, target: 'goal', body })}
      />
    </div>
  );
}

function PlanReview({
  plan,
  gate,
  currentTurnStartedAtMs,
  pending,
  error,
  mutate,
}: {
  plan: Plan;
  gate: ActGate;
  currentTurnStartedAtMs?: number;
  pending: boolean;
  error: unknown;
  mutate: (body: { [key: string]: JsonValue }) => Promise<unknown>;
}) {
  const [editing, setEditing] = useState(false);
  const [returning, setReturning] = useState(false);
  const [confirmingAction, setConfirmingAction] = useState<'cancel' | 'reset' | null>(null);
  const [reviewFeedback, setReviewFeedback] = useState('');
  const [title, setTitle] = useState(plan.title);
  const [items, setItems] = useState<PlanItem[]>(plan.items);
  useEffect(() => {
    if (editing) return;
    setTitle(plan.title);
    setItems(plan.items);
  }, [editing, plan.revision, plan.title, plan.items]);
  useEffect(() => {
    if (plan.status !== 'draft') {
      setEditing(false);
      return;
    }
    if (plan.items.length === 0) setEditing(true);
  }, [plan.status, plan.items.length]);
  useEffect(() => {
    setReturning(false);
    setReviewFeedback('');
    setConfirmingAction(null);
  }, [plan.revision]);

  const canSubmit = title.trim().length > 0 && items.length > 0
    && items.every((item) => item.title.trim().length > 0);
  const canAcceptCompletion = !['completed', 'cancelled'].includes(plan.status)
    && plan.items.length > 0
    && plan.items.every((item) => item.status === 'completed');
  const runMutation = (
    body: { [key: string]: JsonValue },
    onSuccess?: () => void,
  ) => {
    void mutate(body).then(onSuccess).catch(() => undefined);
  };
  const save = (action: 'save' | 'submit_review') => runMutation({
    action,
    expectedRevision: plan.revision,
    title: title.trim(),
    items: items.map((item) => ({
      id: item.id.startsWith('draft:') ? '' : item.id,
      title: item.title.trim(),
      status: item.status,
    })),
  }, () => setEditing(false));
  const returnToDraft = () => runMutation({
    action: 'return_to_draft',
    expectedRevision: plan.revision,
    note: reviewFeedback.trim(),
  }, () => {
    setReturning(false);
    setReviewFeedback('');
  });

  return (
    <section className="agent-workflow-section agent-workflow-plan" aria-label="计划审阅与执行">
      <header>
        <span className="agent-workflow-section__icon"><ListChecks size={16} /></span>
        <span><strong>执行计划</strong><small>{planStatusLabel(plan.status)}</small></span>
        {plan.status === 'draft' && !editing ? (
          <IconButton size="small" icon={<Pencil size={15} />} label="编辑计划" onClick={() => setEditing(true)} tooltip />
        ) : null}
      </header>

      {editing ? (
        <div className="agent-plan-editor">
          <label>
            <span>计划标题</span>
            <Input aria-label="计划标题" maxLength={160} value={title} onChange={(event) => setTitle(event.target.value)} />
          </label>
          <ol>
            {items.map((item, index) => (
              <li key={item.id}>
                <span>{index + 1}</span>
                <Input
                  aria-label={`计划步骤 ${index + 1}`}
                  maxLength={240}
                  value={item.title}
                  onChange={(event) => setItems((current) => current.map((candidate, itemIndex) => (
                    itemIndex === index ? { ...candidate, title: event.target.value } : candidate
                  )))}
                />
                <span className="agent-plan-editor__actions">
                  <IconButton size="small" icon={<ArrowUp size={14} />} label={`上移步骤 ${index + 1}`} disabled={index === 0} onClick={() => setItems(moveItem(items, index, index - 1))} tooltip />
                  <IconButton size="small" icon={<ArrowDown size={14} />} label={`下移步骤 ${index + 1}`} disabled={index === items.length - 1} onClick={() => setItems(moveItem(items, index, index + 1))} tooltip />
                  <IconButton size="small" icon={<Trash2 size={14} />} label={`删除步骤 ${index + 1}`} onClick={() => setItems(items.filter((_, itemIndex) => itemIndex !== index))} tooltip />
                </span>
              </li>
            ))}
          </ol>
          <Button
            className="agent-workflow-add"
            size="small"
            variant="quiet"
            leadingIcon={<Plus size={15} />}
            onClick={() => setItems([...items, draftPlanItem(items.length)])}
          >
            添加步骤
          </Button>
          <div className="agent-workflow-actions">
            {plan.items.length ? <Button size="small" variant="quiet" onClick={() => setEditing(false)}>取消</Button> : null}
            <Button size="small" loading={pending} disabled={!canSubmit} onClick={() => save('save')}>保存草案</Button>
            <Button size="small" variant="primary" loading={pending} disabled={!canSubmit} leadingIcon={<ShieldCheck size={15} />} onClick={() => save('submit_review')}>提交审阅</Button>
          </div>
        </div>
      ) : (
        <>
          <p
            className="agent-workflow-plan__provenance"
            data-predates-turn={Boolean(
              currentTurnStartedAtMs
              && plan.updatedAtMs > 0
              && plan.updatedAtMs < currentTurnStartedAtMs
            ) || undefined}
          >
            <strong>计划来源</strong>
            <span>{planActorLabel(plan.actor)} · {formatWorkflowTime(plan.updatedAtMs)}</span>
            <small>
              {currentTurnStartedAtMs && plan.updatedAtMs > 0 && plan.updatedAtMs < currentTurnStartedAtMs
                ? '这份计划来自更早的对话回合，请确认它仍适合当前任务。'
                : '每轮开始前都会带入这份计划；你也可以在这里直接更新。'}
            </small>
          </p>
          <AgentPlanCard plan={plan} />
          <div className="agent-act-gate" data-open={gate.allowed || undefined}>
            {gate.allowed ? <ShieldCheck size={15} /> : <CirclePause size={15} />}
            <span>
              <strong>
                {gate.allowed
                  ? String(gate.reason) === 'user_execution_request'
                    ? '用户请求已允许继续'
                    : '已经可以执行'
                  : '执行条件未满足'}
              </strong>
              <small>{gate.message}</small>
            </span>
          </div>
          {returning ? (
            <div className="agent-plan-return-editor">
              <label>
                <span>退回意见</span>
                <TextArea
                  aria-describedby="agent-plan-return-help"
                  aria-label="计划退回意见"
                  autoFocus
                  maxLength={600}
                  rows={3}
                  value={reviewFeedback}
                  onChange={(event) => setReviewFeedback(event.target.value)}
                />
              </label>
              <small id="agent-plan-return-help">请说明需要修改的内容；意见会随草案保留给下一位编辑者。</small>
              <div className="agent-workflow-actions">
                <Button size="small" variant="quiet" disabled={pending} onClick={() => {
                  setReturning(false);
                  setReviewFeedback('');
                }}>保留当前版本</Button>
                <Button size="small" variant="primary" leadingIcon={<RotateCcw size={15} />} loading={pending} disabled={!reviewFeedback.trim()} onClick={returnToDraft}>发送退回意见</Button>
              </div>
            </div>
          ) : (
            <div className="agent-workflow-actions">
              {plan.status === 'review' && !canAcceptCompletion ? (
                <>
                  <Button size="small" variant="quiet" leadingIcon={<RotateCcw size={15} />} disabled={pending} onClick={() => setReturning(true)}>退回修改</Button>
                  <Button size="small" variant="primary" leadingIcon={<ShieldCheck size={15} />} loading={pending} onClick={() => runMutation({ action: 'approve', expectedRevision: plan.revision })}>批准计划</Button>
                </>
              ) : null}
              {plan.status === 'approved' && !canAcceptCompletion ? (
                <Button size="small" variant="quiet" leadingIcon={<RotateCcw size={15} />} disabled={pending} onClick={() => setReturning(true)}>退回修改</Button>
              ) : null}
              {plan.status === 'approved' && !canAcceptCompletion ? (
                <small className="agent-workflow-note">
                  首个经治理的工作区写操作成功后，计划会自动进入执行中。
                </small>
              ) : null}
              {canAcceptCompletion ? (
                <Button
                  size="small"
                  variant="primary"
                  leadingIcon={<ShieldCheck size={15} />}
                  loading={pending}
                  onClick={() => runMutation({ action: 'complete', expectedRevision: plan.revision })}
                >
                  验收并完成
                </Button>
              ) : null}
              {['approved', 'executing'].includes(plan.status) ? (
                confirmingAction === 'cancel' ? (
                  <>
                    <span className="agent-workflow-confirm">取消会停止执行并保留当前计划终态，确认继续？</span>
                    <Button size="small" variant="quiet" disabled={pending} onClick={() => setConfirmingAction(null)}>继续执行</Button>
                    <Button
                      size="small"
                      variant="danger"
                      leadingIcon={<X size={15} />}
                      loading={pending}
                      onClick={() => runMutation(
                        { action: 'cancel', expectedRevision: plan.revision },
                        () => setConfirmingAction(null),
                      )}
                    >
                      确认取消执行
                    </Button>
                  </>
                ) : (
                  <Button
                    size="small"
                    variant="quiet"
                    leadingIcon={<X size={15} />}
                    disabled={pending}
                    onClick={() => setConfirmingAction('cancel')}
                  >
                    取消执行
                  </Button>
                )
              ) : null}
              {['completed', 'cancelled'].includes(plan.status) ? (
                confirmingAction === 'reset' ? (
                  <>
                    <span className="agent-workflow-confirm">新计划会替换当前终态视图，确认继续？</span>
                    <Button size="small" variant="quiet" disabled={pending} onClick={() => setConfirmingAction(null)}>保留当前计划</Button>
                    <Button
                      size="small"
                      leadingIcon={<RotateCcw size={15} />}
                      loading={pending}
                      onClick={() => runMutation(
                        { action: 'reset', expectedRevision: plan.revision, title: '执行计划', items: [] },
                        () => setConfirmingAction(null),
                      )}
                    >
                      确认新建计划
                    </Button>
                  </>
                ) : (
                  <Button size="small" leadingIcon={<RotateCcw size={15} />} disabled={pending} onClick={() => setConfirmingAction('reset')}>新建计划</Button>
                )
              ) : null}
            </div>
          )}
        </>
      )}
      {error ? <p className="agent-workflow-error" role="alert">{publicError(error)}</p> : null}
    </section>
  );
}

function GoalMode({
  goal,
  pending,
  error,
  mutate,
}: {
  goal: Goal;
  pending: boolean;
  error: unknown;
  mutate: (body: { [key: string]: JsonValue }) => Promise<unknown>;
}) {
  const [cancelling, setCancelling] = useState(false);
  const [confirmingClear, setConfirmingClear] = useState(false);
  const [cancelReason, setCancelReason] = useState('');
  useEffect(() => {
    setCancelling(false);
    setConfirmingClear(false);
    setCancelReason('');
  }, [goal.revision]);

  const configured = goal.configured;
  const budgetRows = goalBudgetRows(goal);
  const persistedExpectations = goal.evidenceExpectations ?? [];
  const runMutation = (
    body: { [key: string]: JsonValue },
    onSuccess?: () => void,
  ) => {
    void mutate(body).then(onSuccess).catch(() => undefined);
  };

  return (
    <section className="agent-workflow-section agent-goal-mode" aria-label="长期目标">
      <header>
        <span className="agent-workflow-section__icon"><Flag size={16} /></span>
        <span><strong>长期目标</strong><small>{configured ? goalStatusLabel(goal.status) : '未设置'}</small></span>
      </header>

      {!configured ? (
        <div className="agent-goal-empty">
          <strong>直接在对话中描述你想完成的事</strong>
          <p>伙伴会逐项询问目标、交付物、验收方式与禁区，并提供可选择的答案；你只需选择或回复。</p>
          <small>澄清完成后，确认结果会显示在这里，不需要填写表单。</small>
        </div>
      ) : (
        <div className="agent-goal-summary" data-state={goal.status}>
          <p>{goal.objective}</p>
          {goal.successCriteria ? <div className="agent-goal-criteria"><strong>完成标准</strong><span>{goal.successCriteria}</span></div> : null}
          {persistedExpectations.length ? (
            <div className="agent-goal-criteria">
              <strong>证据预期</strong>
              <ul>{persistedExpectations.map((item, index) => <li key={`${index}:${item}`}>{item}</li>)}</ul>
            </div>
          ) : null}
          {budgetRows.length ? <div className="agent-goal-budget">{budgetRows.map((row) => (
            <div key={row.label}>
              <span><small>{row.label}</small><strong>{row.value}</strong></span>
              <i><b style={{ width: `${row.percent}%` }} /></i>
            </div>
          ))}</div> : <small className="agent-goal-unbounded">未设置预算上限</small>}
          {goal.completionAudit ? (
            <div className="agent-goal-audit">
              <strong><ShieldCheck size={14} />完成依据</strong>
              <p>{goal.completionAudit.summary}</p>
              {goal.completionAudit.evidence.map((item) => <small key={`${item.kind}:${item.reference}`}>{item.summary} · {item.reference}</small>)}
            </div>
          ) : null}
          {goal.cancellationAudit ? (
            <div className="agent-goal-audit agent-goal-audit--cancelled">
              <strong><CirclePause size={14} />取消记录</strong>
              <p>{goal.cancellationAudit.reason}</p>
              <small>{goal.cancellationAudit.cancelledBy} · {formatWorkflowTime(goal.cancellationAudit.createdAtMs)}</small>
            </div>
          ) : null}
          {cancelling ? (
            <div className="agent-goal-cancel-editor">
              <label>
                <span>取消原因</span>
                <TextArea aria-label="目标取消原因" autoFocus rows={3} maxLength={1_000} value={cancelReason} onChange={(event) => setCancelReason(event.target.value)} />
              </label>
              <small>取消会保留目标和审计记录；“删除目标”才会清除这些信息。</small>
              <div className="agent-workflow-actions">
                <Button size="small" variant="quiet" disabled={pending} onClick={() => {
                  setCancelling(false);
                  setCancelReason('');
                }}>继续保留目标</Button>
                <Button size="small" variant="danger" loading={pending} disabled={!cancelReason.trim()} onClick={() => runMutation(
                  { action: 'cancel', expectedRevision: goal.revision, reason: cancelReason.trim() },
                  () => setCancelling(false),
                )}>确认取消目标</Button>
              </div>
            </div>
          ) : (
            <div className="agent-workflow-actions">
              {goal.status === 'active' ? <Button size="small" variant="quiet" leadingIcon={<CirclePause size={15} />} loading={pending} onClick={() => runMutation({ action: 'pause', expectedRevision: goal.revision })}>暂停</Button> : null}
              {goal.status === 'paused' ? <Button size="small" leadingIcon={<CirclePlay size={15} />} loading={pending} onClick={() => runMutation({ action: 'resume', expectedRevision: goal.revision })}>恢复</Button> : null}
              {['active', 'paused'].includes(goal.status) ? <Button size="small" variant="quiet" disabled={pending} onClick={() => setCancelling(true)}>取消目标</Button> : null}
              {confirmingClear ? (
                <>
                  <span className="agent-workflow-confirm">永久删除目标、预算和审计记录？</span>
                  <Button size="small" variant="quiet" disabled={pending} onClick={() => setConfirmingClear(false)}>保留</Button>
                  <Button
                    size="small"
                    variant="danger"
                    loading={pending}
                    onClick={() => runMutation(
                      { action: 'clear', expectedRevision: goal.revision },
                      () => setConfirmingClear(false),
                    )}
                  >
                    确认删除
                  </Button>
                </>
              ) : (
                <Button size="small" variant="quiet" disabled={pending} onClick={() => setConfirmingClear(true)}>删除目标</Button>
              )}
            </div>
          )}
        </div>
      )}
      {error ? <p className="agent-workflow-error" role="alert">{publicError(error)}</p> : null}
    </section>
  );
}


function fallbackWorkflow(
  sessionId: string,
  plan?: AgentPlanProjection,
  goal?: Goal,
  actGate?: ActGate,
): AgentWorkflowStateV1 {
  const resolvedPlan = plan ?? emptyPlan(sessionId);
  const projectedPlan: Plan = {
    schemaVersion: 'rag-ime.agent-plan.v2',
    ...resolvedPlan,
    id: resolvedPlan.id || `plan:${sessionId}`,
    sessionId: resolvedPlan.sessionId || sessionId,
  };
  const projectedGoal = goal ?? emptyGoal(sessionId);
  return {
    schemaVersion: 'rag-ime.agent-workflow-state.v1',
    ok: true,
    sessionId,
    plan: projectedPlan,
    goal: projectedGoal,
    actGate: actGate && (!(plan && goal) || gateMatches(actGate, projectedPlan, projectedGoal))
      ? actGate
      : closedActGate(projectedPlan, projectedGoal),
  };
}

function mergeWorkflowState(
  queried: AgentWorkflowStateV1 | undefined,
  live: AgentWorkflowStateV1,
  hasLivePlan: boolean,
  hasLiveGoal: boolean,
  hasLiveActGate: boolean,
): AgentWorkflowStateV1 {
  if (!queried) return live;
  const useLivePlan = hasLivePlan && (
    live.plan.revision > queried.plan.revision
    || (
      live.plan.revision === queried.plan.revision
      && live.plan.updatedAtMs > queried.plan.updatedAtMs
    )
  );
  const useLiveGoal = hasLiveGoal && (
    live.goal.revision > queried.goal.revision
    || (
      live.goal.revision === queried.goal.revision
      && live.goal.updatedAtMs > queried.goal.updatedAtMs
    )
  );
  const plan = useLivePlan ? live.plan : queried.plan;
  const goal = useLiveGoal ? live.goal : queried.goal;
  const liveGateMatches = hasLiveActGate && gateMatches(live.actGate, plan, goal);
  const queriedGateMatches = gateMatches(queried.actGate, plan, goal);
  return {
    ...queried,
    plan,
    goal,
    actGate: liveGateMatches
      ? live.actGate
      : queriedGateMatches
        ? queried.actGate
        : closedActGate(plan, goal),
  };
}

function emptyPlan(sessionId: string): AgentPlanProjection {
  return {
    id: `plan:${sessionId}`,
    sessionId,
    revision: 0,
    title: '执行计划',
    status: 'draft',
    actor: 'agent',
    note: '',
    updatedAtMs: 0,
    editable: true,
    actApproved: false,
    items: [],
    counts: { total: 0, pending: 0, inProgress: 0, completed: 0 },
  };
}

function emptyGoal(sessionId: string): Goal {
  return {
    schemaVersion: 'rag-ime.agent-goal.v1',
    sessionId,
    configured: false,
    goalId: '',
    revision: 0,
    objective: '',
    successCriteria: '',
    evidenceExpectations: [],
    status: 'cleared',
    budget: { tokenLimit: null, timeLimitMs: null },
    usage: { tokens: 0, elapsedMs: 0 },
    remaining: { tokens: null, timeMs: null },
    budgetExceeded: false,
    completionAudit: null,
    cancellationAudit: null,
    updatedAtMs: 0,
  };
}

function closedActGate(plan: Plan, goal: Goal): ActGate {
  return {
    allowed: false,
    reason: 'plan_not_approved',
    message: '计划或目标刚刚更新，正在核对最新状态；请稍候再继续。',
    planRevision: plan.revision,
    goalRevision: goal.revision,
  };
}

function gateMatches(gate: ActGate, plan: Plan, goal: Goal): boolean {
  return gate.planRevision === plan.revision && gate.goalRevision === goal.revision;
}

function assertWorkflowOwner(
  workflow: AgentWorkflowStateV1,
  ownerSessionId: string,
): AgentWorkflowStateV1 {
  if (workflow.sessionId !== ownerSessionId) {
    throw new Error('返回的是另一段对话的结果，当前对话没有更新。');
  }
  return workflow;
}

function draftPlanItem(index: number): PlanItem {
  return {
    id: `draft:${Date.now()}:${index}`,
    title: '',
    status: 'pending',
    position: index + 1,
    sequence: 0,
    updatedAtMs: 0,
  };
}


function moveItem<T>(items: T[], from: number, to: number): T[] {
  if (to < 0 || to >= items.length) return items;
  const next = [...items];
  const [item] = next.splice(from, 1);
  if (!item) return items;
  next.splice(to, 0, item);
  return next;
}

function planActorLabel(actor: string): string {
  const normalized = actor.trim().toLowerCase();
  if (!normalized) return '来源未记录';
  if (normalized === 'agent') return '伙伴创建';
  if (normalized.includes('control-center')) return '你在这里更新';
  return '系统更新';
}

function formatWorkflowTime(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '时间未记录';
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value));
}

export function planStatusLabel(status: Plan['status']): string {
  return {
    draft: '草案',
    review: '待审阅',
    approved: '已批准',
    executing: '执行中',
    completed: '已完成',
    cancelled: '已取消',
  }[status];
}

export function goalStatusLabel(status: Goal['status']): string {
  return {
    active: '进行中',
    paused: '已暂停',
    completed: '已完成',
    cancelled: '已取消',
    cleared: '未设置',
  }[status];
}

function goalBudgetRows(goal: Goal): { label: string; value: string; percent: number }[] {
  const rows = [];
  if (goal.budget.tokenLimit) rows.push({
    label: '模型用量',
    value: `${formatCompact(goal.usage.tokens)} / ${formatCompact(goal.budget.tokenLimit)}`,
    percent: Math.min(100, Math.round((goal.usage.tokens / goal.budget.tokenLimit) * 100)),
  });
  if (goal.budget.timeLimitMs) rows.push({
    label: '时间',
    value: `${formatDuration(goal.usage.elapsedMs)} / ${formatDuration(goal.budget.timeLimitMs)}`,
    percent: Math.min(100, Math.round((goal.usage.elapsedMs / goal.budget.timeLimitMs) * 100)),
  });
  return rows;
}



function formatCompact(value: number): string {
  return new Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 1 }).format(value);
}

function formatDuration(value: number): string {
  const minutes = Math.round(value / 60_000);
  return minutes >= 60 ? `${Math.floor(minutes / 60)}时${minutes % 60}分` : `${minutes}分钟`;
}

function isAbsentWorkflow(error: unknown): boolean {
  if (typeof error !== 'object' || error === null) return false;
  const status = 'status' in error && typeof error.status === 'number'
    ? error.status
    : 'statusCode' in error && typeof error.statusCode === 'number'
      ? error.statusCode
      : 0;
  if (status === 404) return true;
  const message = error instanceof Error ? error.message : '';
  return /\b404\b|workflow (?:is )?not found|no workflow state|plan (?:does not exist|not found)/i.test(message);
}

function publicError(error: unknown): string {
  if (!(error instanceof Error)) return '操作失败，请刷新后重试。';
  if (/agent plan changed; refresh before saving/i.test(error.message)) {
    return '计划已由其他操作更新，当前已显示最新状态，请重试。';
  }
  if (/agent goal changed; refresh before saving/i.test(error.message)) {
    return '目标已由其他操作更新，当前已显示最新状态，请重试。';
  }
  return error.message.slice(0, 240);
}
