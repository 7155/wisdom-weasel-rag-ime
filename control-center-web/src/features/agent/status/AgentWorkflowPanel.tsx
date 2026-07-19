import {
  ArrowDown,
  ArrowUp,
  Check,
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
  target: 'plan' | 'goal';
  body: { [key: string]: JsonValue };
};

export function AgentWorkflowPanel({
  sessionId,
  fallbackPlan,
  fallbackGoal,
  fallbackActGate,
}: {
  sessionId: string;
  fallbackPlan?: AgentPlanProjection;
  fallbackGoal?: Goal;
  fallbackActGate?: ActGate;
}) {
  const transport = useControlTransport();
  const queryClient = useQueryClient();
  const workflowQuery = useQuery({
    queryKey: ['agent', 'workflow', sessionId],
    queryFn: ({ signal }) => transport.request<AgentWorkflowStateV1>({
      pathId: 'agent.session.workflow.get',
      params: { sessionId },
      signal,
    }),
    enabled: Boolean(sessionId),
    retry: false,
    staleTime: 1_000,
    refetchInterval: 5_000,
  });
  const workflow = workflowQuery.data ?? fallbackWorkflow(
    sessionId,
    fallbackPlan,
    fallbackGoal,
    fallbackActGate,
  );
  const mutation = useMutation({
    mutationFn: ({ target, body }: MutationInput) => transport.request<AgentWorkflowStateV1>({
      pathId: target === 'plan'
        ? 'agent.session.plan.mutate'
        : 'agent.session.goal.mutate',
      params: { sessionId },
      body,
    }),
    onSuccess: (next) => {
      queryClient.setQueryData(['agent', 'workflow', sessionId], next);
    },
  });

  return (
    <div className="agent-workflow-panel" aria-label="任务工作流">
      <PlanReview
        plan={workflow.plan}
        gate={workflow.actGate}
        pending={mutation.isPending}
        error={mutation.variables?.target === 'plan' ? mutation.error : null}
        mutate={(body) => mutation.mutateAsync({ target: 'plan', body })}
      />
      <GoalMode
        goal={workflow.goal}
        pending={mutation.isPending}
        error={mutation.variables?.target === 'goal' ? mutation.error : null}
        mutate={(body) => mutation.mutateAsync({ target: 'goal', body })}
      />
    </div>
  );
}

