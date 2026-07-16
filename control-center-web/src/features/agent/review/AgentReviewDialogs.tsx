import { Check, CircleDashed, FileCheck2, ShieldAlert } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useControlTransport } from '@/app/control-transport';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/primitives';
import type { AgentActivityProjection } from '@/contracts/agent-reducer';
import { publicAgentErrorText } from '../public-error';

type MemoryChange = {
  diffId: number;
  operationLabel: string;
  status: string;
  selected: boolean;
  title: string;
  detail: string;
  sourceCount: number;
};

type MemoryRun = {
  runId: string;
  status: string;
  summary: string;
  diffCount: number;
  pendingDiffCount: number;
  changes: MemoryChange[];
};

type ApplyPreview = {
  previewToken: string;
  payloadSha256: string;
  expectedRuntimeRevision: number;
  items: string[];
};

type ApprovalPreviewChange = {
  label: string;
  before: string;
  after: string;
};

export function MemoryReviewDialog({
  activity,
  sessionId,
  onError,
}: {
  activity?: AgentActivityProjection;
  sessionId: string;
  onError: (message: string) => void;
}) {
  const transport = useControlTransport();
  const runId = text(activity?.payload.runId);
  const [run, setRun] = useState<MemoryRun>();
  const [preview, setPreview] = useState<ApplyPreview>();
  const [confirmed, setConfirmed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [pendingDiffId, setPendingDiffId] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [resolved, setResolved] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    setRun(undefined);
    setPreview(undefined);
    setConfirmed(false);
    setResolved(false);
    setError('');
    if (!runId) return;
    let active = true;
    setLoading(true);
    void transport.request({
      pathId: 'agent.memoryMaintenance.run',
      query: { runId },
    }).then((value) => {
      if (active) setRun(parseMemoryRun(value));
    }).catch((reason: unknown) => {
      if (active) setError(publicAgentErrorText(reason, '记忆草案暂时无法读取。'));
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [runId, transport]);

  const selectedCount = useMemo(
    () => run?.changes.filter((change) => change.selected).length ?? 0,
    [run],
  );

  async function resolve(decision: 'reviewed' | 'deferred'): Promise<void> {
    if (!runId) return;
    setSubmitting(true);
    setError('');
    try {
      await transport.request({
        pathId: 'agent.session.review.resolve',
        params: { sessionId },
        body: { runId, decision },
      });
      setResolved(true);
    } catch (reason) {
      const message = publicAgentErrorText(reason, '无法恢复当前 Agent 回合。');
      setError(message);
      onError(message);
      setSubmitting(false);
    }
  }

  async function updateChange(change: MemoryChange, selected: boolean): Promise<void> {
    if (!runId || pendingDiffId) return;
    setPendingDiffId(change.diffId);
    setError('');
    setRun((current) => current ? {
      ...current,
      changes: current.changes.map((item) => item.diffId === change.diffId ? { ...item, selected } : item),
    } : current);
    try {
      await transport.request({
        pathId: 'knowledge.database.draft.edit',
        body: { runId, diffId: change.diffId, selected },
      });
      const refreshed = await transport.request({
        pathId: 'agent.memoryMaintenance.run',
        query: { runId },
      });
      setRun(parseMemoryRun(refreshed));
      setPreview(undefined);
      setConfirmed(false);
    } catch (reason) {
      const message = publicAgentErrorText(reason, '这条记忆变更没有保存。');
      setError(message);
      onError(message);
      setRun((current) => current ? {
        ...current,
        changes: current.changes.map((item) => item.diffId === change.diffId ? { ...item, selected: change.selected } : item),
      } : current);
    } finally {
      setPendingDiffId(0);
    }
  }

  async function previewApply(): Promise<void> {
    if (!runId || submitting || selectedCount === 0) return;
    setSubmitting(true);
    setError('');
    try {
      const value = await transport.request({
        pathId: 'knowledge.database.apply.preview',
        body: { runId },
      });
      setPreview(parseApplyPreview(value));
      setConfirmed(false);
    } catch (reason) {
      setError(publicAgentErrorText(reason, '无法生成安全应用预览。'));
    } finally {
      setSubmitting(false);
    }
  }

  async function apply(): Promise<void> {
    if (!runId || !preview || !confirmed || submitting) return;
    setSubmitting(true);
    setError('');
    try {
      const value = await transport.request<Record<string, unknown>>({
        pathId: 'knowledge.database.apply',
        body: {
          runId,
          confirm: 'apply',
          previewToken: preview.previewToken,
          payloadSha256: preview.payloadSha256,
          expectedRuntimeRevision: preview.expectedRuntimeRevision,
        },
      });
      if (value.ok !== true) throw new Error(text(value.error) || '应用失败');
      await resolve('reviewed');
    } catch (reason) {
      const message = publicAgentErrorText(reason, '记忆草案没有应用。');
      setError(message);
      onError(message);
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={Boolean(activity && runId && !resolved)}>
      <DialogContent
        className="agent-review-dialog"
        hideClose
        onEscapeKeyDown={(event) => event.preventDefault()}
        onInteractOutside={(event) => event.preventDefault()}
      >
        <DialogHeader>
          <span className="agent-review-dialog__eyebrow"><FileCheck2 size={15} />需要你的审阅</span>
          <DialogTitle>记忆整理草案</DialogTitle>
          <DialogDescription>Agent 已暂停。逐项选择要保留的变更，完成或暂缓后会自动继续并结束本轮。</DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="agent-review-dialog__loading" role="status"><CircleDashed size={18} />正在读取草案</div>
        ) : null}

        {run && !preview ? (
          <>
            <div className="agent-review-dialog__summary">
              <span><strong>{run.summary || '增量记忆整理'}</strong><small>{run.diffCount} 项变更，已选择 {selectedCount} 项</small></span>
              <i>{run.status === 'draft' ? '草案' : run.status}</i>
            </div>
            <div className="agent-review-list" role="list" aria-label="记忆变更">
              {run.changes.map((change) => (
                <label className="agent-review-item" data-selected={change.selected} key={change.diffId}>
                  <input
                    checked={change.selected}
                    disabled={Boolean(pendingDiffId) || submitting}
                    onChange={(event) => void updateChange(change, event.target.checked)}
                    type="checkbox"
                  />
                  <span>
                    <strong>{change.title || change.operationLabel}</strong>
                    <small>{change.operationLabel}{change.detail ? ` · ${change.detail}` : ''}</small>
                    {change.sourceCount ? <em>{change.sourceCount} 条来源</em> : null}
                  </span>
                  {pendingDiffId === change.diffId ? <CircleDashed className="agent-review-item__spinner" size={15} /> : change.selected ? <Check size={15} /> : null}
                </label>
              ))}
            </div>
          </>
        ) : null}

        {preview ? (
          <div className="agent-review-confirm">
            <span><ShieldAlert size={17} /><strong>最后确认</strong></span>
            <ul>{preview.items.map((item) => <li key={item}>{item}</li>)}</ul>
            <label><input checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} type="checkbox" />只应用上面已选择并已绑定的变更</label>
          </div>
        ) : null}

        {error ? <p className="agent-review-dialog__error" role="alert">{error}</p> : null}

        <footer className="agent-review-dialog__actions">
          {preview ? (
            <>
              <Button disabled={submitting} onClick={() => { setPreview(undefined); setConfirmed(false); }} variant="quiet">返回修改</Button>
              <Button disabled={!confirmed || submitting} loading={submitting} onClick={() => void apply()} variant="primary">确认应用并继续</Button>
            </>
          ) : (
            <>
              <Button disabled={submitting} onClick={() => void resolve('deferred')} variant="quiet">稍后审阅</Button>
              <Button disabled={!run || submitting} onClick={() => void resolve('reviewed')}>保留草案并继续</Button>
              <Button disabled={!run || selectedCount === 0 || submitting || Boolean(pendingDiffId)} loading={submitting} onClick={() => void previewApply()} variant="primary">预览应用所选</Button>
            </>
          )}
        </footer>
      </DialogContent>
    </Dialog>
  );
}

