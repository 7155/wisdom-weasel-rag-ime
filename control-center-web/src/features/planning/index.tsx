import { CalendarDays, CheckCircle2, ChevronLeft, ChevronRight, Flag, ListTodo, PanelsTopLeft, Plus, RefreshCw, Sparkles } from 'lucide-react';
import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  EmptyState,
  Field,
  IconButton,
  Input,
  Select,
  TextArea,
} from '@/components/primitives';
import type { JsonValue } from '@/platform/transport';
import {
  ManagementMutationWorkflow,
  parseManagementWorkPreview,
  parseManagementWorkReceipt,
} from '@/features/overview/management-mutation';
import { planningMutationPathIds, usePlanningDashboard, usePlanningMutationBoundary } from './api';
import {
  InlineNotice,
  ManagementPage,
  ManagementSection,
  OperationalList,
  QueryState,
  StatusBadge,
  arrayRecords,
  asRecord,
  formatTime,
  numberValue,
  stringValue,
} from '@/features/overview/management-ui';
import { AgentWakeSchedules } from './AgentWakeSchedules';
import { useProductIdentity } from '@/features/identity/product-identity';
import { usePawOsDesktop } from '@/features/paw-os/surface-context';
import './planning.css';

export function PlanningFeature() {
  const navigate = useNavigate();
  const pawOsDesktop = usePawOsDesktop();
  const identity = useProductIdentity();
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
  const selectedDayIsToday = date === today();
  const selectedDayLabel = selectedDayIsToday ? '今天' : planningDayLabel(date);
  const selectedDayNoun = selectedDayIsToday ? '今天' : '这一天';
  const [taskTitle, setTaskTitle] = useState('');
  const [taskTitleTouched, setTaskTitleTouched] = useState(false);
  const [taskDetail, setTaskDetail] = useState('');
  const [selectedTask, setSelectedTask] = useState('');
  const [taskDialogOpen, setTaskDialogOpen] = useState(false);
  const [planDialogOpen, setPlanDialogOpen] = useState(false);
  const planDialogTriggerRef = useRef<HTMLButtonElement | null>(null);
  const [goalTitle, setGoalTitle] = useState('');
  const [goalTitleTouched, setGoalTitleTouched] = useState(false);
  const [goalDetail, setGoalDetail] = useState('');
  const [goalHorizon, setGoalHorizon] = useState('long_term');
  const [goalStatus, setGoalStatus] = useState('active');
  const [goalPriority, setGoalPriority] = useState(1);
  const [goalTargetDate, setGoalTargetDate] = useState('');
  const [selectedGoal, setSelectedGoal] = useState('');
  const [goalDialogOpen, setGoalDialogOpen] = useState(false);
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
  const goalSaveDraft: Record<string, JsonValue> = {
    title: goalTitle.trim(),
    detail: goalDetail.trim(),
    horizon: goalHorizon,
    status: goalStatus,
    priority: goalPriority,
    targetDate: goalTargetDate,
    project,
    ...(selectedGoal ? { goalId: selectedGoal } : {}),
  };
  const revisionBlock = runtimeRevision === null ? '当前规划状态尚未同步，请刷新后重试。' : '';
  const taskEntryAvailability = mutationBoundary.availability([
    planningMutationPathIds.preview,
    planningMutationPathIds.taskSave,
    planningMutationPathIds.rollback,
  ]);
  const goalEntryAvailability = mutationBoundary.availability([
    planningMutationPathIds.preview,
    planningMutationPathIds.goalSave,
    planningMutationPathIds.rollback,
  ]);
  const openTasks = tasks.filter((task) => !['done', 'cancelled'].includes(stringValue(task.status)));
  const inProgressTasks = openTasks.filter((task) => stringValue(task.status) === 'in_progress');
  const overdueTasks = openTasks.filter((task) => {
    const dueAtMs = numberValue(task.dueAtMs);
    return dueAtMs > 0 && dueAtMs < now.getTime();
  });
  const focus = stringValue(plan.intention, stringValue(openTasks[0]?.title, '还没有设置今日重点'));
  const companionHints = planningHints({
    assistantName: identity.assistantName,
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
    setTaskTitleTouched(false);
    setTaskDialogOpen(true);
  };

  const selectGoal = (goal: Record<string, unknown>) => {
    setSelectedGoal(stringValue(goal.id));
    setGoalTitle(stringValue(goal.title));
    setGoalDetail(stringValue(goal.detail));
    setGoalHorizon(stringValue(goal.horizon, 'long_term'));
    setGoalStatus(stringValue(goal.status, 'active'));
    setGoalPriority(numberValue(goal.priority, 1));
    setGoalTargetDate(stringValue(goal.targetDate));
    setGoalTitleTouched(false);
    setGoalDialogOpen(true);
    requestAnimationFrame(() => document.getElementById('planning-goal-title')?.focus());
  };

  const moveDay = (offset: number) => {
    const next = new Date(`${date}T12:00:00`);
    next.setDate(next.getDate() + offset);
    setDate(localDate(next));
  };

  const beginNewTask = () => {
    setSelectedTask('');
    setTaskTitle('');
    setTaskDetail('');
    setTaskTitleTouched(false);
    setTaskDialogOpen(true);
    requestAnimationFrame(() => document.getElementById('planning-task-title')?.focus());
  };

  const beginNewGoal = () => {
    setSelectedGoal('');
    setGoalTitle('');
    setGoalDetail('');
    setGoalHorizon('long_term');
    setGoalStatus('active');
    setGoalPriority(1);
    setGoalTargetDate('');
    setGoalTitleTouched(false);
    setGoalDialogOpen(true);
    requestAnimationFrame(() => document.getElementById('planning-goal-title')?.focus());
  };

  const handoffToAgent = (intent: 'organize' | 'breakdown' | 'review') => {
    const task = selectedTaskRecord ?? openTasks[0];
    const taskTitle = stringValue(task?.title, focus);
    const taskDetail = stringValue(task?.detail);
    const prompts = {
      organize: `帮我整理 ${date} 的工作。今日重点是“${focus}”，还有 ${openTasks.length} 项待继续，已完成 ${numberValue(summary.completedTaskCount)} 项。请给我清晰的优先级和下一步。`,
      breakdown: `帮我把“${taskTitle}”拆成可以逐项完成的步骤${taskDetail ? `。补充说明：${taskDetail}` : ''}。`,
      review: `陪我复盘 ${date} 的工作：已完成 ${numberValue(summary.completedTaskCount)} 项，还有 ${openTasks.length} 项待继续。已有复盘记录：${stringValue(plan.reflection, '尚未填写')}。`,
    };
    navigate({ pathname: '/agent', search: `?${new URLSearchParams({ draft: prompts[intent] })}` });
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
      description="安排今天的任务，跟进目标，并在完成后留下清楚的结果。"
      eyebrow="工作计划"
      routeId="planning"
      title="任务"
    >
      <QueryState error={dashboard.error as Error | null} isPending={dashboard.isPending} onRetry={() => void dashboard.refetch()}>
        <ManagementSection
          title={selectedDayLabel}
          description={selectedDayIsToday
            ? openTasks.length
              ? `${timeGreeting(now)}。先完成最重要的一项，再安排其余工作。`
              : `${timeGreeting(now)}。今天还没有待办，从一项小而明确的任务开始。`
            : openTasks.length
              ? '先完成最重要的一项，再安排其余工作。'
              : '这一天还没有待办，可以添加一项清楚的任务。'}
          trailing={<StatusBadge label={date} tone="info" />}
        >
          <div className="planning-companion">
            <div className="planning-companion__focus">
              <span>{selectedDayIsToday ? '今日重点' : '当天重点'}</span>
              <strong>{focus}</strong>
            </div>
            <div className="planning-companion__actions">
              <Button leadingIcon={<Sparkles size={15} />} onClick={() => handoffToAgent('organize')} size="small" variant="primary">{selectedDayIsToday ? '安排今天' : '整理这一天'}</Button>
              <Button leadingIcon={<ListTodo size={15} />} onClick={() => handoffToAgent('breakdown')} size="small">拆解当前重点</Button>
              <Button leadingIcon={<CheckCircle2 size={15} />} onClick={() => handoffToAgent('review')} size="small" variant="quiet">一起复盘</Button>
            </div>
          </div>
          <div aria-label={selectedDayIsToday ? '今日进度' : '当天进度'} className="planning-summary-strip">
            <PlanningSummaryItem detail={`${inProgressTasks.length} 个进行中`} icon={ListTodo} label="待继续" value={openTasks.length} />
            <PlanningSummaryItem
              detail={overdueTasks.length ? stringValue(overdueTasks[0]?.title, '需要重新安排') : '节奏正常'}
              icon={CalendarDays}
              label="已逾期"
              tone={overdueTasks.length ? 'warning' : 'success'}
              value={overdueTasks.length}
            />
            <PlanningSummaryItem detail={`${Math.round(numberValue(summary.progress) * 100)}%`} icon={CheckCircle2} label="已完成" tone="success" value={numberValue(summary.completedTaskCount)} />
          </div>
          <div className="planning-secondary-actions">
            <Button onClick={(event) => { planDialogTriggerRef.current = event.currentTarget; setPlanDialogOpen(true); }} size="small" variant="quiet">{selectedDayIsToday ? '查看今日安排' : '查看当天安排'}</Button>
          </div>
        </ManagementSection>

        {Object.keys(completion).length ? (
          <ManagementSection title="需要核对的完成记录" trailing={<StatusBadge label="待核对" tone="info" />}>
            <InlineNotice title={stringValue(completion.message, '检测到任务完成')} tone="info">
              {stringValue(asRecord(completion.task).title, '未命名任务')} · {formatTime(completion.createdAtMs)}。核对后再更新任务状态。
            </InlineNotice>
            <InlineNotice title="请在原操作处处理" tone="info">
              这条记录不能在这里撤销；如需更改，请回到创建它的操作处处理。
            </InlineNotice>
          </ManagementSection>
        ) : null}

        <div className="planning-overview-grid">
          <ManagementSection title={`${selectedDayLabel}的安排`} description={`${selectedDayNoun}想做什么、过程备注和复盘都放在这里。`}>
            <div className="planning-plan-summary">
              <span>{selectedDayIsToday ? '今日意图' : '当天意图'}</span>
              <strong>{stringValue(plan.intention, '尚未设置')}</strong>
              <Button onClick={(event) => { planDialogTriggerRef.current = event.currentTarget; setPlanDialogOpen(true); }} size="small" variant="quiet">查看备注与复盘</Button>
            </div>
          </ManagementSection>
          <ManagementSection
            title="正在推进的目标"
            trailing={goalEntryAvailability.state !== 'unsupported' ? (
              <Button
                disabled={goalEntryAvailability.state !== 'available'}
                leadingIcon={<Plus size={14} />}
                onClick={beginNewGoal}
                size="small"
                variant="quiet"
              >
                {entryActionLabel(goalEntryAvailability.state, '添加目标')}
              </Button>
            ) : undefined}
          >
            {goals.length ? (
              <div className="planning-list planning-list--goals">
                <OperationalList items={goals.map((goal) => ({
                  id: stringValue(goal.id),
                  title: stringValue(goal.title, '未命名目标'),
                  detail: stringValue(goal.detail, '无说明'),
                  meta: stringValue(goal.targetDate, goalHorizonLabel(stringValue(goal.horizon))),
                  status: <StatusBadge label={goalStatusLabel(stringValue(goal.status))} tone={stringValue(goal.status) === 'active' ? 'info' : 'success'} />,
                  onClick: () => selectGoal(goal),
                  selected: selectedGoal === stringValue(goal.id),
                }))} />
              </div>
            ) : <EmptyState
              description={goalEntryAvailability.state === 'unsupported'
                ? `先和${identity.assistantName}聊聊长期想完成的事，她会帮你梳理方向。`
                : '现在还没有正在推进的目标。'}
              headingLevel={3}
              icon={Flag}
              title="暂无目标"
            />}
          </ManagementSection>
        </div>

        <ManagementSection
          title="任务"
          description="选择任务即可编辑内容或更新状态。"
          trailing={taskEntryAvailability.state !== 'unsupported' ? (
            <Button
              disabled={taskEntryAvailability.state !== 'available'}
              leadingIcon={<Plus size={14} />}
                onClick={beginNewTask}
                size="small"
                variant="primary"
            >
              {entryActionLabel(taskEntryAvailability.state, '添加任务')}
            </Button>
          ) : undefined}
        >
          {tasks.length ? (
            <div className="planning-list planning-list--tasks">
              <OperationalList items={tasks.map((task) => ({
                id: stringValue(task.id),
                title: stringValue(task.title, '未命名任务'),
                detail: stringValue(task.detail, '无说明'),
                meta: taskMeta(task, identity.assistantName),
                status: <StatusBadge label={taskStatusLabel(stringValue(task.status))} tone={stringValue(task.status) === 'done' ? 'success' : stringValue(task.status) === 'in_progress' ? 'info' : 'neutral'} />,
                onClick: () => selectTask(task),
                selected: selectedTask === stringValue(task.id),
              }))} />
            </div>
          ) : <EmptyState
            description={taskEntryAvailability.state === 'unsupported'
              ? `先把想做的事告诉${identity.assistantName}，她会帮你拆成可以执行和验收的下一步。`
              : '添加一个清楚、做完后能确认结果的下一步。'}
            headingLevel={3}
            icon={ListTodo}
            title="还没有任务"
          />}
        </ManagementSection>

        <AgentWakeSchedules tasks={tasks} />

        <Dialog onOpenChange={setPlanDialogOpen} open={planDialogOpen}>
          <DialogContent
            className="planning-dialog planning-detail-dialog"
            onCloseAutoFocus={(event) => {
              event.preventDefault();
              planDialogTriggerRef.current?.focus();
            }}
          >
            <DialogHeader>
              <DialogTitle>{selectedDayLabel}的安排</DialogTitle>
              <DialogDescription>{planningFullDateLabel(date)}想做的事、过程备注和复盘。</DialogDescription>
            </DialogHeader>
            <dl className="mgmt-kv planning-plan">
              <dt>{selectedDayIsToday ? '今日意图' : '当天意图'}</dt><dd>{stringValue(plan.intention, '尚未设置')}</dd>
              <dt>备注</dt><dd>{stringValue(plan.notes, '暂无')}</dd>
              <dt>复盘</dt><dd>{stringValue(plan.reflection, '暂无')}</dd>
            </dl>
            <section aria-label="下一步" className="planning-next-steps">
              <h3>下一步</h3>
              <OperationalList items={companionHints.map((hint, index) => ({
                id: `planning-hint-${index}`,
                title: hint.title,
                detail: hint.detail,
                meta: hint.meta,
                onClick: hint.task
                  ? () => {
                    setPlanDialogOpen(false);
                    selectTask(hint.task!);
                  }
                  : hint.action === 'new-task'
                    ? () => {
                      setPlanDialogOpen(false);
                      beginNewTask();
                    }
                    : () => handoffToAgent('organize'),
              }))} />
            </section>
            <DialogFooter>
              <Button onClick={() => setPlanDialogOpen(false)} size="small">返回</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <Dialog onOpenChange={setTaskDialogOpen} open={taskDialogOpen}>
          <DialogContent className="planning-dialog">
            <DialogHeader>
              <DialogTitle>{selectedTask ? '编辑任务' : '添加任务'}</DialogTitle>
              <DialogDescription>
                {selectedTask ? '修改内容后直接保存，也可以在右侧更新完成状态。' : '填写任务信息后直接保存。'}
              </DialogDescription>
            </DialogHeader>
            <div className="planning-dialog__context">
              <span><CalendarDays aria-hidden="true" size={15} />{date}</span>
              {selectedTaskRecord ? (
                <StatusBadge
                  label={taskStatusLabel(stringValue(selectedTaskRecord.status))}
                  tone={selectedStatus === 'done' ? 'success' : selectedStatus === 'in_progress' ? 'info' : 'neutral'}
                />
              ) : null}
              {selectedTaskRecord && pawOsDesktop ? (
                <Button
                  leadingIcon={<PanelsTopLeft aria-hidden="true" size={14} />}
                  onClick={() => pawOsDesktop.openWindow({
                    appId: 'project-workbench',
                    target: {
                      kind: 'task',
                      id: stringValue(selectedTaskRecord.id),
                      title: stringValue(selectedTaskRecord.title, '未命名任务'),
                      subtitle: `${date} · ${project}`,
                      date,
                      project,
                    },
                  })}
                  size="small"
                  variant="quiet"
                >
                  独立窗口
                </Button>
              ) : null}
            </div>
            <div className={selectedTask ? 'planning-dialog__grid' : 'planning-dialog__grid planning-dialog__grid--single'}>
              <div className="mgmt-stack">
                <Field
                  error={taskTitleTouched && !taskTitle.trim() ? '请输入任务标题。' : undefined}
                  htmlFor="planning-task-title"
                  label="任务标题"
                  required
                >
                  <Input
                    aria-describedby={taskTitleTouched && !taskTitle.trim() ? 'planning-task-title-error' : undefined}
                    aria-invalid={taskTitleTouched && !taskTitle.trim() ? true : undefined}
                    id="planning-task-title"
                    onBlur={() => setTaskTitleTouched(true)}
                    onChange={(event) => setTaskTitle(event.target.value)}
                    placeholder="例如：整理今天的工作清单"
                    value={taskTitle}
                  />
                </Field>
                <Field htmlFor="planning-task-detail" label="说明">
                  <TextArea id="planning-task-detail" onChange={(event) => setTaskDetail(event.target.value)} rows={4} value={taskDetail} />
                </Field>
                <ManagementMutationWorkflow
                  availability={mutationBoundary.availability(
                    [planningMutationPathIds.preview, planningMutationPathIds.taskSave, planningMutationPathIds.rollback],
                    revisionBlock || (!taskTitle.trim() ? '请输入任务标题。' : ''),
                  )}
                  description={selectedTask ? '保存标题、说明和日期。' : '添加到当天的任务清单。'}
                  disabled={!taskTitle.trim()}
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
              {selectedTask ? (
                <div className="mgmt-stack">
                  <ManagementMutationWorkflow
                    availability={mutationBoundary.availability(
                      [planningMutationPathIds.preview, planningMutationPathIds.taskAction, planningMutationPathIds.taskEventUndo],
                      revisionBlock || (!selectedTask ? '先从任务列表选择一项任务。' : ''),
                    )}
                    explicitConfirmation={false}
                    description={taskAction === 'reopen' ? '重新打开所选任务；完成后仍可撤销。' : '将所选任务标记完成；完成后仍可撤销。'}
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
                      if (!eventId) throw new Error('无法验证这次任务变更，不能安全撤销。');
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
                </div>
              ) : null}
            </div>
          </DialogContent>
        </Dialog>

        <Dialog onOpenChange={setGoalDialogOpen} open={goalDialogOpen}>
          <DialogContent className="planning-dialog planning-dialog--goal">
            <DialogHeader>
              <DialogTitle>{selectedGoal ? '编辑目标' : '添加目标'}</DialogTitle>
              <DialogDescription>填写目标信息后直接保存，完成后仍可撤销。</DialogDescription>
            </DialogHeader>
            <div className="planning-dialog__context">
              <span><Flag aria-hidden="true" size={15} />{goalHorizonLabel(goalHorizon)}</span>
              {selectedGoal ? <StatusBadge label={goalStatusLabel(goalStatus)} tone={goalStatus === 'active' ? 'info' : 'success'} /> : null}
              {selectedGoal ? <Button onClick={beginNewGoal} size="small" variant="quiet">另建一个目标</Button> : null}
            </div>
            <div className="planning-dialog__grid">
              <div className="mgmt-stack">
                <Field
                  error={goalTitleTouched && !goalTitle.trim() ? '请输入目标标题。' : undefined}
                  htmlFor="planning-goal-title"
                  label="目标标题"
                  required
                >
                  <Input
                    aria-describedby={goalTitleTouched && !goalTitle.trim() ? 'planning-goal-title-error' : undefined}
                    aria-invalid={goalTitleTouched && !goalTitle.trim() ? true : undefined}
                    id="planning-goal-title"
                    onBlur={() => setGoalTitleTouched(true)}
                    onChange={(event) => setGoalTitle(event.target.value)}
                    placeholder="例如：完成控制中心迁移"
                    value={goalTitle}
                  />
                </Field>
                <Field htmlFor="planning-goal-detail" label="说明">
                  <TextArea id="planning-goal-detail" onChange={(event) => setGoalDetail(event.target.value)} rows={4} value={goalDetail} />
                </Field>
                <Field htmlFor="planning-goal-target-date" label="目标日期">
                  <Input id="planning-goal-target-date" onChange={(event) => setGoalTargetDate(event.target.value)} type="date" value={goalTargetDate} />
                </Field>
              </div>
              <div className="mgmt-stack">
                <div className="planning-dialog__selects">
                  <Field htmlFor="planning-goal-horizon" label="时间范围">
                    <Select id="planning-goal-horizon" onValueChange={setGoalHorizon} options={[
                      { value: 'today', label: '今天' },
                      { value: 'short_term', label: '近期' },
                      { value: 'medium_term', label: '阶段目标' },
                      { value: 'long_term', label: '长期目标' },
                    ]} value={goalHorizon} />
                  </Field>
                  <Field htmlFor="planning-goal-status" label="状态">
                    <Select id="planning-goal-status" onValueChange={setGoalStatus} options={[
                      { value: 'active', label: '进行中' },
                      { value: 'completed', label: '已完成' },
                      { value: 'archived', label: '已归档' },
                    ]} value={goalStatus} />
                  </Field>
                </div>
                <Field htmlFor="planning-goal-priority" label="优先级">
                  <Select id="planning-goal-priority" onValueChange={(value) => setGoalPriority(Number(value))} options={[
                    { value: '0', label: '低' },
                    { value: '1', label: '普通' },
                    { value: '2', label: '高' },
                    { value: '3', label: '最高' },
                  ]} value={String(goalPriority)} />
                </Field>
                <ManagementMutationWorkflow
                  availability={mutationBoundary.availability(
                    [planningMutationPathIds.preview, planningMutationPathIds.goalSave, planningMutationPathIds.rollback],
                    revisionBlock || (!goalTitle.trim() ? '请输入目标标题。' : ''),
                  )}
                  description={selectedGoal ? '保存周期、状态和优先级。' : '添加到正在推进的目标。'}
                  disabled={!goalTitle.trim()}
                  draftKey={JSON.stringify(goalSaveDraft)}
                  mutationKey={['planning', 'mutation', 'goal-save']}
                  onApply={async (preview) => parseManagementWorkReceipt(
                    await mutationBoundary.request({
                      pathId: planningMutationPathIds.goalSave,
                      body: {
                        ...preview.context,
                        expectedRuntimeRevision: preview.expectedRuntimeRevision,
                        previewToken: preview.previewToken,
                        payloadSha256: preview.payloadSha256,
                        confirmText: preview.requiredConfirm,
                      },
                    }),
                    planningMutationPathIds.goalSave,
                    preview.payloadSha256,
                  )}
                  onApplied={() => void dashboard.refetch()}
                  onPreview={async () => parseManagementWorkPreview(
                    await mutationBoundary.request({
                      pathId: planningMutationPathIds.preview,
                      body: {
                        kind: 'goal.save',
                        payload: goalSaveDraft,
                        expectedRuntimeRevision: runtimeRevision ?? 0,
                      },
                    }),
                    planningMutationPathIds.goalSave,
                    goalSaveDraft,
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
                  title={selectedGoal ? '保存目标修改' : '创建目标'}
                />
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </QueryState>
    </ManagementPage>
  );
}

function PlanningSummaryItem({
  detail,
  icon: Icon,
  label,
  tone = 'neutral',
  value,
}: {
  detail: string;
  icon: typeof ListTodo;
  label: string;
  tone?: 'neutral' | 'success' | 'warning';
  value: number;
}) {
  return (
    <div className="planning-summary-item" data-tone={tone}>
      <Icon aria-hidden="true" size={16} />
      <span>{label}</span>
      <strong>{value}</strong>
      <small title={detail}>{detail}</small>
    </div>
  );
}

function today(): string {
  return localDate(new Date());
}

function entryActionLabel(state: 'checking' | 'available' | 'blocked' | 'unsupported', label: string): string {
  if (state === 'available') return label;
  if (state === 'checking') return `${label}（正在确认）`;
  return `${label}（暂不可用）`;
}

function localDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function planningDayLabel(value: string): string {
  const [, month, day] = value.match(/^\d{4}-(\d{2})-(\d{2})$/u) ?? [];
  if (!month || !day) return value;
  return `${Number(month)}月${Number(day)}日`;
}

function planningFullDateLabel(value: string): string {
  const [year, month, day] = value.match(/^(\d{4})-(\d{2})-(\d{2})$/u)?.slice(1) ?? [];
  if (!year || !month || !day) return value;
  return `${year}年${Number(month)}月${Number(day)}日`;
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
  assistantName,
  assistantMessage,
  completedCount,
  focus,
  inProgressTasks,
  openTasks,
  overdueTasks,
  reflection,
  suggestions,
}: {
  assistantName: string;
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
    const candidate = arrayRecords(suggestions[0]?.candidateTasks)[0];
    hints.push({
      title: `核对 ${suggestions.length} 条完成建议`,
      detail: candidate
        ? `先核对“${stringValue(candidate.title, '候选任务')}”的真实完成情况。`
        : '先确认真实完成情况，再更新任务状态。',
      meta: '待确认',
      ...(candidate ? { task: candidate } : {}),
    });
  }
  if (hints.length < 3 && completedCount > 0 && !reflection) {
    hints.push({
      title: `复盘今天完成的 ${completedCount} 项`,
      detail: `把有效做法和下一步交给${assistantName}收束。`,
      meta: '复盘',
    });
  }
  if (hints.length < 3 && openTasks.length) {
    const next = openTasks.find((task) => task !== overdue && task !== inProgress);
    if (next) {
      hints.push({
        title: `下一步：${stringValue(next.title, focus)}`,
        detail: stringValue(next.detail, assistantMessage || '选中任务后继续细化。'),
        meta: taskStatusLabel(stringValue(next.status)),
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
      title: openTasks.length ? `让${assistantName}重新整理今天的顺序` : `让${assistantName}把今日意图拆成第一步`,
      detail: assistantMessage || focus,
      meta: assistantName,
    });
  }
  return hints.slice(0, 3);
}

function taskStatusLabel(value: string): string {
  return ({
    todo: '待开始',
    in_progress: '进行中',
    done: '已完成',
    cancelled: '已取消',
  } as Record<string, string>)[value] ?? '待处理';
}

function goalStatusLabel(value: string): string {
  return ({
    active: '进行中',
    completed: '已完成',
    archived: '已归档',
  } as Record<string, string>)[value] ?? '待处理';
}

function goalHorizonLabel(value: string): string {
  return ({
    today: '今天',
    short_term: '近期',
    medium_term: '阶段目标',
    long_term: '长期目标',
  } as Record<string, string>)[value] ?? '长期目标';
}

function taskMeta(task: Record<string, unknown>, assistantName: string): string {
  const dueAtMs = numberValue(task.dueAtMs);
  if (dueAtMs > 0) return `截止 ${formatTime(dueAtMs)}`;
  return ({
    manual: '手动添加',
    assistant: `${assistantName}建议`,
    completion_suggestion: '完成建议',
    imported: '导入任务',
  } as Record<string, string>)[stringValue(task.source)] ?? '计划任务';
}
