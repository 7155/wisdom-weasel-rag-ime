import {
  BookOpenText,
  CalendarClock,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Database,
  ExternalLink,
  Fingerprint,
  ListTree,
  LockKeyhole,
  Monitor,
  RefreshCw,
  Sparkles,
  X,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Disclosure,
  Field,
  IconButton,
  Input,
} from '@/components/primitives';
import {
  InlineNotice,
  StatusBadge,
  arrayRecords,
  asRecord,
  numberValue,
  stringValue,
} from '@/features/overview/management-ui';
import { useActivityTimeline } from './api';
import {
  MemoryReferenceDialog,
  type MemoryReferenceSelection,
} from './MemoryReferenceDialog';
import './activity-timeline.css';

type TimelinePeriod = 'day' | 'morning' | 'afternoon' | 'evening';
type TimelineActivityKind = 'ordinary_activity' | 'consolidated_activity' | 'unclassified_activity';

interface TimelineApp {
  id: string;
  name: string;
  eventCount: number;
}

interface TimelineSourceRef {
  id: string;
  kind: string;
  referenceKind: MemoryReferenceSelection['kind'];
  label: string;
  locator: string;
  createdAtMs: number;
}

interface TimelineEvidenceEvent {
  id: string;
  timestampMs: number;
  appName: string;
  sourceKind: string;
  summary: string;
  redacted: boolean;
  referenceId: string;
  sourceRefs: TimelineSourceRef[];
}

interface SemanticTimelineTask {
  id: string;
  title: string;
  summary: string;
  period: TimelinePeriod;
  startMs: number;
  endMs: number;
  eventCount: number;
  activityKind: TimelineActivityKind;
  evidenceCount: number;
  redactedEventCount: number;
  apps: TimelineApp[];
  sourceKinds: string[];
  contextGroupIds: string[];
  sourceEventIds: string[];
  sourceRefs: TimelineSourceRef[];
  events: TimelineEvidenceEvent[];
}

interface ActivityCalendarDay {
  date: string;
  status: string;
  organized: boolean;
  modelOrganized: boolean;
  needsRefresh: boolean;
  sourceEventCount: number;
  segmentCount: number;
}

const PERIODS: TimelinePeriod[] = ['day', 'morning', 'afternoon', 'evening'];
const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日'] as const;

