import {
  CalendarClock,
  CalendarDays,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Database,
  ExternalLink,
  FileClock,
  Fingerprint,
  ListTree,
  LockKeyhole,
  Monitor,
  RefreshCw,
  Sparkles,
  X,
} from 'lucide-react';
import { useMemo, useState } from 'react';
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
  evidenceCount: number;
  redactedEventCount: number;
  apps: TimelineApp[];
  sourceKinds: string[];
  contextGroupIds: string[];
  sourceEventIds: string[];
  sourceRefs: TimelineSourceRef[];
  events: TimelineEvidenceEvent[];
}

const PERIODS: TimelinePeriod[] = ['day', 'morning', 'afternoon', 'evening'];

export function ActivityTimeline() {
  const today = useMemo(localDate, []);
  const [date, setDate] = useState(today);
  const [approveOpen, setApproveOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const [selectedTaskId, setSelectedTaskId] = useState('');
  const [selectedReference, setSelectedReference] = useState<MemoryReferenceSelection | null>(null);
  const {
    approve,
    build,
    canRead,
    canWrite,
    capabilities,
    reject,
    timeline,
  } = useActivityTimeline(date, true);
  const payload = asRecord(timeline.data);
  const item = asRecord(payload.timeline);
  const tasks = useMemo(() => normalizeTimelineTasks(item), [item]);
  const taskGroups = useMemo(() => PERIODS.map((period) => ({
    period,
    tasks: tasks.filter((task) => task.period === period),
  })).filter((group) => group.tasks.length), [tasks]);
  const selectedTask = tasks.find((task) => task.id === selectedTaskId);
  const timelineId = stringValue(item.timelineId);
  const status = stringValue(item.status);
  const busy = build.isPending || approve.isPending || reject.isPending;
  const error = timeline.error ?? build.error ?? approve.error ?? reject.error;

  const chooseDate = (nextDate: string) => {
    setDate(nextDate);
    setApproveOpen(false);
    setRejectOpen(false);
    setSelectedTaskId('');
    setSelectedReference(null);
  };

  const moveDate = (offset: number) => chooseDate(shiftDate(date, offset));

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
      ) : !canRead || timeline.error ? null : timelineId ? (
        <>
          <div className="activity-timeline__summary-band activity-timeline__day-band">
            <div className="activity-timeline__summary-copy">
              <div>
                <StatusBadge label={timelineStatusLabel(status)} tone={timelineStatusTone(status)} />
                <span>{tasks.length} 个语义任务</span>
                <span>{numberValue(item.eventCount)} 条完整记录</span>
              </div>
              <p>{stringValue(item.summary, '当天活动已完成结构化整理。')}</p>
              <button
                className="activity-timeline__day-source"
                onClick={() => setSelectedReference({
                  kind: 'timeline',
                  referenceId: timelineId,
                  label: `${formatDateHeading(date)} 的活动时间线`,
                })}
                type="button"
              >
                <Fingerprint aria-hidden="true" size={13} />
                <span>查看当天整理来源</span>
                <ChevronRight aria-hidden="true" size={13} />
              </button>
            </div>
            <dl className="activity-timeline__summary-metrics">
              <div><dt>任务跨度合计</dt><dd>{formatDuration(sumTaskSpan(tasks))}</dd></div>
              <div><dt>参与 APP</dt><dd>{uniqueAppCount(tasks)}</dd></div>
              <div><dt>证据</dt><dd>{sumEvidenceCount(tasks)} 条</dd></div>
              <div><dt>时区</dt><dd>{stringValue(item.timezone, '本地')}</dd></div>
              <div><dt>来源版本</dt><dd>{shortHash(stringValue(item.sourceEventHash))}</dd></div>
              <div><dt>更新时间</dt><dd>{formatTimestamp(numberValue(item.updatedAtMs))}</dd></div>
            </dl>
          </div>

          {taskGroups.length ? (
            <div className="activity-timeline__periods" aria-label={`${date} 语义任务`}>
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
              <span>这份时间线还没有可显示的语义任务。</span>
            </div>
          )}

          <footer className="activity-timeline__decision-bar">
            <div>
              <LockKeyhole aria-hidden="true" size={16} />
              <span>{decisionCopy(status, stringValue(item.approvedBookId))}</span>
            </div>
            <div>
              {status === 'draft' ? (
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
                    onClick={() => setApproveOpen(true)}
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
                  onClick={() => build.mutate(date)}
                  size="small"
                >
                  重新整理
                </Button>
              )}
            </div>
          </footer>
        </>
      ) : (
        <div className="activity-timeline__empty">
          <EmptyState
            description="当天还没有整理产物。"
            icon={FileClock}
            title="尚未生成时间线"
          />
          <Button
            disabled={busy || !canWrite}
            leadingIcon={<Sparkles size={15} />}
            loading={build.isPending}
            onClick={() => build.mutate(date)}
            variant="primary"
          >
            整理当天活动
          </Button>
        </div>
      )}

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

      <Dialog onOpenChange={setApproveOpen} open={approveOpen}>
        <DialogContent className="activity-timeline__dialog">
          <DialogHeader>
            <DialogTitle>发布 {formatDateHeading(date)} 的时间线</DialogTitle>
            <DialogDescription>
              当前来源哈希会在发布前再次校验；期间新增记录时会先重新整理。
            </DialogDescription>
          </DialogHeader>
          <div className="activity-timeline__review-line">
            <Check aria-hidden="true" size={17} />
            <span>{tasks.length} 个语义任务将进入独立时间线索引，不会创建主题书。</span>
          </div>
          <DialogFooter>
            <Button onClick={() => setApproveOpen(false)} variant="quiet">取消</Button>
            <Button
              disabled={!canWrite}
              loading={approve.isPending}
              onClick={() => approve.mutate(
                { timelineId, sourceEventHash: stringValue(item.sourceEventHash) },
                { onSuccess: () => setApproveOpen(false) },
              )}
              variant="primary"
            >
              发布到时间线
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
        <span>{tasks.length} 项 · 任务跨度 {formatDuration(sumTaskSpan(tasks))}</span>
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
              <small>跨度 {formatDuration(task.endMs - task.startMs)}</small>
            </span>
            <span className="activity-timeline__task-main">
              <strong>{task.title}</strong>
              <span className="activity-timeline__task-summary">{task.summary}</span>
              <span className="activity-timeline__task-apps" aria-label="参与 APP">
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
              <span><Database aria-hidden="true" size={13} />{task.evidenceCount} 条证据</span>
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
  if (!task) return null;
  const visibleEvents = task.events.slice(0, 24);
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
            {periodLabel(task.period)} · {formatTimeRange(task.startMs, task.endMs)} · 时间跨度 {formatDuration(task.endMs - task.startMs)}
          </DialogDescription>
        </DialogHeader>

        <div className="activity-timeline__task-detail">
          <p className="activity-timeline__task-detail-summary">{task.summary}</p>
          <dl className="activity-timeline__task-detail-metrics">
            <div><dt>参与 APP</dt><dd>{task.apps.length}</dd></div>
            <div><dt>事件</dt><dd>{task.eventCount}</dd></div>
            <div><dt>证据</dt><dd>{task.evidenceCount}</dd></div>
            <div><dt>脱敏</dt><dd>{task.redactedEventCount}</dd></div>
          </dl>

          <section className="activity-timeline__detail-section">
            <h3><Monitor aria-hidden="true" size={15} />参与 APP</h3>
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
            <h3><Database aria-hidden="true" size={15} />证据链</h3>
            <p>先打开事件，再沿稳定引用查看保留的原始来源。</p>
            {taskLevelRefs.length ? (
              <SourceReferenceDetails
                onOpenReference={onOpenReference}
                refs={taskLevelRefs}
                title="任务级来源引用"
              />
            ) : null}
            <div className="activity-timeline__event-list">
              {visibleEvents.map((event, index) => (
                <details key={`${event.id}-${index}`} className="activity-timeline__event">
                  <summary>
                    <span>事件 {index + 1}</span>
                    <strong>{event.summary || `原始事件 #${event.id}`}</strong>
                    <ChevronDown aria-hidden="true" size={15} />
                  </summary>
                  <div className="activity-timeline__event-body">
                    <div className="activity-timeline__event-meta">
                      {event.timestampMs ? <time dateTime={new Date(event.timestampMs).toISOString()}>{formatTimestamp(event.timestampMs)}</time> : null}
                      {event.appName ? <span>{event.appName}</span> : null}
                      {event.sourceKind ? <span>{sourceLabel(event.sourceKind)}</span> : null}
                      {event.redacted ? <span data-tone="warning">内容已脱敏</span> : null}
                    </div>
                    {event.summary ? <p>{event.summary}</p> : (
                      <p>当前接口只提供事件身份，未返回可展示的事件摘要。</p>
                    )}
                    {event.referenceId ? (
                      <button
                        className="activity-timeline__open-event"
                        onClick={() => onOpenReference({
                          kind: 'event',
                          referenceId: event.referenceId,
                          label: event.summary || `原始事件 #${event.id}`,
                        })}
                        type="button"
                      >
                        <ExternalLink aria-hidden="true" size={13} />
                        <span>打开原始事件</span>
                        <ChevronRight aria-hidden="true" size={13} />
                      </button>
                    ) : null}
                    {event.sourceRefs.length ? (
                      <SourceReferenceDetails
                        onOpenReference={onOpenReference}
                        refs={event.sourceRefs}
                        title={`来源引用 · ${event.sourceRefs.length}`}
                      />
                    ) : (
                      <p className="activity-timeline__source-unavailable">
                        当前接口未返回这条事件的来源引用。
                      </p>
                    )}
                  </div>
                </details>
              ))}
            </div>
            {!visibleEvents.length ? (
              <div className="activity-timeline__evidence-empty">没有可展开的事件证据。</div>
            ) : null}
            {task.events.length > visibleEvents.length ? (
              <p className="activity-timeline__evidence-limit">
                已显示前 {visibleEvents.length} 条，另有 {task.events.length - visibleEvents.length} 条保留在来源账本中。
              </p>
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
    <details className="activity-timeline__source-refs">
      <summary>
        <span>{title}</span>
        <ChevronDown aria-hidden="true" size={14} />
      </summary>
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
    </details>
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
  return apps[0]?.name ? `${apps[0].name} 中的任务` : `语义任务 ${index + 1}`;
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

function uniqueAppCount(tasks: SemanticTimelineTask[]): number {
  return new Set(tasks.flatMap((task) => task.apps.map((app) => app.id))).size;
}

function localDate(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function shiftDate(value: string, offset: number): string {
  const [year, month, day] = value.split('-').map(Number);
  const next = new Date(year, month - 1, day + offset);
  return `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}-${String(next.getDate()).padStart(2, '0')}`;
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
  return ({ draft: '待自动发布', approved: '已发布', rejected: '已删除', superseded: '已更新' } as Record<string, string>)[status] ?? '未知';
}

function timelineStatusTone(status: string): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'approved') return 'success';
  if (status === 'draft') return 'warning';
  if (status === 'rejected') return 'danger';
  return 'info';
}

function decisionCopy(status: string, approvedBookId: string): string {
  if (status === 'approved') return approvedBookId ? '已迁移到独立时间线索引' : '已进入独立时间线索引';
  if (status === 'rejected') return '本次整理未进入长期上下文';
  if (status === 'superseded') return '来源已经变化，可重新生成草案';
  return '后台会自动发布；仅在时间类问题中按需召回';
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
    pi_agent: 'Agent',
    terminal: '终端',
    reference: '来源引用',
  } as Record<string, string>)[value] ?? value.replaceAll('_', ' ');
}

function friendlyTimelineError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error || '');
  if (/stale|hash|source/i.test(message)) return '来源记录已变化，请刷新并重新整理。';
  if (/not found|does not exist/i.test(message)) return '没有找到这份时间线，请重新整理当天活动。';
  return '读取或保存失败，请稍后重试。';
}