export function ApprovalReviewDialog({
  activity,
  onDecision,
}: {
  activity?: AgentActivityProjection;
  onDecision: (approvalId: string, decision: 'approved' | 'rejected', hash: string) => Promise<void>;
}) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const approvalId = text(activity?.payload.approvalId);
  const hash = text(activity?.payload.payloadSha256);
  useEffect(() => {
    setSubmitting(false);
    setError('');
  }, [activity?.id]);
  if (!activity || !approvalId || !hash) return null;
  const preview = parseApprovalPreview(activity.payload.preview);
  const title = preview.summary || text(activity.payload.summary) || text(activity.payload.operation) || '执行受控操作';
  const risk = text(activity.payload.riskLevel) || '需确认';
  return (
    <Dialog open>
      <DialogContent
        className="agent-approval-dialog"
        hideClose
        onEscapeKeyDown={(event) => event.preventDefault()}
        onInteractOutside={(event) => event.preventDefault()}
      >
        <DialogHeader>
          <span className="agent-review-dialog__eyebrow"><ShieldAlert size={15} />{risk}</span>
          <DialogTitle>{preview.title || '确认 Agent 操作'}</DialogTitle>
          <DialogDescription>Agent 已暂停，必须由你明确批准或拒绝后才会继续。</DialogDescription>
        </DialogHeader>
        <div className="agent-approval-dialog__summary"><strong>{title}</strong><small>只会执行这份已绑定的操作预览。</small></div>
        {preview.changes.length ? (
          <dl className="agent-approval-dialog__changes" aria-label="操作预览">
            {preview.changes.map((change, index) => (
              <div key={`${change.label}:${index}`}>
                <dt>{change.label}</dt>
                {change.before ? <dd><span>原值</span><code>{change.before}</code></dd> : null}
                <dd><span>{change.before ? '新值' : '内容'}</span><code>{change.after || '无'}</code></dd>
              </div>
            ))}
          </dl>
        ) : null}
        {error ? <p className="agent-review-dialog__error" role="alert">{error}</p> : null}
        <footer className="agent-review-dialog__actions">
          <Button disabled={submitting} onClick={() => void decide('rejected')} variant="quiet">拒绝并继续</Button>
          <Button disabled={submitting} loading={submitting} onClick={() => void decide('approved')} variant="primary">批准并执行</Button>
        </footer>
      </DialogContent>
    </Dialog>
  );

  async function decide(decision: 'approved' | 'rejected'): Promise<void> {
    setSubmitting(true);
    setError('');
    try {
      await onDecision(approvalId, decision, hash);
    } catch (reason) {
      setError(publicAgentErrorText(reason, '审批提交失败，请检查状态后重试。'));
    } finally {
      setSubmitting(false);
    }
  }
}