function PlanReview({
  plan,
  gate,
  pending,
  error,
  mutate,
}: {
  plan: Plan;
  gate: ActGate;
  pending: boolean;
  error: unknown;
  mutate: (body: { [key: string]: JsonValue }) => Promise<unknown>;
}) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(plan.title);
  const [items, setItems] = useState<PlanItem[]>(plan.items);
  useEffect(() => {
    if (editing) return;
    setTitle(plan.title);
    setItems(plan.items);
  }, [editing, plan.revision, plan.title, plan.items]);
  useEffect(() => {
    if (plan.status === 'draft' && plan.items.length === 0) setEditing(true);
  }, [plan.status, plan.items.length]);

  const canSubmit = title.trim().length > 0 && items.length > 0
    && items.every((item) => item.title.trim().length > 0);
  const save = (action: 'save' | 'submit_review') => mutate({
    action,
    expectedRevision: plan.revision,
    title: title.trim(),
    items: items.map((item) => ({
      id: item.id.startsWith('draft:') ? '' : item.id,
      title: item.title.trim(),
      status: item.status,
    })),
  }).then(() => setEditing(false));

  return (
    <section className="agent-workflow-section agent-workflow-plan" aria-label="Plan 审阅与执行门禁">
      <header>
        <span className="agent-workflow-section__icon"><ListChecks size={16} /></span>
        <span><strong>Plan</strong><small>{planStatusLabel(plan.status)}</small></span>
        {plan.status === 'draft' && !editing ? (
          <IconButton size="small" icon={<Pencil size={15} />} label="编辑 Plan" onClick={() => setEditing(true)} tooltip />
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
          <AgentPlanCard plan={plan} />
          <div className="agent-act-gate" data-open={gate.allowed || undefined}>
            {gate.allowed ? <ShieldCheck size={15} /> : <CirclePause size={15} />}
            <span><strong>{gate.allowed ? 'Act 已解锁' : 'Act 已锁定'}</strong><small>{gate.message}</small></span>
          </div>
          <div className="agent-workflow-actions">
            {plan.status === 'review' ? (
              <>
                <Button size="small" variant="quiet" leadingIcon={<RotateCcw size={15} />} loading={pending} onClick={() => mutate({ action: 'return_to_draft', expectedRevision: plan.revision })}>退回修改</Button>
                <Button size="small" variant="primary" leadingIcon={<ShieldCheck size={15} />} loading={pending} onClick={() => mutate({ action: 'approve', expectedRevision: plan.revision })}>批准进入 Act</Button>
              </>
            ) : null}
            {plan.status === 'approved' ? (
              <Button size="small" variant="quiet" leadingIcon={<RotateCcw size={15} />} loading={pending} onClick={() => mutate({ action: 'return_to_draft', expectedRevision: plan.revision })}>退回修改</Button>
            ) : null}
            {['approved', 'executing'].includes(plan.status) ? (
              <Button size="small" variant="quiet" leadingIcon={<X size={15} />} loading={pending} onClick={() => mutate({ action: 'cancel', expectedRevision: plan.revision })}>取消执行</Button>
            ) : null}
            {['completed', 'cancelled'].includes(plan.status) ? (
              <Button size="small" leadingIcon={<RotateCcw size={15} />} loading={pending} onClick={() => mutate({ action: 'reset', expectedRevision: plan.revision, title: '执行计划', items: [] })}>新建 Plan</Button>
            ) : null}
          </div>
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
  const [editing, setEditing] = useState(false);
  const [auditing, setAuditing] = useState(false);
  const [objective, setObjective] = useState(goal.objective);
  const [tokenBudget, setTokenBudget] = useState(goal.budget.tokenLimit?.toString() ?? '');
  const [timeMinutes, setTimeMinutes] = useState(goal.budget.timeLimitMs ? Math.round(goal.budget.timeLimitMs / 60_000).toString() : '');
  const [auditSummary, setAuditSummary] = useState('');
  const [evidenceKind, setEvidenceKind] = useState('test');
  const [evidenceSummary, setEvidenceSummary] = useState('');
  const [evidenceReference, setEvidenceReference] = useState('');
  useEffect(() => {
    if (editing) return;
    setObjective(goal.objective);
    setTokenBudget(goal.budget.tokenLimit?.toString() ?? '');
    setTimeMinutes(goal.budget.timeLimitMs ? Math.round(goal.budget.timeLimitMs / 60_000).toString() : '');
  }, [editing, goal.revision, goal.objective, goal.budget.tokenLimit, goal.budget.timeLimitMs]);

  const configured = goal.configured;
  const budgetRows = useMemo(() => goalBudgetRows(goal), [goal]);
  const saveGoal = () => mutate({
    action: configured ? 'update' : 'set',
    ...(configured ? { expectedRevision: goal.revision } : {}),
    objective: objective.trim(),
    tokenBudget: positiveNumberOrNull(tokenBudget),
    timeBudgetMs: positiveNumberOrNull(timeMinutes, 60_000),
  }).then(() => setEditing(false));
  const completeGoal = () => mutate({
    action: 'complete',
    expectedRevision: goal.revision,
    summary: auditSummary.trim(),
    evidence: [{
      kind: evidenceKind,
      summary: evidenceSummary.trim(),
      reference: evidenceReference.trim(),
    }],
  }).then(() => setAuditing(false));

  return (
    <section className="agent-workflow-section agent-goal-mode" aria-label="Goal Mode">
      <header>
        <span className="agent-workflow-section__icon"><Flag size={16} /></span>
        <span><strong>Goal</strong><small>{configured ? goalStatusLabel(goal.status) : '未设置'}</small></span>
        {configured && ['active', 'paused'].includes(goal.status) && !editing && !auditing ? (
          <IconButton size="small" icon={<Pencil size={15} />} label="编辑 Goal" onClick={() => setEditing(true)} tooltip />
        ) : null}
      </header>

      {!configured && !editing ? (
        <div className="agent-goal-empty">
          <p>为这条对话设置长期目标和执行预算。</p>
          <Button size="small" leadingIcon={<Plus size={15} />} onClick={() => setEditing(true)}>设置 Goal</Button>
        </div>
      ) : null}

      {editing ? (
        <div className="agent-goal-editor">
          <label><span>目标</span><TextArea aria-label="Goal 目标" rows={3} maxLength={4_000} value={objective} onChange={(event) => setObjective(event.target.value)} /></label>
          <div>
            <label><span>Token 预算</span><Input aria-label="Goal Token 预算" inputMode="numeric" placeholder="不限" value={tokenBudget} onChange={(event) => setTokenBudget(event.target.value.replace(/\D/g, ''))} /></label>
            <label><span>时间预算（分钟）</span><Input aria-label="Goal 时间预算" inputMode="numeric" placeholder="不限" value={timeMinutes} onChange={(event) => setTimeMinutes(event.target.value.replace(/\D/g, ''))} /></label>
          </div>
          <div className="agent-workflow-actions">
            <Button size="small" variant="quiet" onClick={() => setEditing(false)}>取消</Button>
            <Button size="small" variant="primary" leadingIcon={<Check size={15} />} loading={pending} disabled={!objective.trim()} onClick={saveGoal}>保存 Goal</Button>
          </div>
        </div>
      ) : null}

      {configured && !editing ? (
        <div className="agent-goal-summary" data-state={goal.status}>
          <p>{goal.objective}</p>
          {budgetRows.length ? <div className="agent-goal-budget">{budgetRows.map((row) => (
            <div key={row.label}>
              <span><small>{row.label}</small><strong>{row.value}</strong></span>
              <i><b style={{ width: `${row.percent}%` }} /></i>
            </div>
          ))}</div> : <small className="agent-goal-unbounded">未设置预算上限</small>}
          {goal.completionAudit ? (
            <div className="agent-goal-audit">
              <strong><ShieldCheck size={14} />完成审计</strong>
              <p>{goal.completionAudit.summary}</p>
              {goal.completionAudit.evidence.map((item) => <small key={`${item.kind}:${item.reference}`}>{item.summary} · {item.reference}</small>)}
            </div>
          ) : null}
          {!auditing ? <div className="agent-workflow-actions">
            {goal.status === 'active' ? <Button size="small" variant="quiet" leadingIcon={<CirclePause size={15} />} loading={pending} onClick={() => mutate({ action: 'pause', expectedRevision: goal.revision })}>暂停</Button> : null}
            {goal.status === 'paused' ? <Button size="small" leadingIcon={<CirclePlay size={15} />} loading={pending} onClick={() => mutate({ action: 'resume', expectedRevision: goal.revision })}>恢复</Button> : null}
            {['active', 'paused'].includes(goal.status) ? <Button size="small" variant="primary" leadingIcon={<ShieldCheck size={15} />} onClick={() => setAuditing(true)}>完成审计</Button> : null}
            <Button size="small" variant="quiet" loading={pending} onClick={() => mutate({ action: 'clear', expectedRevision: goal.revision })}>清除</Button>
          </div> : null}
        </div>
      ) : null}

      {auditing ? (
        <div className="agent-goal-audit-editor">
          <label><span>完成结论</span><TextArea aria-label="Goal 完成结论" rows={2} value={auditSummary} onChange={(event) => setAuditSummary(event.target.value)} /></label>
          <label><span>证据类型</span><select aria-label="Goal 证据类型" className="ui-input" value={evidenceKind} onChange={(event) => setEvidenceKind(event.target.value)}><option value="test">测试</option><option value="artifact">产物</option><option value="commit">提交</option><option value="receipt">回执</option><option value="note">说明</option></select></label>
          <label><span>证据摘要</span><Input aria-label="Goal 证据摘要" value={evidenceSummary} onChange={(event) => setEvidenceSummary(event.target.value)} /></label>
          <label><span>证据引用</span><Input aria-label="Goal 证据引用" placeholder="测试命令、commit 或 receipt ID" value={evidenceReference} onChange={(event) => setEvidenceReference(event.target.value)} /></label>
          <div className="agent-workflow-actions">
            <Button size="small" variant="quiet" onClick={() => setAuditing(false)}>取消</Button>
            <Button size="small" variant="primary" loading={pending} disabled={!auditSummary.trim() || !evidenceSummary.trim() || !evidenceReference.trim()} onClick={completeGoal}>提交审计</Button>
          </div>
        </div>
      ) : null}
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
  return {
    schemaVersion: 'rag-ime.agent-workflow-state.v1',
    ok: true,
    sessionId,
    plan: {
      schemaVersion: 'rag-ime.agent-plan.v2',
      ...resolvedPlan,
      id: resolvedPlan.id || `plan:${sessionId}`,
      sessionId: resolvedPlan.sessionId || sessionId,
    },
    goal: goal ?? emptyGoal(sessionId),
    actGate: actGate ?? closedActGate,
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
    status: 'cleared',
    budget: { tokenLimit: null, timeLimitMs: null },
    usage: { tokens: 0, elapsedMs: 0 },
    remaining: { tokens: null, timeMs: null },
    budgetExceeded: false,
    completionAudit: null,
    updatedAtMs: 0,
  };
}

const closedActGate: ActGate = {
  allowed: false,
  reason: 'plan_required',
  message: '先创建执行计划并提交审阅。',
};

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

function moveItem(items: PlanItem[], from: number, to: number): PlanItem[] {
  if (to < 0 || to >= items.length) return items;
  const next = [...items];
  const [item] = next.splice(from, 1);
  if (!item) return items;
  next.splice(to, 0, item);
  return next;
}

function planStatusLabel(status: Plan['status']): string {
  return {
    draft: '草案',
    review: '待审阅',
    approved: '已批准',
    executing: '执行中',
    completed: '已完成',
    cancelled: '已取消',
  }[status];
}

function goalStatusLabel(status: Goal['status']): string {
  return { active: '进行中', paused: '已暂停', completed: '已完成', cleared: '未设置' }[status];
}

function goalBudgetRows(goal: Goal): { label: string; value: string; percent: number }[] {
  const rows = [];
  if (goal.budget.tokenLimit) rows.push({
    label: 'Token',
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

function positiveNumberOrNull(value: string, multiplier = 1): number | null {
  const number = Number.parseInt(value, 10);
  return Number.isFinite(number) && number > 0 ? number * multiplier : null;
}

function formatCompact(value: number): string {
  return new Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 1 }).format(value);
}

function formatDuration(value: number): string {
  const minutes = Math.round(value / 60_000);
  return minutes >= 60 ? `${Math.floor(minutes / 60)}时${minutes % 60}分` : `${minutes}分钟`;
}

function publicError(error: unknown): string {
  return error instanceof Error ? error.message.slice(0, 240) : '操作失败，请刷新后重试。';
}
