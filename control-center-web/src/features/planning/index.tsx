import { CalendarDays, CheckCircle2, ChevronLeft, ChevronRight, Flag, ListTodo, RefreshCw, Sparkles } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, EmptyState, Field, IconButton, Input, TextArea } from '@/components/primitives';
import type { JsonValue } from '@/platform/transport';
import {
  ManagementMutationWorkflow,
  UnsupportedWorkflow,
  parseManagementWorkPreview,
  parseManagementWorkReceipt,
} from '@/features/overview/management-mutation';
import { planningMutationPathIds, usePlanningDashboard, usePlanningMutationBoundary } from './api';
import {
  InlineNotice,
  ManagementPage,
  ManagementSection,
  MetricStrip,
  OperationalList,
  QueryState,
  StatusBadge,
  arrayRecords,
  asRecord,
  formatTime,
  numberValue,
  stringValue,
} from '@/features/overview/management-ui';
import './planning.css';

export function PlanningFeature() {
  const navigate = useNavigate();
  const now = new Date();
  const [date, setDate] = useState(today());
  const { dashboard } = usePlanningDashboard(date);
  const payload = asRecord(dashboard.data);
  const plan = asRecord(payload.plan);
  const summary = asRecord(payload.summary);
  const tasks = arrayRecords(payload.tasks);
  const goals = arrayRecords(payload.goals);
  const suggestions = arrayRecords(payload.pendingCompletionSuggestions);
  const completion = asRecord(payload.recentDetectedCompletion);
  const [taskTitle, setTaskTitle] = useState('');
  const [taskDetail, setTaskDetail] = useState('');
  const [selectedTask, setSelectedTask] = useState('');
  const selectedTaskRecord = tasks.find((task) => stringValue(task.id) === selectedTask);
  const runtimeRevision = typeof payload.runtimeRevision === 'number' ? payload.runtimeRevision : null;
  const mutationBoundary = usePlanningMutationBoundary();
  const project = stringValue(plan.project, 'wisdom-weasel-rag-ime');
  const taskSaveDraft: Record<string, JsonValue> = {
    date,
    title: taskTitle.trim(),
    detail: taskDetail.trim(),
    project,
    ...(selectedTask ? { taskId: selectedTask } : {}),
  };
  const selectedStatus = stringValue(selectedTaskRecord?.status, 'todo');
  const taskAction = selectedStatus === 'done' ? 'reopen' : 'complete';
  const taskActionDraft: Record<string, JsonValue> = {
    taskId: selectedTask,
    action: taskAction,
  };
  const revisionBlock = runtimeRevision === null ? '规划快照缺少 runtimeRevision，请刷新后重试。' : '';
  const openTasks = tasks.filter((task) => !['done', 'cancelled'].includes(stringValue(task.status)));
  const inProgressTasks = openTasks.filter((task) => stringValue(task.status) === 'in_progress');
  const overdueTasks = openTasks.filter((task) => {
    const dueAtMs = numberValue(task.dueAtMs);
    return dueAtMs > 0 && dueAtMs < now.getTime();
  });
  const focus = stringValue(plan.intention, stringValue(openTasks[0]?.title, '今天没有未完成任务'));
  const companionHints = planningHints({
    assistantMessage: stringValue(asRecord(payload.assistant).message),
    completedCount: numberValue(summary.completedTaskCount),
    focus,
    inProgressTasks,
    openTasks,
    overdueTasks,
    reflection: stringValue(plan.reflection),
    suggestions,
  });

  const selectTask = (task: Record<string, unknown>) => {
    setSelectedTask(stringValue(task.id));
    setTaskTitle(stringValue(task.title));
    setTaskDetail(stringValue(task.detail));
  };

  const moveDay = (offset: number) => {
    const next = new Date(`${date}T12:00:00`);
    next.setDate(next.getDate() + offset);
    setDate(localDate(next));
  };

  return (
    <ManagementPage
      actions={
        <>
          <IconButton icon={<ChevronLeft size={16} />} label="前一天" onClick={() => moveDay(-1)} tooltip />
          <Input aria-label="规划日期" onChange={(event) => setDate(event.target.value)} type="date" value={date} />
          <IconButton icon={<ChevronRight size={16} />} label="后一天" onClick={() => moveDay(1)} tooltip />
          <Button onClick={() => setDate(today())} size="small" variant="quiet">今天</Button>
          <IconButton icon={<RefreshCw size={16} />} label="刷新" onClick={() => void dashboard.refetch()} tooltip />
        </>
      }
      description="按日期查看日计划、任务、目标与完成建议。"
      eyebrow="TODAY"
      routeId="planning"
      title="规划"
    >
      <QueryState error={dashboard.error as Error | null} isPending={dashboard.isPending} onRetry={() => void dashboard.refetch()}>
        <ManagementSection
          title={`${timeGreeting(now)}，今天先照顾这一件事`}
          description={stringValue(asRecord(payload.assistant).message, focus)}
          trailing={<StatusBadge label={stringValue(payload.date, date)} tone="info" />}
        >
          <div className="planning-companion">
            <div className="planning-companion__focus">
              <span>今日重点</span>
              <strong>{focus}</strong>
            </div>
            <div className="planning-companion__actions">
              <Button leadingIcon={<Sparkles size={15} />} onClick={() => navigate('/agent')} size="small" variant="primary">交给智鼬整理</Button>
              <Button leadingIcon={<ListTodo size={15} />} onClick={() => navigate('/agent')} size="small">请智鼬拆解</Button>
              <Button leadingIcon={<CheckCircle2 size={15} />} onClick={() => navigate('/agent')} size="small" variant="quiet">一起复盘</Button>
            </div>
          </div>
          <MetricStrip items={[
            { label: '待继续', value: openTasks.length, detail: `${inProgressTasks.length} 个进行中`, icon: ListTodo },
            { label: '已逾期', value: overdueTasks.length, detail: overdueTasks.length ? stringValue(overdueTasks[0]?.title, '需要重新安排') : '节奏正常', icon: CalendarDays, tone: overdueTasks.length ? 'warning' : 'success' },
            { label: '已完成', value: numberValue(summary.completedTaskCount), detail: `${Math.round(numberValue(summary.progress) * 100)}%`, icon: CheckCircle2, tone: 'success' },
            { label: '陪伴提示', value: companionHints.length, detail: suggestions.length ? `${suggestions.length} 条待确认完成` : '来自今日真实计划', icon: Sparkles, tone: suggestions.length ? 'warning' : 'neutral' },
          ]} />
          <OperationalList items={companionHints.map((hint, index) => ({
            id: `planning-hint-${index}`,
            title: hint.title,
            detail: hint.detail,
            meta: hint.meta,
            onClick: hint.task
              ? () => selectTask(hint.task!)
              : hint.action === 'new-task'
                ? () => document.getElementById('planning-task-title')?.focus()
                : () => navigate('/agent'),
          }))} />
        </ManagementSection>

        {Object.keys(completion).length ? (
          <ManagementSection title="最近检测到完成" trailing={<StatusBadge label={stringValue(completion.eventId, 'event')} tone="success" />}>
            <InlineNotice title={stringValue(completion.message, '检测到任务完成')} tone="success">
              任务：{stringValue(asRecord(completion.task).title, '未命名')} · {formatTime(completion.createdAtMs)}。确认前不会静默改写计划。
            </InlineNotice>
            <UnsupportedWorkflow
              description="只允许持有原应用收据和 rollbackToken 的调用方撤销任务事件。"
              reason="这条旧完成记录没有绑定的 Web WorkContract 收据，已按失败关闭处理。"
              risk="R1"
              title="撤销完成事件"
            />
          </ManagementSection>
        ) : null}

        <div className="mgmt-grid-2">
          <ManagementSection title="日计划" description="意图、备注和复盘保持同一快照。">
            <dl className="mgmt-kv">
              <dt>今日意图</dt><dd>{stringValue(plan.intention, '尚未设置')}</dd>
              <dt>备注</dt><dd>{stringValue(plan.notes, '暂无')}</dd>
              <dt>复盘</dt><dd>{stringValue(plan.reflection, '暂无')}</dd>
              <dt>项目</dt><dd>{stringValue(plan.project, 'wisdom-weasel-rag-ime')}</dd>
            </dl>
          </ManagementSection>
          <ManagementSection title="活动目标">
            {goals.length ? <OperationalList items={goals.map((goal) => ({
              id: stringValue(goal.id),
              title: stringValue(goal.title, '未命名目标'),
              detail: stringValue(goal.detail, '无说明'),
              meta: stringValue(goal.targetDate, stringValue(goal.horizon, 'long_term')),
              status: <StatusBadge label={stringValue(goal.status, 'active')} tone={stringValue(goal.status) === 'active' ? 'info' : 'success'} />,
            }))} /> : <EmptyState description="当前没有活动目标。" icon={Flag} title="暂无目标" />}
          </ManagementSection>
        </div>

        <ManagementSection title="任务" description="选择一项任务以查看、完成或继续编辑。">
          {tasks.length ? <OperationalList items={tasks.map((task) => ({
            id: stringValue(task.id),
            title: stringValue(task.title, '未命名任务'),
            detail: stringValue(task.detail, '无说明'),
            meta: stringValue(task.source, 'manual'),
            status: <StatusBadge label={stringValue(task.status, 'todo')} tone={stringValue(task.status) === 'done' ? 'success' : stringValue(task.status) === 'in_progress' ? 'info' : 'neutral'} />,
            onClick: () => selectTask(task),
            selected: selectedTask === stringValue(task.id),
          }))} /> : <EmptyState description="这一天还没有任务。" icon={CalendarDays} title="任务列表为空" />}
        </ManagementSection>

        <ManagementSection title="任务编辑" description="服务端预览会绑定运行版本、请求摘要与最终收据。">
          <div className="mgmt-grid-2">
            <div className="mgmt-stack">
              <Field htmlFor="planning-task-title" label="任务标题" required>
                <Input id="planning-task-title" onChange={(event) => setTaskTitle(event.target.value)} placeholder="例如：完成前台输入 smoke" value={taskTitle} />
              </Field>
              <Field htmlFor="planning-task-detail" label="说明">
                <TextArea id="planning-task-detail" onChange={(event) => setTaskDetail(event.target.value)} rows={4} value={taskDetail} />
              </Field>
              <ManagementMutationWorkflow
                availability={mutationBoundary.availability(
                  [planningMutationPathIds.preview, planningMutationPathIds.taskSave, planningMutationPathIds.rollback],
                  revisionBlock || (!taskTitle.trim() ? '填写任务标题后才能生成服务端预览。' : ''),
                )}
                description="创建任务或更新标题、说明与日期。"
                draftKey={JSON.stringify(taskSaveDraft)}
                mutationKey={['planning', 'mutation', 'task-save']}
                onApply={async (preview) => parseManagementWorkReceipt(
                  await mutationBoundary.request({
                    pathId: planningMutationPathIds.taskSave,
                    body: {
                      ...preview.context,
                      expectedRuntimeRevision: preview.expectedRuntimeRevision,
                      previewToken: preview.previewToken,
                      payloadSha256: preview.payloadSha256,
                      confirmText: preview.requiredConfirm,
                    },
                  }),
                  planningMutationPathIds.taskSave,
                  preview.payloadSha256,
                )}
                onApplied={() => void dashboard.refetch()}
                onPreview={async () => parseManagementWorkPreview(
                  await mutationBoundary.request({
                    pathId: planningMutationPathIds.preview,
                    body: {
                      kind: 'task.save',
                      payload: taskSaveDraft,
                      expectedRuntimeRevision: runtimeRevision ?? 0,
                    },
                  }),
                  planningMutationPathIds.taskSave,
                  taskSaveDraft,
                )}
                onRollback={async (receipt, preview) => parseManagementWorkReceipt(
                  await mutationBoundary.request({
                    pathId: planningMutationPathIds.rollback,
                    body: {
                      receiptId: receipt.receiptId,
                      rollbackToken: receipt.rollbackToken,
                      payloadSha256: receipt.payloadSha256,
                      confirmText: 'rollback',
                    },
                  }),
                  planningMutationPathIds.rollback,
                  preview.payloadSha256,
                )}
                onRolledBack={() => void dashboard.refetch()}
                risk="R1"
                title={selectedTask ? '保存任务修改' : '创建任务'}
              />
            </div>
            <div className="mgmt-stack">
              <ManagementMutationWorkflow
                availability={mutationBoundary.availability(
                  [planningMutationPathIds.preview, planningMutationPathIds.taskAction, planningMutationPathIds.taskEventUndo],
                  revisionBlock || (!selectedTask ? '先从任务列表选择一项任务。' : ''),
                )}
                description={taskAction === 'reopen' ? '重新打开所选任务，并保留本次动作的撤销收据。' : '将所选任务标记完成，并保留本次动作的撤销收据。'}
                draftKey={JSON.stringify(taskActionDraft)}
                mutationKey={['planning', 'mutation', 'task-complete']}
                onApply={async (preview) => parseManagementWorkReceipt(
                  await mutationBoundary.request({
                    pathId: planningMutationPathIds.taskAction,
                    body: {
                      ...preview.context,
                      expectedRuntimeRevision: preview.expectedRuntimeRevision,
                      previewToken: preview.previewToken,
                      payloadSha256: preview.payloadSha256,
                      confirmText: preview.requiredConfirm,
                    },
                  }),
                  planningMutationPathIds.taskAction,
                  preview.payloadSha256,
                )}
                onApplied={() => void dashboard.refetch()}
                onPreview={async () => parseManagementWorkPreview(
                  await mutationBoundary.request({
                    pathId: planningMutationPathIds.preview,
                    body: {
                      kind: 'task.action',
                      payload: taskActionDraft,
                      expectedRuntimeRevision: runtimeRevision ?? 0,
                    },
                  }),
                  planningMutationPathIds.taskAction,
                  taskActionDraft,
                )}
                onRollback={async (receipt, preview) => {
                  const eventId = stringValue(receipt.raw.eventId);
                  if (!eventId) throw new Error('任务动作收据缺少 eventId，无法安全撤销。');
                  return parseManagementWorkReceipt(
                    await mutationBoundary.request({
                      pathId: planningMutationPathIds.taskEventUndo,
                      body: {
                        eventId,
                        receiptId: receipt.receiptId,
                        rollbackToken: receipt.rollbackToken,
                        payloadSha256: receipt.payloadSha256,
                        confirmText: 'undo',
                      },
                    }),
                    planningMutationPathIds.taskEventUndo,
                    preview.payloadSha256,
                  );
                }}
                onRolledBack={() => void dashboard.refetch()}
                risk="R1"
                title={taskAction === 'reopen' ? '重新打开所选任务' : '完成所选任务'}
              />
              <UnsupportedWorkflow
                description="新建长期目标，之后可关联到具体任务。"
                reason="本批 WorkContract 仅开放 task.save 与 task.action；目标写入保持禁用。"
                risk="R1"
                title="创建目标草案"
              />
            </div>
          </div>
        </ManagementSection>
      </QueryState>
    </ManagementPage>
  );
}