export function ActivityTimeline({ initialDate = '' }: { initialDate?: string }) {
  const today = useMemo(localDate, []);
  const [date, setDate] = useState(() => (
    /^\d{4}-\d{2}-\d{2}$/u.test(initialDate) && initialDate <= today
      ? initialDate
      : today
  ));
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const [selectedTaskId, setSelectedTaskId] = useState('');
  const [selectedReference, setSelectedReference] = useState<MemoryReferenceSelection | null>(null);
  useEffect(() => {
    if (!/^\d{4}-\d{2}-\d{2}$/u.test(initialDate) || initialDate > today) return;
    setDate(initialDate);
    setRejectOpen(false);
    setSelectedTaskId('');
    setSelectedReference(null);
  }, [initialDate, today]);
  const organizeRange = useMemo(() => monthRange(date, today), [date, today]);
  const {
    approve,
    build,
    buildJob,
    buildJobError,
    buildJobId,
    buildJobProgress,
    buildJobResult,
    buildJobState,
    calendar,
    canRead,
    canReadCalendar,
    canWrite,
    capabilities,
    reject,
    timeline,
  } = useActivityTimeline(date, true, organizeRange.end);
  const payload = asRecord(timeline.data);
  const calendarPayload = asRecord(calendar.data);
  const calendarSummary = asRecord(calendarPayload.summary);
  const calendarDays = useMemo(
    () => normalizeCalendarDays(calendarPayload),
    [calendarPayload],
  );
  const item = asRecord(payload.timeline);
  const tasks = useMemo(() => normalizeTimelineTasks(item), [item]);
  const taskGroups = useMemo(() => PERIODS.map((period) => ({
    period,
    tasks: tasks.filter((task) => task.period === period),
  })).filter((group) => group.tasks.length), [tasks]);
  const selectedTask = tasks.find((task) => task.id === selectedTaskId);
  const timelineId = stringValue(item.timelineId);
  const status = stringValue(item.status);
  const buildRunning = buildJobState === 'queued' || buildJobState === 'running';
  const buildAwaitingStatus = buildJob.isFetching && !buildJobState;
  const buildActive = build.isPending || buildAwaitingStatus || buildRunning;
  const busy = buildActive || approve.isPending || reject.isPending;
  const buildError = build.error ?? buildJobError;
  const error = timeline.error ?? approve.error ?? reject.error;
  const buildProgressMessage = buildError
    ? friendlyTimelineError(buildError)
    : build.isPending
      ? '正在提交整理任务…'
      : buildAwaitingStatus
        ? '整理任务已受理，正在读取进度…'
        : buildRunning && [
          'activity_timeline_catch_up',
          'activity_timeline_auto_catch_up',
        ].includes(stringValue(buildJobProgress.phase))
          ? catchUpProgressCopy(buildJobProgress)
          : buildRunning
            ? '整理任务已进入队列，等待开始…'
            : buildJobState === 'completed'
              ? catchUpCompletedCopy(buildJobProgress, buildJobResult)
              : '';
  const semanticReady = timelineId
    ? calendarDays.some((day) => (
      day.date === date && day.organized && day.modelOrganized
    ))
    : false;

  const chooseDate = (nextDate: string) => {
    setDate(nextDate);
    setRejectOpen(false);
    setSelectedTaskId('');
    setSelectedReference(null);
  };

  const moveDate = (offset: number) => chooseDate(shiftDate(date, offset));
  const moveMonth = (offset: number) => chooseDate(shiftMonth(date, offset));

  return (
    <section className="activity-timeline activity-timeline--semantic" aria-labelledby="activity-timeline-title">
      <header className="activity-timeline__toolbar">
        <div>
          <span className="activity-timeline__eyebrow">每日活动</span>
          <h2 id="activity-timeline-title">{formatDateHeading(date)}</h2>
        </div>
        <div className="activity-timeline__date-controls">
          <IconButton
            disabled={busy}
            icon={<ChevronLeft size={17} />}
            label="前一天"
            onClick={() => moveDate(-1)}
            size="small"
            tooltip
          />
          <Input
            aria-label="时间线日期"
            disabled={busy}
            max={today}
            onChange={(event) => chooseDate(event.target.value || today)}
            type="date"
            value={date}
          />
          <IconButton
            disabled={busy || date >= today}
            icon={<ChevronRight size={17} />}
            label="后一天"
            onClick={() => moveDate(1)}
            size="small"
            tooltip
          />
          <Button
            disabled={busy || date === today}
            leadingIcon={<CalendarClock size={15} />}
            onClick={() => chooseDate(today)}
            size="small"
            variant="quiet"
          >
            今天
          </Button>
        </div>
      </header>

      {/* Master-detail viewport: the journal is the primary object and owns
          the first screen; the month calendar accompanies it as a side rail
          instead of a dashboard the reader must scroll past. */}
      <div className="activity-timeline__layout">
        <div className="activity-timeline__main">
          <DailyJournal
            canRead={canRead}
            canWrite={canWrite}
            date={date}
            hasError={Boolean(timeline.error)}
            isLoading={capabilities.isPending || (canRead && timeline.isPending)}
            item={item}
            semanticReady={semanticReady}
            onBuild={() => build.mutate({ targetDate: date })}
            onOpenSource={() => setSelectedReference({
              kind: 'timeline',
              referenceId: timelineId,
              label: `${formatDateHeading(date)} 的活动时间线`,
            })}
            onSelectTask={setSelectedTaskId}
            status={status}
            tasks={tasks}
            timelineId={timelineId}
            busy={busy}
          />

          {error ? (
            <InlineNotice title="时间线暂时不可用" tone="danger">
              {friendlyTimelineError(error)}
            </InlineNotice>
          ) : null}

          {!capabilities.isPending && !canRead ? (
            <InlineNotice title="当前服务未开放每日活动读取" tone="warning">
              不会发送时间线请求；更新本机服务后再刷新此页。
            </InlineNotice>
          ) : !capabilities.isPending && canRead && !canWrite ? (
            <InlineNotice title="每日活动为只读状态" tone="info">
              可以查看现有时间线，但当前服务不会接收整理、发布或删除操作。
            </InlineNotice>
          ) : null}

          {capabilities.isPending || (canRead && timeline.isPending) ? (
            <div className="activity-timeline__loading" role="status">
              <RefreshCw aria-hidden="true" size={18} />
              <span>正在读取当天活动</span>
            </div>
          ) : !canRead || timeline.error ? null : timelineId && !semanticReady ? (
            <div className="activity-timeline__semantic-empty">
              <Sparkles aria-hidden="true" size={19} />
              <span>当天来源已经收集；整理并核对通过后，这里会显示当天的活动故事。</span>
            </div>
          ) : timelineId ? (
            <>
              {tasks.length ? (
                <ActivityDayMap date={date} onSelect={setSelectedTaskId} tasks={tasks} />
              ) : null}

              {taskGroups.length ? (
                <div className="activity-timeline__periods" aria-label={`${date} 活动分段`}>
                  {taskGroups.map((group) => (
                    <TimelinePeriodBand
                      key={group.period}
                      onSelect={setSelectedTaskId}
                      period={group.period}
                      tasks={group.tasks}
                    />
                  ))}
                </div>
              ) : (
                <div className="activity-timeline__semantic-empty">
                  <ListTree aria-hidden="true" size={19} />
                  <span>这份时间线还没有可显示的活动记录。</span>
                </div>
              )}

              <footer className="activity-timeline__decision-bar">
                <div>
                  <LockKeyhole aria-hidden="true" size={16} />
                  <span>{decisionCopy(status, stringValue(item.approvedBookId))}</span>
                </div>
                <div>
                  {status === 'draft' && semanticReady ? (
                    <>
                      <Button
                        disabled={busy || !canWrite}
                        leadingIcon={<X size={15} />}
                        onClick={() => setRejectOpen(true)}
                        size="small"
                        variant="quiet"
                      >
                        驳回
                      </Button>
                      <Button
                        disabled={busy || !canWrite}
                        leadingIcon={<Check size={15} />}
                        onClick={() => approve.mutate({ timelineId, sourceEventHash: stringValue(item.sourceEventHash) })}
                        size="small"
                        variant="primary"
                      >
                        立即发布
                      </Button>
                    </>
                  ) : (
                    <Button
                      disabled={busy || !canWrite}
                      leadingIcon={<Sparkles size={15} />}
                      loading={build.isPending}
                      onClick={() => build.mutate({ targetDate: date })}
                      size="small"
                    >
                      {semanticReady ? '重新整理' : '整理这一天'}
                    </Button>
                  )}
                </div>
              </footer>
            </>
          ) : null}
        </div>

        <aside className="activity-timeline__rail">
          <ActivityTimelineCalendar
            busy={busy}
            canWrite={canWrite}
            date={date}
            days={calendarDays}
            error={calendar.error as Error | null}
            isLoading={capabilities.isPending || (canReadCalendar && calendar.isPending)}
            onMoveMonth={moveMonth}
            onOrganizeMonth={() => build.mutate({
              targetDate: organizeRange.end,
              throughToday: true,
              rangeStartDate: organizeRange.start,
            })}
            organizeRange={organizeRange}
            organizeActive={buildActive}
            organizeFailed={Boolean(buildError)}
            organizeJobId={buildJobId}
            organizeJobState={buildJobState}
            organizeMessage={buildProgressMessage}
            onSelect={chooseDate}
            summary={calendarSummary}
            today={today}
            unavailable={!capabilities.isPending && !canReadCalendar}
          />
        </aside>
      </div>

      <TaskDetailDialog
        onClose={() => setSelectedTaskId('')}
        onOpenReference={setSelectedReference}
        task={selectedTask}
      />

      {selectedReference ? (
        <MemoryReferenceDialog
          {...selectedReference}
          onOpenChange={(open) => { if (!open) setSelectedReference(null); }}
        />
      ) : null}

      <Dialog
        onOpenChange={(open) => {
          setRejectOpen(open);
          if (!open) setRejectReason('');
        }}
        open={rejectOpen}
      >
        <DialogContent className="activity-timeline__dialog">
          <DialogHeader>
            <DialogTitle>驳回当天整理</DialogTitle>
            <DialogDescription>保留操作记录，但不会发布这份时间线。</DialogDescription>
          </DialogHeader>
          <Field htmlFor="timeline-reject-reason" label="原因">
            <Input
              id="timeline-reject-reason"
              maxLength={500}
              onChange={(event) => setRejectReason(event.target.value)}
              placeholder="例如：任务归并不准确"
              value={rejectReason}
            />
          </Field>
          <DialogFooter>
            <Button onClick={() => setRejectOpen(false)} variant="quiet">取消</Button>
            <Button
              disabled={!canWrite || !rejectReason.trim()}
              loading={reject.isPending}
              onClick={() => reject.mutate(
                { timelineId, reason: rejectReason.trim() },
                { onSuccess: () => { setRejectOpen(false); setRejectReason(''); } },
              )}
              variant="danger"
            >
              确认驳回
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

function DailyJournal({
  busy,
  canRead,
  canWrite,
  date,
  hasError,
  isLoading,
  item,
  semanticReady,
  onBuild,
  onOpenSource,
  onSelectTask,
  status,
  tasks,
  timelineId,
}: {
  busy: boolean;
  canRead: boolean;
  canWrite: boolean;
  date: string;
  hasError: boolean;
  isLoading: boolean;
  item: Record<string, unknown>;
  semanticReady: boolean;
  onBuild: () => void;
  onOpenSource: () => void;
  onSelectTask: (taskId: string) => void;
  status: string;
  tasks: SemanticTimelineTask[];
  timelineId: string;
}) {
  const highlights = tasks.slice(0, 3);
  const apps = topJournalApps(tasks, 5);
  return (
    <section className="daily-journal" aria-labelledby="daily-journal-title" data-state={timelineId ? status : 'empty'}>
      <header className="daily-journal__header">
        <div className="daily-journal__identity">
          <span className="daily-journal__mark" aria-hidden="true"><BookOpenText size={18} /></span>
          <div>
            <span>时间线日记</span>
            <h3 id="daily-journal-title">{formatDateHeading(date)}的每日日记</h3>
          </div>
        </div>
        {timelineId ? (
          <StatusBadge
            label={semanticReady ? timelineStatusLabel(status) : '待整理成日记'}
            tone={semanticReady ? timelineStatusTone(status) : 'info'}
          />
        ) : null}
      </header>

      {isLoading ? (
        <div className="daily-journal__loading" role="status">
          <RefreshCw aria-hidden="true" size={17} />
          <span>正在展开这一天的记录…</span>
        </div>
      ) : !canRead || hasError ? (
        <div className="daily-journal__empty-copy">
          <strong>日记暂时无法读取</strong>
          <span>日历仍保留整理状态；服务恢复后可继续查看当天内容。</span>
        </div>
      ) : !timelineId ? (
        <div className="daily-journal__empty-copy">
          <strong>这一天还没有日记</strong>
          <span>整理当天时间线后，这里会形成可回看、可追溯的日记，而不是复制一份新数据。</span>
          <Button
            disabled={busy || !canWrite}
            leadingIcon={<Sparkles size={15} />}
            onClick={onBuild}
            size="small"
            variant="primary"
          >
            生成这天的日记
          </Button>
        </div>
      ) : !semanticReady ? (
        <div className="daily-journal__empty-copy">
          <strong>这一天还没有整理成日记</strong>
          <span>目前只按来源做了分组，还没有整理核对成日记；原始输入不会被直接当作日记正文。</span>
          <Button
            disabled={busy || !canWrite}
            leadingIcon={<Sparkles size={15} />}
            loading={busy}
            onClick={onBuild}
            size="small"
            variant="primary"
          >
            整理这一天
          </Button>
        </div>
      ) : (
        <div className="daily-journal__body">
          <article className="daily-journal__story">
            <p>{stringValue(item.summary, '当天活动已完成结构化整理。')}</p>
            {highlights.length ? (
              <ol className="daily-journal__highlights" aria-label="日记重点">
                {highlights.map((task) => (
                  <li key={task.id}>
                    <button
                      aria-label={`查看日记条目：${task.title}`}
                      onClick={() => onSelectTask(task.id)}
                      type="button"
                    >
                      <time>{formatTimeRange(task.startMs, task.endMs)}</time>
                      <span><strong>{task.title}</strong><small>{journalTaskCaption(task)}</small></span>
                      <ChevronRight aria-hidden="true" size={15} />
                    </button>
                  </li>
                ))}
              </ol>
            ) : <span className="daily-journal__quiet">当天没有可展示的活动条目。</span>}
            <button className="daily-journal__source" onClick={onOpenSource} type="button">
              <Fingerprint aria-hidden="true" size={13} />
              <span>查看日记与当天来源</span>
              <ChevronRight aria-hidden="true" size={13} />
            </button>
          </article>

          <aside className="daily-journal__facts" aria-label="今日日记摘要">
            <dl>
              <div><dt>活动</dt><dd>{tasks.length} 项活动</dd></div>
              <div><dt>记录时间范围合计</dt><dd>{formatDuration(sumTaskSpan(tasks))}</dd></div>
              <div><dt>来源</dt><dd>{sumEvidenceCount(tasks)} 条</dd></div>
              <div><dt>更新时间</dt><dd>{formatTimestamp(numberValue(item.updatedAtMs))}</dd></div>
            </dl>
            {apps.length ? (
              <div className="daily-journal__apps">
                <span>今日足迹</span>
                <ul>
                  {apps.map((app) => (
                    <li key={app.id}>
                      <i aria-hidden="true" data-app-tone={appTone(app.id)} />
                      <span>{app.name}</span>
                      {app.eventCount ? <small>{app.eventCount} 条</small> : null}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </aside>
        </div>
      )}
      <footer className="daily-journal__boundary">
        日记由当天时间线维护；重新整理会更新它，来源记录不会被复制或改写。
      </footer>
    </section>
  );
}

function ActivityTimelineCalendar({
  busy,
  canWrite,
  date,
  days,
  error,
  isLoading,
  onMoveMonth,
  onOrganizeMonth,
  organizeRange,
  organizeActive,
  organizeFailed,
  organizeJobId,
  organizeJobState,
  organizeMessage,
  onSelect,
  summary,
  today,
  unavailable,
}: {
  busy: boolean;
  canWrite: boolean;
  date: string;
  days: readonly ActivityCalendarDay[];
  error: Error | null;
  isLoading: boolean;
  onMoveMonth: (offset: number) => void;
  onOrganizeMonth: () => void;
  organizeRange: { start: string; end: string };
  organizeActive: boolean;
  organizeFailed: boolean;
  organizeJobId: string;
  organizeJobState: string;
  organizeMessage: string;
  onSelect: (date: string) => void;
  summary: Record<string, unknown>;
  today: string;
  unavailable: boolean;
}) {
  const month = date.slice(0, 7);
  const cells = calendarCells(month);
  const byDate = new Map(days.map((day) => [day.date, day]));
  const canMoveForward = month < today.slice(0, 7);
  const [organizePreviewOpen, setOrganizePreviewOpen] = useState(false);
  const pendingDays = days.filter((day) => (
    day.date <= today && (!day.organized || day.needsRefresh)
  ));
  const pendingDayCount = Math.max(
    pendingDays.length,
    numberValue(summary.waitingDayCount) + numberValue(summary.outdatedDayCount),
  );
  const pendingSourceCount = pendingDays.reduce(
    (total, day) => total + day.sourceEventCount,
    0,
  );

  return (
    <section className="activity-calendar" aria-labelledby="activity-calendar-title">
      <header className="activity-calendar__header">
        <div>
          <span className="activity-calendar__kicker">月度整理轨迹</span>
          <h3 id="activity-calendar-title">{formatMonthHeading(month)}</h3>
          <p>点击日期，直接查看当天时间线和来源。</p>
        </div>
        <div className="activity-calendar__month-controls">
          <Button
            disabled={busy || !canWrite}
            leadingIcon={<Sparkles size={15} />}
            loading={organizeActive}
            onClick={() => setOrganizePreviewOpen(true)}
            size="small"
            variant="primary"
          >
            {organizeActive ? '正在整理' : '整理本月'}
          </Button>
          <IconButton
            icon={<ChevronLeft size={16} />}
            label="上个月"
            onClick={() => onMoveMonth(-1)}
            size="small"
            tooltip
          />
          <Button
            disabled={month === today.slice(0, 7)}
            onClick={() => onSelect(today)}
            size="small"
            variant="quiet"
          >
            本月
          </Button>
          <IconButton
            disabled={!canMoveForward}
            icon={<ChevronRight size={16} />}
            label="下个月"
            onClick={() => onMoveMonth(1)}
            size="small"
            tooltip
          />
        </div>
      </header>

      {organizeMessage ? (
        <div
          aria-label="历史日记整理进度"
          className="activity-calendar__organize-status"
          data-tone={organizeFailed ? 'danger' : 'info'}
          role={organizeFailed ? 'alert' : 'status'}
        >
          {organizeFailed
            ? <X aria-hidden="true" size={15} />
            : organizeJobState === 'completed'
              ? <Check aria-hidden="true" size={15} />
              : <RefreshCw aria-hidden="true" size={15} />}
          <span>
            <strong>{organizeMessage}</strong>
            {organizeJobId ? <small>任务 {organizeJobId}</small> : null}
          </span>
          {organizeFailed ? (
            <Button onClick={() => setOrganizePreviewOpen(true)} size="small" variant="quiet">重新检查范围</Button>
          ) : null}
        </div>
      ) : null}

      <Dialog open={organizePreviewOpen} onOpenChange={setOrganizePreviewOpen}>
        <DialogContent className="activity-calendar__organize-preview">
          <DialogHeader>
            <DialogTitle>整理本月</DialogTitle>
            <DialogDescription>
              以当前月历返回的待处理范围为准；本次只整理这个月，不会带入其他月份，也不会改写来源记录。
            </DialogDescription>
          </DialogHeader>
          <div className="activity-calendar__organize-scope">
            <strong>{pendingDayCount} 天待整理 · {pendingSourceCount} 条来源</strong>
            <span>范围：{organizeRange.start} 至 {organizeRange.end}</span>
            {pendingDays.length ? (
              <div>
                <small>待整理日期示例</small>
                <ul>
                  {pendingDays.slice(0, 3).map((day) => (
                    <li key={day.date}>
                      <time>{day.date}</time>
                      <span>{day.needsRefresh ? '有新来源，需重新整理' : '尚未整理'} · {day.sourceEventCount} 条来源</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : <p>当前月历未返回待整理日期。</p>}
          </div>
          <DialogFooter>
            <Button onClick={() => setOrganizePreviewOpen(false)} variant="quiet">取消</Button>
            <Button
              disabled={organizeActive || pendingDayCount === 0}
              loading={organizeActive}
              onClick={() => {
                setOrganizePreviewOpen(false);
                onOrganizeMonth();
              }}
              variant="primary"
            >
              确认整理本月
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <div className="activity-calendar__summary" aria-live="polite">
        <span><strong>{numberValue(summary.activityDayCount)}</strong> 天有活动</span>
        <span data-tone="success"><strong>{numberValue(summary.organizedDayCount)}</strong> 天已整理</span>
        <span data-tone="warning"><strong>{numberValue(summary.waitingDayCount)}</strong> 天待整理</span>
        {numberValue(summary.outdatedDayCount) ? (
          <span data-tone="info"><strong>{numberValue(summary.outdatedDayCount)}</strong> 天有新增</span>
        ) : null}
        <span><strong>{numberValue(summary.sourceEventCount)}</strong> 条来源</span>
      </div>

      {unavailable ? (
        <div className="activity-calendar__message">当前服务暂未提供月度时间线状态，仍可按日期查看。</div>
      ) : error ? (
        <div className="activity-calendar__message" role="alert">月度整理状态读取失败；当天时间线仍可继续使用。</div>
      ) : (
        <>
          <div className="activity-calendar__weekdays" aria-hidden="true">
            {WEEKDAYS.map((weekday) => <span key={weekday}>周{weekday}</span>)}
          </div>
          <div className="activity-calendar__grid" aria-busy={isLoading || undefined}>
            {cells.map((cell, index) => {
              if (!cell) return <span aria-hidden="true" className="activity-calendar__blank" key={`blank:${index}`} />;
              const day = byDate.get(cell);
              const state = calendarDayState(day);
              const disabled = cell > today;
              return (
                <button
                  aria-label={calendarDayAriaLabel(cell, day)}
                  aria-pressed={cell === date}
                  className="activity-calendar__day"
                  data-state={state}
                  data-today={cell === today || undefined}
                  disabled={disabled}
                  key={cell}
                  onClick={() => onSelect(cell)}
                  type="button"
                >
                  <span className="activity-calendar__date">{Number(cell.slice(-2))}</span>
                  <span className="activity-calendar__state">
                    {calendarStateIcon(state)}
                    <small>{calendarStateLabel(state)}</small>
                  </span>
                  {day?.sourceEventCount ? <b>{day.sourceEventCount} 条</b> : <b aria-hidden="true">—</b>}
                </button>
              );
            })}
          </div>
          {isLoading ? <div className="activity-calendar__loading" role="status">正在读取本月整理轨迹…</div> : null}
          <div className="activity-calendar__legend" aria-label="日历状态图例">
            {(['approved', 'draft', 'waiting', 'refresh'] as const).map((state) => (
              <span data-state={state} key={state}>{calendarStateIcon(state)}{calendarStateLabel(state)}</span>
            ))}
          </div>
          <p className="activity-calendar__boundary">
            “已整理”表示当天来源已形成当前有效时间线；不代表每条输入都已进入长期记忆。
          </p>
        </>
      )}
    </section>
  );
}

function ActivityDayMap({
  date,
  onSelect,
  tasks,
}: {
  date: string;
  onSelect: (taskId: string) => void;
  tasks: SemanticTimelineTask[];
}) {
  const bounds = dayBounds(date);
  return (
    <section className="activity-day-map" aria-label={`${date} 活动分布`}>
      <header>
        <div>
          <Clock3 aria-hidden="true" size={15} />
          <strong>一天的活动分布</strong>
        </div>
        <span>时间范围按记录的首尾时间计算，不代表全程持续活跃；点击活动可查看来源</span>
      </header>
      <div className="activity-day-map__axis" aria-hidden="true">
        {[0, 6, 12, 18, 24].map((hour) => <span key={hour}>{String(hour).padStart(2, '0')}:00</span>)}
      </div>
      <div className="activity-day-map__rows">
        {tasks.map((task) => {
          const start = percentInDay(task.startMs, bounds.start, bounds.end);
          const end = percentInDay(Math.max(task.startMs + 60_000, task.endMs), bounds.start, bounds.end);
          const width = Math.max(1.8, end - start);
          return (
            <div className="activity-day-map__row" key={task.id}>
              <button
                aria-label={`${task.title}，${formatTimeRange(task.startMs, task.endMs)}`}
                data-period={task.period}
                onClick={() => onSelect(task.id)}
                style={{ left: `${start}%`, width: `${Math.min(width, 100 - start)}%` }}
                title={`${formatTimeRange(task.startMs, task.endMs)} · ${task.title}`}
                type="button"
              >
                <span>{task.title}</span>
              </button>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function dayBounds(date: string): { start: number; end: number } {
  const start = new Date(`${date}T00:00:00`).getTime();
  return { start, end: start + 24 * 60 * 60 * 1000 };
}

function percentInDay(value: number, start: number, end: number): number {
  return Math.max(0, Math.min(100, ((value - start) / (end - start)) * 100));
}

function TimelinePeriodBand({
  onSelect,
  period,
  tasks,
}: {
  onSelect: (taskId: string) => void;
  period: TimelinePeriod;
  tasks: SemanticTimelineTask[];
}) {
  return (
    <section className="activity-timeline__period" data-period={period}>
      <header className="activity-timeline__period-header">
        <div>
          <span className="activity-timeline__period-icon" aria-hidden="true">
            {period === 'day' ? <CalendarDays size={16} /> : <Clock3 size={16} />}
          </span>
          <div>
            <h3>{periodLabel(period)}</h3>
            <p>{periodDescription(period)}</p>
          </div>
        </div>
        <span>{tasks.length} 项 · 记录时间范围 {formatDuration(sumTaskSpan(tasks))}</span>
      </header>
      <div className="activity-timeline__task-list">
        {tasks.map((task) => (
          <button
            key={task.id}
            aria-label={`查看任务：${task.title}`}
            className="activity-timeline__task"
            onClick={() => onSelect(task.id)}
            type="button"
          >
            <span className="activity-timeline__task-time">
              <time dateTime={task.startMs ? new Date(task.startMs).toISOString() : undefined}>
                {formatTimeRange(task.startMs, task.endMs)}
              </time>
              <small>{activityKindLabel(task.activityKind)} · 记录时间范围 {formatDuration(task.endMs - task.startMs)}</small>
            </span>
            <span className="activity-timeline__task-main">
              <strong>{task.title}</strong>
              <span className="activity-timeline__task-summary">{task.summary}</span>
              <span className="activity-timeline__task-apps" aria-label="参与应用">
                <Monitor aria-hidden="true" size={13} />
                {task.apps.map((app) => (
                  <span key={app.id}>
                    <i aria-hidden="true" data-app-tone={appTone(app.id)} />
                    {app.name}
                  </span>
                ))}
              </span>
            </span>
            <span className="activity-timeline__task-stats">
              <StatusBadge
                label={activityKindLabel(task.activityKind)}
                tone={activityKindTone(task.activityKind)}
              />
              <span><Database aria-hidden="true" size={13} />{task.evidenceCount} 条来源</span>
              <span><ListTree aria-hidden="true" size={13} />{task.eventCount} 条事件</span>
              {task.redactedEventCount ? <span data-tone="warning">{task.redactedEventCount} 条脱敏</span> : null}
            </span>
            <ChevronRight className="activity-timeline__task-open" aria-hidden="true" size={17} />
          </button>
        ))}
      </div>
    </section>
  );
}

function TaskDetailDialog({
  onClose,
  onOpenReference,
  task,
}: {
  onClose: () => void;
  onOpenReference: (reference: MemoryReferenceSelection) => void;
  task: SemanticTimelineTask | undefined;
}) {
  const [visibleEventCount, setVisibleEventCount] = useState(24);
  useEffect(() => setVisibleEventCount(24), [task?.id]);
  if (!task) return null;
  const visibleEvents = task.events.slice(0, visibleEventCount);
  const remainingEventCount = task.events.length - visibleEvents.length;
  const eventReferenceKeys = new Set(
    task.events.flatMap((event) => event.sourceRefs.map(sourceReferenceKey)),
  );
  const taskLevelRefs = task.sourceRefs.filter((ref) => !eventReferenceKeys.has(sourceReferenceKey(ref)));
  return (
    <Dialog onOpenChange={(open) => { if (!open) onClose(); }} open>
      <DialogContent className="activity-timeline__task-dialog">
        <DialogHeader>
          <DialogTitle>{task.title}</DialogTitle>
          <DialogDescription>
            {periodLabel(task.period)} · {formatTimeRange(task.startMs, task.endMs)} · {activityKindLabel(task.activityKind)} · 记录时间范围 {formatDuration(task.endMs - task.startMs)}
          </DialogDescription>
        </DialogHeader>

        <div className="activity-timeline__task-detail">
          <p className="activity-timeline__task-detail-summary">{task.summary}</p>
          <dl className="activity-timeline__task-detail-metrics">
            <div><dt>参与应用</dt><dd>{task.apps.length}</dd></div>
            <div><dt>事件</dt><dd>{task.eventCount}</dd></div>
            <div><dt>来源</dt><dd>{task.evidenceCount}</dd></div>
            <div><dt>脱敏</dt><dd>{task.redactedEventCount}</dd></div>
          </dl>

          <section className="activity-timeline__detail-section">
            <h3><Monitor aria-hidden="true" size={15} />参与应用</h3>
            <div className="activity-timeline__detail-apps">
              {task.apps.map((app) => (
                <span key={app.id}>
                  <i aria-hidden="true" data-app-tone={appTone(app.id)} />
                  <strong>{app.name}</strong>
                  {app.eventCount ? <small>{app.eventCount} 条</small> : null}
                </span>
              ))}
            </div>
          </section>

          <section className="activity-timeline__detail-section">
            <h3><Database aria-hidden="true" size={15} />相关来源</h3>
            <p>时间、分类和来源来自本机活动记录。原始输入与当时上下文只在所属范围内按需读取，不会复制到时间线。</p>
            {taskLevelRefs.length ? (
              <SourceReferenceDetails
                onOpenReference={onOpenReference}
                refs={taskLevelRefs}
                title="活动相关来源"
              />
            ) : null}
            <div className="activity-timeline__event-list">
              {visibleEvents.map((event, index) => (
                <Disclosure
                  className="activity-timeline__event"
                  contentClassName="activity-timeline__event-body"
                  key={`${event.id}-${index}`}
                  summary={
                    <>
                      <span>事件 {index + 1}</span>
                      <strong>{event.summary || `记录 #${event.id}`}</strong>
                      <ChevronDown aria-hidden="true" size={15} />
                    </>
                  }
                >
                  <div className="activity-timeline__event-meta">
                    {event.timestampMs ? <time dateTime={new Date(event.timestampMs).toISOString()}>{formatTimestamp(event.timestampMs)}</time> : null}
                    {event.appName ? <span>{event.appName}</span> : null}
                    {event.sourceKind ? <span>{sourceLabel(event.sourceKind)}</span> : null}
                    {event.redacted ? <span data-tone="warning">内容已脱敏</span> : null}
                  </div>
                  {event.summary ? <p>{event.summary}</p> : (
                    <p>这条记录暂时没有可展示的摘要。</p>
                  )}
                  {event.referenceId ? (
                    <button
                      className="activity-timeline__open-event"
                      onClick={() => onOpenReference({
                        kind: 'event',
                        referenceId: event.referenceId,
                        label: event.summary || `记录 #${event.id}`,
                      })}
                      type="button"
                    >
                      <ExternalLink aria-hidden="true" size={13} />
                      <span>打开来源记录</span>
                      <ChevronRight aria-hidden="true" size={13} />
                    </button>
                  ) : null}
                  {event.sourceRefs.length ? (
                    <SourceReferenceDetails
                      onOpenReference={onOpenReference}
                      refs={event.sourceRefs}
                      title={`相关来源 · ${event.sourceRefs.length}`}
                    />
                  ) : (
                    <p className="activity-timeline__source-unavailable">
                      这条记录暂时没有可打开的来源。
                    </p>
                  )}
                </Disclosure>
              ))}
            </div>
            {!visibleEvents.length ? (
              <div className="activity-timeline__evidence-empty">没有可展开的来源记录。</div>
            ) : null}
            {remainingEventCount > 0 ? (
              <div className="activity-timeline__evidence-limit">
                <span>当前 {visibleEvents.length} / {task.events.length} 条</span>
                <Button
                  aria-label={`再显示 ${Math.min(24, remainingEventCount)} 条事件，当前 ${visibleEvents.length} / ${task.events.length}`}
                  onClick={() => setVisibleEventCount((count) => Math.min(task.events.length, count + 24))}
                  size="small"
                  variant="quiet"
                >
                  再显示 {Math.min(24, remainingEventCount)} 条
                </Button>
              </div>
            ) : null}
          </section>
        </div>

        <DialogFooter>
          <Button onClick={onClose}>完成查看</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SourceReferenceDetails({
  onOpenReference,
  refs,
  title,
}: {
  onOpenReference: (reference: MemoryReferenceSelection) => void;
  refs: TimelineSourceRef[];
  title: string;
}) {
  return (
    <Disclosure
      className="activity-timeline__source-refs"
      contentClassName="activity-timeline__source-refs-body"
      summary={<><span>{title}</span><ChevronDown aria-hidden="true" size={14} /></>}
    >
      <ul>
        {refs.map((ref, index) => (
          <li key={`${ref.id}-${index}`}>
            <button
              onClick={() => onOpenReference({
                kind: ref.referenceKind,
                referenceId: ref.id,
                label: ref.label,
              })}
              type="button"
            >
              <Fingerprint aria-hidden="true" size={13} />
              <span>
                <strong>{ref.label}</strong>
                <small>{sourceLabel(ref.kind)} · {ref.locator || ref.id}</small>
              </span>
              {ref.createdAtMs ? (
                <time dateTime={new Date(ref.createdAtMs).toISOString()}>{formatTimestamp(ref.createdAtMs)}</time>
              ) : null}
              <ChevronRight aria-hidden="true" size={13} />
            </button>
          </li>
        ))}
      </ul>
    </Disclosure>
  );
}

function normalizeTimelineTasks(item: Record<string, unknown>): SemanticTimelineTask[] {
  return timelineTaskRecords(item).map(({ record, period }, index) => normalizeTimelineTask(record, index, period));
}

function timelineTaskRecords(item: Record<string, unknown>): Array<{ record: Record<string, unknown>; period: string }> {
  for (const key of ['semanticTasks', 'tasks']) {
    const records = arrayRecords(item[key]);
    if (records.length) return records.map((record) => ({ record, period: '' }));
  }
  for (const key of ['semanticTaskBands', 'taskBands', 'periods']) {
    const bands = arrayRecords(item[key]);
    const records = bands.flatMap((band) => {
      const period = stringValue(band.period) || stringValue(band.id) || stringValue(band.label);
      return arrayRecords(band.tasks).map((record) => ({ record, period }));
    });
    if (records.length) return records;
  }
  return arrayRecords(item.segments).map((record) => ({ record, period: '' }));
}

function normalizeTimelineTask(
  task: Record<string, unknown>,
  index: number,
  inheritedPeriod: string,
): SemanticTimelineTask {
  const startMs = firstNumber(task, ['startMs', 'startedAtMs', 'startAtMs']);
  const endMs = Math.max(startMs, firstNumber(task, ['endMs', 'endedAtMs', 'endAtMs'], startMs));
  const apps = normalizeApps(task);
  const summary = firstString(task, ['summary', 'description', 'detail'], '该任务没有可显示摘要。');
  const sourceEventIds = uniqueStrings(firstArray(task, ['sourceEventIds', 'evidenceEventIds', 'eventIds']));
  const sourceRefs = dedupeSourceRefs(normalizeSourceRefs(firstArray(task, ['sourceRefs', 'references', 'evidenceRefs'])));
  const events = normalizeEvents(task, sourceEventIds);
  const eventCount = firstNumber(task, ['eventCount'], events.length || sourceEventIds.length);
  const evidenceCount = firstNumber(
    task,
    ['evidenceCount', 'sourceEventCount'],
    sourceEventIds.length || events.length || eventCount,
  );
  return {
    id: firstString(task, ['taskId', 'semanticTaskId', 'segmentId', 'id'], `semantic-task:${index}`),
    title: firstString(task, ['title', 'taskTitle', 'name'], deriveTaskTitle(summary, apps, index)),
    summary,
    period: normalizePeriod(firstString(task, ['period', 'dayPart'], inheritedPeriod), startMs, endMs),
    activityKind: normalizeActivityKind(firstString(task, ['activityKind'])),
    startMs,
    endMs,
    eventCount,
    evidenceCount,
    redactedEventCount: firstNumber(task, ['redactedEventCount']),
    apps,
    sourceKinds: uniqueStrings(firstArray(task, ['sourceKinds', 'sources'])),
    contextGroupIds: uniqueStrings(firstArray(task, ['contextGroupIds', 'groupIds'])),
    sourceEventIds,
    sourceRefs,
    events,
  };
}

function normalizeApps(task: Record<string, unknown>): TimelineApp[] {
  const candidates = firstArray(task, ['apps', 'participatingApps', 'applications']);
  const apps = candidates.flatMap((value, index): TimelineApp[] => {
    if (typeof value === 'string' && value.trim()) {
      return [{ id: value.trim(), name: friendlyAppName(value.trim()), eventCount: 0 }];
    }
    const app = asRecord(value);
    if (!Object.keys(app).length) return [];
    const id = firstString(app, ['bundleId', 'appId', 'id', 'app', 'name'], `app:${index}`);
    return [{
      id,
      name: firstString(app, ['displayName', 'name', 'label'], friendlyAppName(id)),
      eventCount: firstNumber(app, ['eventCount', 'count']),
    }];
  });
  const singleApp = firstString(task, ['app', 'bundleId']);
  if (!apps.length && singleApp) {
    apps.push({ id: singleApp, name: friendlyAppName(singleApp), eventCount: firstNumber(task, ['eventCount']) });
  }
  if (!apps.length) apps.push({ id: 'unknown-app', name: '未知应用', eventCount: 0 });
  return dedupeApps(apps);
}

function normalizeEvents(task: Record<string, unknown>, sourceEventIds: string[]): TimelineEvidenceEvent[] {
  const evidence = asRecord(task.evidence);
  const candidates = firstArray(task, ['events', 'eventRefs', 'evidenceEvents']);
  const evidenceRefs = firstArray(task, ['evidenceRefs']);
  const nestedEvents = firstArray(evidence, ['events', 'eventRefs']);
  const rawEvents = candidates.length
    ? candidates
    : nestedEvents.length
      ? nestedEvents
      : evidenceRefs.filter(isEventReference);
  if (!rawEvents.length) {
    return sourceEventIds.map((id) => ({
      id,
      timestampMs: 0,
      appName: '',
      sourceKind: '',
      summary: '',
      redacted: false,
      referenceId: id,
      sourceRefs: [],
    }));
  }
  return rawEvents.flatMap((value, index): TimelineEvidenceEvent[] => {
    if (typeof value === 'string' || typeof value === 'number') {
      return [{
        id: String(value),
        timestampMs: 0,
        appName: '',
        sourceKind: '',
        summary: '',
        redacted: false,
        referenceId: String(value),
        sourceRefs: [],
      }];
    }
    const event = asRecord(value);
    if (!Object.keys(event).length) return [];
    const app = asRecord(event.app);
    const appId = firstString(app, ['bundleId', 'id', 'name']) || firstString(event, ['app', 'bundleId']);
    const id = firstString(event, ['eventId', 'sourceEventId', 'id'], `event:${index}`);
    const referenceId = firstString(event, ['referenceId', 'sourceId', 'refId'], id);
    const inlineReference = normalizeSourceRefs([event]);
    const nestedReferences = normalizeSourceRefs(firstArray(event, ['sourceRefs', 'references', 'evidenceRefs', 'sources']));
    return [{
      id,
      timestampMs: firstNumber(event, ['occurredAtMs', 'createdAtMs', 'timestampMs']),
      appName: firstString(app, ['displayName', 'name'], friendlyAppName(appId)) || friendlyAppName(appId),
      sourceKind: firstString(event, ['sourceKind', 'source', 'kind', 'sourceType']),
      summary: firstString(event, ['summary', 'preview', 'text', 'description']),
      redacted: event.redacted === true
        || event.isRedacted === true
        || firstString(event, ['preview', 'summary']).includes('已脱敏'),
      referenceId,
      sourceRefs: dedupeSourceRefs(nestedReferences.length ? nestedReferences : inlineReference),
    }];
  });
}

function normalizeSourceRefs(values: unknown[]): TimelineSourceRef[] {
  return values.flatMap((value, index): TimelineSourceRef[] => {
    if (typeof value === 'string' || typeof value === 'number') {
      const id = String(value);
      return [{
        id,
        kind: 'reference',
        referenceKind: inferMemoryReferenceKind('', id),
        label: id,
        locator: '',
        createdAtMs: 0,
      }];
    }
    const ref = asRecord(value);
    if (!Object.keys(ref).length) return [];
    const locator = firstString(ref, ['locator', 'uri', 'url', 'path']);
    const eventId = firstString(ref, ['eventId']);
    const id = firstString(
      ref,
      ['referenceId', 'refId', 'sourceId', 'sourceRef', 'id'],
      eventId || locator || `reference:${index}`,
    );
    const kind = firstString(ref, ['kind', 'sourceKind', 'sourceType', 'type'], 'reference');
    return [{
      id,
      kind,
      referenceKind: inferMemoryReferenceKind(kind, id),
      label: firstString(ref, ['label', 'title', 'name', 'preview'], id),
      locator,
      createdAtMs: firstNumber(ref, ['occurredAtMs', 'createdAtMs', 'timestampMs']),
    }];
  });
}

function isEventReference(value: unknown): boolean {
  const record = asRecord(value);
  if (!Object.keys(record).length) return false;
  const sourceType = firstString(record, ['sourceType', 'kind', 'type']).toLowerCase();
  return Boolean(
    firstString(record, ['eventId', 'sourceEventId'])
    || sourceType === 'input_event'
    || sourceType === 'event',
  );
}

function inferMemoryReferenceKind(
  rawKind: string,
  referenceId: string,
): MemoryReferenceSelection['kind'] {
  const kind = rawKind.trim().toLowerCase().replaceAll('-', '_');
  if (['event', 'input_event', 'input_event_bundle'].includes(kind)) return 'event';
  if (['evidence', 'agent_evidence', 'memory_evidence'].includes(kind)) return 'evidence';
  if (['atom', 'memory_atom'].includes(kind)) return 'atom';
  if (['book', 'memory_book', 'topic_book'].includes(kind)) return 'book';
  if (['timeline', 'activity_timeline', 'activity_timeline_segment'].includes(kind)) return 'timeline';
  if (['role_book', 'role_book_revision'].includes(kind)) return 'role_book_revision';
  const normalizedId = referenceId.toLowerCase();
  if (/^\d+$/u.test(normalizedId) || normalizedId.startsWith('event:') || normalizedId.startsWith('input-memory:')) return 'event';
  if (normalizedId.startsWith('evidence:') || normalizedId.startsWith('agent-memory:')) return 'evidence';
  if (normalizedId.startsWith('atom:')) return 'atom';
  if (normalizedId.startsWith('book:')) return 'book';
  if (normalizedId.startsWith('timeline:')) return 'timeline';
  if (normalizedId.startsWith('revision:') || normalizedId.startsWith('role-book:')) return 'role_book_revision';
  return 'evidence';
}

function dedupeSourceRefs(refs: TimelineSourceRef[]): TimelineSourceRef[] {
  const byIdentity = new Map<string, TimelineSourceRef>();
  for (const ref of refs) {
    const identity = `${ref.referenceKind}\u0000${ref.id}`;
    if (!byIdentity.has(identity)) byIdentity.set(identity, ref);
  }
  return [...byIdentity.values()];
}

function sourceReferenceKey(ref: TimelineSourceRef): string {
  return `${ref.referenceKind}\u0000${ref.id}`;
}

function firstArray(record: Record<string, unknown>, keys: string[]): unknown[] {
  for (const key of keys) {
    if (Array.isArray(record[key])) return record[key] as unknown[];
  }
  return [];
}

function firstString(
  record: Record<string, unknown>,
  keys: string[],
  fallback = '',
): string {
  for (const key of keys) {
    const value = stringValue(record[key]);
    if (value) return value;
  }
  return fallback;
}

function firstNumber(
  record: Record<string, unknown>,
  keys: string[],
  fallback = 0,
): number {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'number' && Number.isFinite(value)) return Math.max(0, value);
  }
  return Math.max(0, fallback);
}

function uniqueStrings(values: unknown[]): string[] {
  return [...new Set(values.map((value) => stringValue(value)).filter(Boolean))];
}

function dedupeApps(apps: TimelineApp[]): TimelineApp[] {
  const byId = new Map<string, TimelineApp>();
  for (const app of apps) {
    const current = byId.get(app.id);
    byId.set(app.id, current
      ? { ...current, eventCount: current.eventCount + app.eventCount }
      : app);
  }
  return [...byId.values()];
}

function deriveTaskTitle(summary: string, apps: TimelineApp[], index: number): string {
  const withoutAppPrefix = summary.replace(/^[^：:\n]{1,48}[：:]\s*/, '').trim();
  const firstClause = withoutAppPrefix.split(/[。；\n]/, 1)[0]?.trim() || '';
  if (firstClause) return firstClause.length > 42 ? `${firstClause.slice(0, 42)}...` : firstClause;
  if (apps.length > 1) return '跨应用协同任务';
  return apps[0]?.name ? `${apps[0].name} 中的任务` : `任务 ${index + 1}`;
}

function normalizePeriod(value: string, startMs: number, endMs: number): TimelinePeriod {
  const normalized = value.trim().toLowerCase();
  if (['day', 'all-day', 'allday', '全天', '整日'].includes(normalized)) return 'day';
  if (['morning', 'am', '上午', '早上', '清晨'].includes(normalized)) return 'morning';
  if (['afternoon', 'pm', '下午'].includes(normalized)) return 'afternoon';
  if (['evening', 'night', '晚上', '夜间'].includes(normalized)) return 'evening';
  if (!startMs) return 'day';
  const startPeriod = periodForHour(new Date(startMs).getHours());
  const boundedEndMs = Math.max(startMs, endMs || startMs);
  const endPeriod = periodForHour(new Date(boundedEndMs).getHours());
  return startPeriod === endPeriod ? startPeriod : 'day';
}

function normalizeActivityKind(value: string): TimelineActivityKind {
  if (value === 'ordinary_activity' || value === 'consolidated_activity') return value;
  return 'unclassified_activity';
}


function activityKindLabel(kind: TimelineActivityKind): string {
  return ({
    ordinary_activity: '普通活动',
    consolidated_activity: '长时聚合',
    unclassified_activity: '分类未标注',
  } as const)[kind];
}


function activityKindTone(kind: TimelineActivityKind): 'success' | 'info' | 'neutral' {
  if (kind === 'consolidated_activity') return 'success';
  if (kind === 'ordinary_activity') return 'info';
  return 'neutral';
}


function periodForHour(hour: number): Exclude<TimelinePeriod, 'day'> {
  if (hour < 12) return 'morning';
  if (hour < 18) return 'afternoon';
  return 'evening';
}

function periodLabel(period: TimelinePeriod): string {
  return ({ day: '全天', morning: '上午', afternoon: '下午', evening: '晚间' } as const)[period];
}

function periodDescription(period: TimelinePeriod): string {
  return ({
    day: '跨越多个时段的持续任务',
    morning: '当天开始到中午前的主要工作',
    afternoon: '中午后到傍晚的主要工作',
    evening: '傍晚后的主要工作',
  } as const)[period];
}

function sumTaskSpan(tasks: SemanticTimelineTask[]): number {
  return tasks.reduce((total, task) => total + Math.max(0, task.endMs - task.startMs), 0);
}

function sumEvidenceCount(tasks: SemanticTimelineTask[]): number {
  return tasks.reduce((total, task) => total + task.evidenceCount, 0);
}

function topJournalApps(tasks: SemanticTimelineTask[], limit: number): TimelineApp[] {
  const byId = new Map<string, TimelineApp>();
  for (const app of tasks.flatMap((task) => task.apps)) {
    const current = byId.get(app.id);
    byId.set(app.id, current
      ? { ...current, eventCount: current.eventCount + app.eventCount }
      : app);
  }
  return [...byId.values()]
    .sort((left, right) => right.eventCount - left.eventCount || left.name.localeCompare(right.name, 'zh-CN'))
    .slice(0, Math.max(0, limit));
}

function journalTaskCaption(task: SemanticTimelineTask): string {
  const appNames = task.apps.map((app) => app.name).filter(Boolean).slice(0, 3);
  const appLabel = appNames.join(' · ');
  return appLabel ? `${periodLabel(task.period)} · ${appLabel}` : periodLabel(task.period);
}

function localDate(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function normalizeCalendarDays(payload: Record<string, unknown>): ActivityCalendarDay[] {
  return arrayRecords(payload.days).map((value) => ({
    date: stringValue(value.date),
    status: stringValue(value.status, 'none'),
    organized: value.organized === true,
    modelOrganized: value.modelOrganized === true,
    needsRefresh: value.needsRefresh === true,
    sourceEventCount: numberValue(value.sourceEventCount),
    segmentCount: numberValue(value.segmentCount),
  })).filter((value) => /^\d{4}-\d{2}-\d{2}$/u.test(value.date));
}

type CalendarDayState = 'approved' | 'draft' | 'rejected' | 'waiting' | 'refresh' | 'empty';

function calendarDayState(day: ActivityCalendarDay | undefined): CalendarDayState {
  if (!day) return 'empty';
  if (day.needsRefresh) return 'refresh';
  if (day.organized && day.status === 'approved') return 'approved';
  if (day.organized && day.status === 'draft') return 'draft';
  if (day.status === 'rejected') return 'rejected';
  return day.sourceEventCount ? 'waiting' : 'empty';
}

function calendarStateLabel(state: CalendarDayState): string {
  return ({
    approved: '已整理',
    draft: '待发布',
    rejected: '已驳回',
    waiting: '待整理',
    refresh: '有新增',
    empty: '无活动',
  } as const)[state];
}

function calendarStateIcon(state: CalendarDayState) {
  if (state === 'approved') return <Check aria-hidden="true" size={12} />;
  if (state === 'draft') return <Clock3 aria-hidden="true" size={12} />;
  if (state === 'rejected') return <X aria-hidden="true" size={12} />;
  if (state === 'refresh') return <RefreshCw aria-hidden="true" size={12} />;
  if (state === 'waiting') return <Database aria-hidden="true" size={12} />;
  return null;
}

function calendarDayAriaLabel(dateValue: string, day: ActivityCalendarDay | undefined): string {
  const state = calendarDayState(day);
  const detail = day?.sourceEventCount
    ? `，${day.sourceEventCount} 条来源${day.modelOrganized && day.segmentCount ? `，${day.segmentCount} 项活动` : ''}`
    : '';
  return `${formatDateHeading(dateValue)}，${calendarStateLabel(state)}${detail}`;
}

function calendarCells(monthValue: string): Array<string | null> {
  const [year, month] = monthValue.split('-').map(Number);
  const firstWeekday = (new Date(year, month - 1, 1).getDay() + 6) % 7;
  const dayCount = new Date(year, month, 0).getDate();
  const cells: Array<string | null> = Array.from({ length: firstWeekday }, () => null);
  for (let day = 1; day <= dayCount; day += 1) {
    cells.push(`${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`);
  }
  while (cells.length % 7) cells.push(null);
  return cells;
}

function shiftDate(value: string, offset: number): string {
  const [year, month, day] = value.split('-').map(Number);
  const next = new Date(year, month - 1, day + offset);
  return `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}-${String(next.getDate()).padStart(2, '0')}`;
}

function shiftMonth(value: string, offset: number): string {
  const [year, month, day] = value.split('-').map(Number);
  const target = new Date(year, month - 1 + offset, 1);
  const maxDay = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate();
  return `${target.getFullYear()}-${String(target.getMonth() + 1).padStart(2, '0')}-${String(Math.min(day, maxDay)).padStart(2, '0')}`;
}

function monthRange(value: string, today: string): { start: string; end: string } {
  const month = value.slice(0, 7);
  const [year, monthNumber] = month.split('-').map(Number);
  const lastDay = new Date(year, monthNumber, 0).getDate();
  const monthEnd = `${month}-${String(lastDay).padStart(2, '0')}`;
  return {
    start: `${month}-01`,
    end: month === today.slice(0, 7) ? today : monthEnd,
  };
}

function formatMonthHeading(value: string): string {
  const [year, month] = value.split('-').map(Number);
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'long' }).format(new Date(year, month - 1, 1));
}

function catchUpProgressCopy(progress: Record<string, unknown>): string {
  const completed = numberValue(progress.completedDayCount);
  const total = numberValue(progress.totalDayCount);
  const currentDate = stringValue(progress.currentDate);
  const count = total ? `已完成 ${completed} / ${total} 天` : '正在计算待整理日期';
  return `正在整理历史日记：${count}${currentDate ? `，当前 ${currentDate}` : ''}。`;
}

function catchUpCompletedCopy(
  progress: Record<string, unknown>,
  result: Record<string, unknown>,
): string {
  const completed = numberValue(result.completedDayCount, numberValue(progress.completedDayCount));
  const total = numberValue(progress.totalDayCount, numberValue(result.batchDayCount, completed));
  const remaining = numberValue(result.remainingDayCount, numberValue(progress.remainingDayCount));
  return total
    ? `整理完成：已完成 ${completed} / ${total} 天，剩余 ${remaining} 天。`
    : '整理任务已完成，月历状态已刷新。';
}

function formatDateHeading(value: string): string {
  const [year, month, day] = value.split('-').map(Number);
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'long',
    day: 'numeric',
    weekday: 'long',
    ...(year !== new Date().getFullYear() ? { year: 'numeric' } : {}),
  }).format(new Date(year, month - 1, day));
}

function formatTimeRange(start: number, end: number): string {
  if (!start) return '时间未标注';
  const formatter = new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
  const startLabel = formatter.format(new Date(start));
  const endLabel = formatter.format(new Date(end || start));
  return startLabel === endLabel ? startLabel : `${startLabel}-${endLabel}`;
}

function formatDuration(value: number): string {
  const minutes = Math.max(0, Math.round(value / 60_000));
  if (!minutes) return '不足 1 分钟';
  if (minutes < 60) return `${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return remainder ? `${hours} 小时 ${remainder} 分钟` : `${hours} 小时`;
}

function formatTimestamp(value: number): string {
  if (!value) return '未知';
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value));
}

function shortHash(value: string): string {
  return value ? value.slice(0, 8) : '未生成';
}

function timelineStatusLabel(status: string): string {
  return ({ draft: '待发布', approved: '已发布', rejected: '已驳回', superseded: '已更新' } as Record<string, string>)[status] ?? '未知';
}

function timelineStatusTone(status: string): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'approved') return 'success';
  if (status === 'draft') return 'warning';
  if (status === 'rejected') return 'danger';
  return 'info';
}

function decisionCopy(status: string, approvedBookId: string): string {
  if (status === 'approved') return approvedBookId ? '已加入活动时间线' : '已整理到活动时间线';
  if (status === 'rejected') return '本次整理未进入长期上下文';
  if (status === 'superseded') return '来源已经变化，可重新生成草案';
  return '整理完成后会自动更新；仅在时间相关问题中按需使用';
}

function friendlyAppName(value: string): string {
  if (!value) return '';
  const lower = value.toLowerCase();
  if (lower.includes('codex')) return 'Codex';
  if (lower.includes('chatgpt') || lower === 'com.openai.chat') return 'ChatGPT';
  if (lower.includes('chrome')) return 'Chrome';
  if (lower.includes('edge')) return 'Edge';
  if (lower.includes('safari')) return 'Safari';
  if (lower.includes('terminal')) return 'Terminal';
  if (lower.includes('textedit')) return '文本编辑';
  if (lower.includes('ghostty')) return 'Ghostty';
  if (lower.includes('vscode') || lower.includes('visualstudio')) return 'VS Code';
  return value.split('.').at(-1) || value;
}

function appTone(value: string): string {
  const tones = ['teal', 'blue', 'green', 'amber', 'rose'];
  const score = [...value].reduce((sum, character) => sum + character.charCodeAt(0), 0);
  return tones[score % tones.length];
}

function sourceLabel(value: string): string {
  return ({
    squirrel_input_segment: '完整输入',
    squirrel_rime_commit: '输入法提交',
    browser_extension: '浏览器',
    pi_agent: '伙伴',
    terminal: '终端',
    reference: '相关来源',
  } as Record<string, string>)[value] ?? value.replaceAll('_', ' ');
}

function friendlyTimelineError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error || '');
  if (/stale|hash|source/i.test(message)) return '来源记录已变化，请刷新并重新整理。';
  if (/not found|does not exist/i.test(message)) return '没有找到这份时间线，请重新整理当天活动。';
  return '读取或保存失败，请稍后重试。';
}