function parseApprovalPreview(value: unknown): { title: string; summary: string; changes: ApprovalPreviewChange[] } {
  const preview = record(value);
  const source = Array.isArray(preview.changes) ? preview.changes : [];
  const changes = source.flatMap((item): ApprovalPreviewChange[] => {
    const change = record(item);
    const label = previewText(change.label, 120);
    const before = previewText(change.before, 2_000);
    const after = previewText(change.after, 4_000);
    return label && (before || after) ? [{ label, before, after }] : [];
  }).slice(0, 20);
  return {
    title: previewText(preview.title, 160),
    summary: previewText(preview.summary, 500),
    changes,
  };
}

function previewText(value: unknown, maximum: number): string {
  if (typeof value !== 'string' && typeof value !== 'number' && typeof value !== 'boolean') return '';
  const normalized = String(value).replace(/\r\n?/g, '\n').trim();
  return normalized.length > maximum ? `${normalized.slice(0, maximum)}…` : normalized;
}

function parseMemoryRun(value: unknown): MemoryRun {
  const payload = record(value);
  if (payload.ok !== true) throw new Error(text(payload.error) || '记忆草案不可用');
  const run = record(payload.run);
  const changes = Array.isArray(run.changes) ? run.changes.map((item) => {
    const change = record(item);
    return {
      diffId: integer(change.diffId),
      operationLabel: text(change.operationLabel) || '记忆变更',
      status: text(change.status),
      selected: change.selected !== false,
      title: text(change.title),
      detail: text(change.detail),
      sourceCount: integer(change.sourceCount),
    };
  }).filter((change) => change.diffId > 0) : [];
  return {
    runId: text(run.runId),
    status: text(run.status),
    summary: text(run.summary),
    diffCount: integer(run.diffCount) || changes.length,
    pendingDiffCount: integer(run.pendingDiffCount),
    changes,
  };
}

function parseApplyPreview(value: unknown): ApplyPreview {
  const payload = record(value);
  if (payload.ok !== true) throw new Error(text(payload.error) || '应用预览不可用');
  const summary = record(payload.summary);
  const expectedRevision = record(payload.expectedRevision);
  const items = Array.isArray(summary.items) ? summary.items.filter((item): item is string => typeof item === 'string') : [];
  const preview = {
    previewToken: text(payload.previewToken),
    payloadSha256: text(payload.payloadSha256),
    expectedRuntimeRevision: integer(expectedRevision.runtimeRevision),
    items: items.length ? items : ['应用当前选择的记忆变更。'],
  };
  if (!preview.previewToken || !preview.payloadSha256) throw new Error('应用预览缺少安全绑定');
  return preview;
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function text(value: unknown): string { return typeof value === 'string' ? value.trim() : ''; }
function integer(value: unknown): number { return typeof value === 'number' && Number.isInteger(value) ? value : 0; }