function today(): string {
  return localDate(new Date());
}

function localDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function timeGreeting(date: Date): string {
  const hour = date.getHours();
  if (hour < 6) return '夜深了';
  if (hour < 11) return '早上好';
  if (hour < 14) return '中午好';
  if (hour < 18) return '下午好';
  return '晚上好';
}

type PlanningHint = {
  action?: 'agent' | 'new-task';
  detail: string;
  meta: string;
  task?: Record<string, unknown>;
  title: string;
};

function planningHints({
  assistantMessage,
  completedCount,
  focus,
  inProgressTasks,
  openTasks,
  overdueTasks,
  reflection,
  suggestions,
}: {
  assistantMessage: string;
  completedCount: number;
  focus: string;
  inProgressTasks: Record<string, unknown>[];
  openTasks: Record<string, unknown>[];
  overdueTasks: Record<string, unknown>[];
  reflection: string;
  suggestions: Record<string, unknown>[];
}): PlanningHint[] {
  const hints: PlanningHint[] = [];
  const overdue = overdueTasks[0];
  const inProgress = inProgressTasks[0];
  if (overdue) {
    hints.push({
      title: `先重新安排：${stringValue(overdue.title, '逾期任务')}`,
      detail: `已超过 ${formatTime(overdue.dueAtMs)}，点开后可调整或完成。`,
      meta: '逾期',
      task: overdue,
    });
  }
  if (inProgress && inProgress !== overdue) {
    hints.push({
      title: `继续：${stringValue(inProgress.title, '进行中任务')}`,
      detail: stringValue(inProgress.detail, '沿着上次停下的位置继续。'),
      meta: '进行中',
      task: inProgress,
    });
  }
  if (suggestions.length) {
    hints.push({
      title: `核对 ${suggestions.length} 条完成建议`,
      detail: '先确认真实完成情况，再更新任务状态。',
      meta: '待确认',
    });
  }
  if (hints.length < 3 && completedCount > 0 && !reflection) {
    hints.push({
      title: `复盘今天完成的 ${completedCount} 项`,
      detail: '把有效做法和下一步交给智鼬收束。',
      meta: '复盘',
    });
  }
  if (hints.length < 3 && openTasks.length) {
    const next = openTasks.find((task) => task !== overdue && task !== inProgress);
    if (next) {
      hints.push({
        title: `下一步：${stringValue(next.title, focus)}`,
        detail: stringValue(next.detail, assistantMessage || '选中任务后继续细化。'),
        meta: stringValue(next.status, '待继续'),
        task: next,
      });
    }
  }
  if (hints.length < 2 && !openTasks.length) {
    hints.push({
      action: 'new-task',
      title: '创建今天的第一项任务',
      detail: '当前计划没有待继续任务，从一个可完成的小动作开始。',
      meta: '新任务',
    });
  }
  if (hints.length < 2) {
    hints.push({
      action: 'agent',
      title: openTasks.length ? '让智鼬重新整理今天的顺序' : '让智鼬把今日意图拆成第一步',
      detail: assistantMessage || focus,
      meta: '智鼬',
    });
  }
  return hints.slice(0, 3);
}
