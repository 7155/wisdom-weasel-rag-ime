import { CalendarDays, CheckCircle2, ChevronLeft, ChevronRight, Flag, ListTodo, RefreshCw, Sparkles } from 'lucide-react';
import { useState } from 'react';
import { Button, EmptyState, Field, IconButton, Input, TextArea } from '@/components/primitives';
import { usePlanningDashboard } from './api';
import {
  InlineNotice,
  ManagementPage,
  ManagementSection,
  MetricStrip,
  OperationalList,
  QueryState,
  StatusBadge,
  WorkflowAction,
  arrayRecords,
  asRecord,
  formatTime,
  numberValue,
  stringValue,
} from '@/features/overview/management-ui';

export function PlanningFeature() {
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
        <ManagementSection title={stringValue(payload.date, date)} description={stringValue(asRecord(payload.assistant).message, '把计划压缩为今天真正会推进的动作。')}>
          <MetricStrip items={[
            { label: '任务', value: numberValue(summary.taskCount, tasks.length), detail: `${numberValue(summary.openTaskCount)} 个待推进`, icon: ListTodo },
            { label: '已完成', value: numberValue(summary.completedTaskCount), detail: `${Math.round(numberValue(summary.progress) * 100)}%`, icon: CheckCircle2, tone: 'success' },
            { label: '目标', value: numberValue(summary.goalCount, goals.length), detail: 'active horizons', icon: Flag },
            { label: '建议', value: suggestions.length, detail: '待确认完成', icon: Sparkles, tone: suggestions.length ? 'warning' : 'neutral' },
          ]} />
        </ManagementSection>

        {Object.keys(completion).length ? (
          <ManagementSection title="最近检测到完成" trailing={<StatusBadge label={stringValue(completion.eventId, 'event')} tone="success" />}>
            <InlineNotice title={stringValue(completion.message, '检测到任务完成')} tone="success">
              任务：{stringValue(asRecord(completion.task).title, '未命名')} · {formatTime(completion.createdAtMs)}。确认前不会静默改写计划。
            </InlineNotice>
            <WorkflowAction
              actionId="planning.completion.undo"
              applyLabel="批准撤销"
              description="撤销最近一次自动完成事件并恢复任务状态。"
              mutationKey={['planning', 'mutation', 'undo-completion']}
              preview={[`eventId：${stringValue(completion.eventId)}`, '只撤销关联任务事件。', '收据保留恢复前后状态。']}
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
            onClick: () => setSelectedTask(stringValue(task.id)),
            selected: selectedTask === stringValue(task.id),
          }))} /> : <EmptyState description="这一天还没有任务。" icon={CalendarDays} title="任务列表为空" />}
        </ManagementSection>

        <ManagementSection title="任务编辑" description="编辑任务内容并预览状态变化；当前操作为演练。">
          <div className="mgmt-grid-2">
            <div className="mgmt-stack">
              <Field htmlFor="planning-task-title" label="任务标题" required>
                <Input id="planning-task-title" onChange={(event) => setTaskTitle(event.target.value)} placeholder="例如：完成前台输入 smoke" value={taskTitle} />
              </Field>
              <Field htmlFor="planning-task-detail" label="说明">
                <TextArea id="planning-task-detail" onChange={(event) => setTaskDetail(event.target.value)} rows={4} value={taskDetail} />
              </Field>
              <WorkflowAction
                actionId="planning.task.save"
                description="创建任务或更新标题、说明与日期。"
                mutationKey={['planning', 'mutation', 'task-save']}
                preview={[`日期：${date}`, `标题：${taskTitle.trim() || '未填写'}`, `说明：${taskDetail.trim() || '无'}`]}
                risk="R1"
                title="保存任务草案"
              />
            </div>
            <div className="mgmt-stack">
              <WorkflowAction
                actionId="planning.task.complete"
                applyLabel="批准完成"
                description="将所选任务标记完成，并保留撤销入口。"
                mutationKey={['planning', 'mutation', 'task-complete']}
                preview={[
                  `taskId：${selectedTask || '尚未选择'}`,
                  `任务：${stringValue(selectedTaskRecord?.title, '尚未选择')}`,
                  '服务端必须返回 eventId 与 undoAvailable。',
                ]}
                risk="R1"
                title="完成所选任务"
              />
              <WorkflowAction
                actionId="planning.goal.save"
                description="新建长期目标，之后可关联到具体任务。"
                mutationKey={['planning', 'mutation', 'goal-save']}
                preview={['目标标题与周期必填。', '优先级范围为 0-3。', '归档或完成仍保留历史记录。']}
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
