import {
  CalendarClock,
  Check,
  ChevronLeft,
  ChevronRight,
  FileClock,
  LockKeyhole,
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

export function ActivityTimeline() {
  const today = useMemo(localDate, []);
  const [date, setDate] = useState(today);
  const [approveOpen, setApproveOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
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
  const segments = arrayRecords(item.segments);
  const timelineId = stringValue(item.timelineId);
  const status = stringValue(item.status);
  const busy = build.isPending || approve.isPending || reject.isPending;
  const error = timeline.error ?? build.error ?? approve.error ?? reject.error;

  const moveDate = (offset: number) => {
    setDate(shiftDate(date, offset));
    setApproveOpen(false);
    setRejectOpen(false);
  };

  return (
    <section className="activity-timeline" aria-labelledby="activity-timeline-title">
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
            onChange={(event) => setDate(event.target.value || today)}
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
            onClick={() => setDate(today)}
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
          可以查看现有时间线，但当前服务不会接收整理、批准或驳回操作。
        </InlineNotice>
      ) : null}

      {capabilities.isPending || (canRead && timeline.isPending) ? (
        <div className="activity-timeline__loading" role="status">
          <RefreshCw aria-hidden="true" size={18} />
          <span>正在读取当天活动</span>
        </div>
      ) : !canRead || timeline.error ? null : timelineId ? (
        <>
          <div className="activity-timeline__summary-band">
            <div className="activity-timeline__summary-copy">
              <div>
                <StatusBadge label={timelineStatusLabel(status)} tone={timelineStatusTone(status)} />
                <span>{numberValue(item.segmentCount)} 个时段</span>
                <span>{numberValue(item.eventCount)} 条完整记录</span>
              </div>
              <p>{stringValue(item.summary, '当天活动已完成结构化整理。')}</p>
            </div>
            <dl className="activity-timeline__summary-metrics">
              <div><dt>时区</dt><dd>{stringValue(item.timezone, '本地')}</dd></div>
              <div><dt>来源版本</dt><dd>{shortHash(stringValue(item.sourceEventHash))}</dd></div>
              <div><dt>更新时间</dt><dd>{formatTimestamp(numberValue(item.updatedAtMs))}</dd></div>
            </dl>
          </div>

          <div className="activity-timeline__rail" aria-label={`${date} 活动时段`}>
            {segments.map((segment, index) => (
              <TimelineSegment key={stringValue(segment.segmentId, String(index))} segment={segment} />
            ))}
          </div>

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
                    批准整理
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

      <Dialog onOpenChange={setApproveOpen} open={approveOpen}>
        <DialogContent className="activity-timeline__dialog">
          <DialogHeader>
            <DialogTitle>批准 {formatDateHeading(date)} 的时间线</DialogTitle>
            <DialogDescription>
              当前来源哈希会在写入前再次校验；期间新增记录时，本次批准会被拒绝。
            </DialogDescription>
          </DialogHeader>
          <div className="activity-timeline__review-line">
            <Check aria-hidden="true" size={17} />
            <span>{numberValue(item.segmentCount)} 个时段将写入一条已批准的每日主题书。</span>
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
              批准并写入
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
            <DialogDescription>保留决定记录，但不会生成主题书。</DialogDescription>
          </DialogHeader>
          <Field htmlFor="timeline-reject-reason" label="原因">
            <Input
              id="timeline-reject-reason"
              maxLength={500}
              onChange={(event) => setRejectReason(event.target.value)}
              placeholder="例如：时段划分不准确"
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

function TimelineSegment({ segment }: { segment: Record<string, unknown> }) {
  const start = numberValue(segment.startMs);
  const end = numberValue(segment.endMs, start);
  const app = stringValue(segment.app, '未知应用');
  const sources = Array.isArray(segment.sourceKinds)
    ? segment.sourceKinds.map((value) => stringValue(value)).filter(Boolean)
    : [];
  const groups = Array.isArray(segment.contextGroupIds)
    ? segment.contextGroupIds.map((value) => stringValue(value)).filter(Boolean)
    : [];
  const redacted = numberValue(segment.redactedEventCount);
  return (
    <article className="activity-timeline__segment">
      <time dateTime={new Date(start).toISOString()}>{formatTimeRange(start, end)}</time>
      <span className="activity-timeline__node" aria-hidden="true"><i /></span>
      <div className="activity-timeline__segment-body">
        <header>
          <span className="activity-timeline__app-mark" data-app-tone={appTone(app)} />
          <strong>{friendlyAppName(app)}</strong>
          <span>{numberValue(segment.eventCount)} 条</span>
        </header>
        <p>{stringValue(segment.summary, '该时段没有可显示摘要。')}</p>
        <div className="activity-timeline__segment-meta">
          {sources.map((source) => <span key={source}>{sourceLabel(source)}</span>)}
          {groups.slice(0, 2).map((group) => <span key={group}>{compactGroup(group)}</span>)}
          {redacted ? <span data-tone="warning">{redacted} 条已脱敏</span> : null}
        </div>
      </div>
    </article>
  );
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
  const formatter = new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
  const startLabel = formatter.format(new Date(start));
  const endLabel = formatter.format(new Date(end));
  return startLabel === endLabel ? startLabel : `${startLabel}-${endLabel}`;
}

function formatTimestamp(value: number): string {
  if (!value) return '未知';
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value));
}

function shortHash(value: string): string {
  return value ? value.slice(0, 8) : '未生成';
}

function timelineStatusLabel(status: string): string {
  return ({ draft: '待审核', approved: '已批准', rejected: '已驳回', superseded: '已更新' } as Record<string, string>)[status] ?? '未知';
}

function timelineStatusTone(status: string): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'approved') return 'success';
  if (status === 'draft') return 'warning';
  if (status === 'rejected') return 'danger';
  return 'info';
}

function decisionCopy(status: string, approvedBookId: string): string {
  if (status === 'approved') return approvedBookId ? '已写入每日主题书' : '已批准';
  if (status === 'rejected') return '本次整理未进入长期上下文';
  if (status === 'superseded') return '来源已经变化，可重新生成草案';
  return '批准前只是一份派生草案，不参与事实召回';
}

function friendlyAppName(value: string): string {
  const lower = value.toLowerCase();
  if (lower.includes('codex')) return 'Codex';
  if (lower.includes('chatgpt') || lower === 'com.openai.chat') return 'ChatGPT';
  if (lower.includes('chrome')) return 'Chrome';
  if (lower.includes('edge')) return 'Edge';
  if (lower.includes('safari')) return 'Safari';
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
  } as Record<string, string>)[value] ?? value.replaceAll('_', ' ');
}

function compactGroup(value: string): string {
  const suffix = value.split(':').at(-1) || value;
  return suffix.length > 28 ? `${suffix.slice(0, 28)}...` : suffix;
}

function friendlyTimelineError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error || '');
  if (/stale|hash|source/i.test(message)) return '来源记录已变化，请刷新并重新整理。';
  if (/not found|does not exist/i.test(message)) return '没有找到这份时间线，请重新整理当天活动。';
  return '读取或保存失败，请稍后重试。';
}
