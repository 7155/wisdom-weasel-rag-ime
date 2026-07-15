import { useMutation } from '@tanstack/react-query';
import { Check, CircleDashed, RotateCcw, ShieldCheck } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Button } from '@/components/primitives';
import {
  InlineNotice,
  StatusBadge,
  asRecord,
  booleanValue,
  numberValue,
  publicErrorText,
  stringValue,
} from './management-ui';

export type MutationAvailability = {
  state: 'checking' | 'available' | 'blocked' | 'unsupported';
  reason?: string;
};

export type ManagementWorkPreview<Context> = {
  context: Context;
  expectedRuntimeRevision: number;
  expiresAtMs: number;
  pathId: string;
  payloadSha256: string;
  previewToken: string;
  requiredConfirm: string;
  summary: {
    title: string;
    items: readonly string[];
    risk: 'R1' | 'R2' | 'R3';
  };
};

export type ManagementWorkReceipt = {
  appliedAtMs: number;
  pathId: string;
  payloadSha256: string;
  receiptId: string;
  rollbackAvailable: boolean;
  rollbackToken: string;
  raw: Record<string, unknown>;
};

export function ManagementMutationWorkflow<Context>({
  availability,
  description,
  draftKey,
  mutationKey,
  onApply,
  onApplied,
  onPreview,
  onRollback,
  onRolledBack,
  risk,
  title,
}: {
  availability: MutationAvailability;
  description: string;
  draftKey: string;
  mutationKey: readonly unknown[];
  onApply: (preview: ManagementWorkPreview<Context>) => Promise<ManagementWorkReceipt>;
  onApplied?: (receipt: ManagementWorkReceipt) => void;
  onPreview: () => Promise<ManagementWorkPreview<Context>>;
  onRollback?: (
    receipt: ManagementWorkReceipt,
    preview: ManagementWorkPreview<Context>,
  ) => Promise<ManagementWorkReceipt>;
  onRolledBack?: (receipt: ManagementWorkReceipt) => void;
  risk: 'R1' | 'R2' | 'R3';
  title: string;
}) {
  const [stage, setStage] = useState<'idle' | 'preview' | 'approval' | 'receipt' | 'rolled-back'>('idle');
  const [approved, setApproved] = useState(false);
  const [preview, setPreview] = useState<ManagementWorkPreview<Context> | null>(null);
  const [receipt, setReceipt] = useState<ManagementWorkReceipt | null>(null);
  const [rollbackReceipt, setRollbackReceipt] = useState<ManagementWorkReceipt | null>(null);

  const previewMutation = useMutation({
    mutationKey: [...mutationKey, 'preview'],
    mutationFn: onPreview,
    onSuccess: (nextPreview) => {
      setPreview(nextPreview);
      setApproved(false);
      setStage('preview');
    },
  });
  const applyMutation = useMutation({
    mutationKey: [...mutationKey, 'apply'],
    mutationFn: async (boundPreview: ManagementWorkPreview<Context>) => onApply(boundPreview),
    onSuccess: (nextReceipt) => {
      setReceipt(nextReceipt);
      setStage('receipt');
      onApplied?.(nextReceipt);
    },
  });
  const rollbackMutation = useMutation({
    mutationKey: [...mutationKey, 'rollback'],
    mutationFn: async ({ applied, boundPreview }: {
      applied: ManagementWorkReceipt;
      boundPreview: ManagementWorkPreview<Context>;
    }) => {
      if (!onRollback) throw new Error('这次操作当前不能撤销。');
      return onRollback(applied, boundPreview);
    },
    onSuccess: (nextReceipt) => {
      setRollbackReceipt(nextReceipt);
      setStage('rolled-back');
      onRolledBack?.(nextReceipt);
    },
  });

  useEffect(() => {
    if (stage !== 'preview' && stage !== 'approval') return;
    setPreview(null);
    setApproved(false);
    setStage('idle');
  // draftKey intentionally invalidates a server preview when editable input changes.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftKey]);

  const steps = useMemo(() => [
    { id: 'preview', label: '预览' },
    { id: 'approval', label: '确认' },
    { id: 'receipt', label: '完成' },
    { id: 'rolled-back', label: '撤销' },
  ] as const, []);
  const stageIndex = stage === 'idle' ? -1 : steps.findIndex((step) => step.id === stage);
  const actionable = availability.state === 'available';
  const previewExpired = Boolean(preview && preview.expiresAtMs <= Date.now());

  return (
    <div className="mgmt-workflow" data-availability={availability.state} data-stage={stage}>
      <div className="mgmt-workflow__heading">
        <div>
          <span className="mgmt-workflow__risk">{riskLabel(risk)}</span>
          <strong>{title}</strong>
          <p>{description}</p>
        </div>
        {stage === 'idle' ? (
          <Button
            disabled={!actionable}
            leadingIcon={<ShieldCheck size={15} />}
            loading={previewMutation.isPending || availability.state === 'checking'}
            onClick={() => previewMutation.mutate()}
            size="small"
          >
            {availability.state === 'unsupported' ? '当前不可用' : availability.state === 'blocked' ? '尚不可预览' : '预览操作'}
          </Button>
        ) : null}
      </div>

      {availability.state !== 'available' && availability.state !== 'checking' && availability.reason ? (
        <InlineNotice title={availability.state === 'unsupported' ? '暂不可用' : '等待必要信息'} tone="warning">
          {availability.reason}
        </InlineNotice>
      ) : null}

      {previewMutation.error ? (
        <InlineNotice title="预览失败" tone="danger">{publicErrorText(previewMutation.error)}</InlineNotice>
      ) : null}

      {stage !== 'idle' ? (
        <ol className="mgmt-workflow__steps" aria-label="操作进度">
          {steps.map((step, index) => (
            <li data-state={index < stageIndex ? 'complete' : index === stageIndex ? 'current' : 'pending'} key={step.id}>
              {index < stageIndex ? <Check size={13} /> : index === stageIndex ? <CircleDashed size={13} /> : <i />}
              {step.label}
            </li>
          ))}
        </ol>
      ) : null}

      {stage === 'preview' && preview ? (
        <div className="mgmt-workflow__panel">
          <strong>{preview.summary.title}</strong>
          <ul>{preview.summary.items.map((line) => <li key={line}>{line}</li>)}</ul>
          <div className="mgmt-workflow__binding">
            <span>预览已校验</span>
            <span>{previewExpired ? '预览已过期' : `有效至 ${formatTimestamp(preview.expiresAtMs)}`}</span>
          </div>
          {previewExpired ? <InlineNotice title="需要重新预览" tone="warning">这份预览已过期，不会进入确认。</InlineNotice> : null}
          <div className="mgmt-workflow__buttons">
            <Button onClick={() => reset()} size="small" variant="quiet">取消</Button>
            <Button disabled={previewExpired} onClick={() => setStage('approval')} size="small" variant="primary">进入确认</Button>
          </div>
        </div>
      ) : null}

      {stage === 'approval' && preview ? (
        <div className="mgmt-workflow__panel">
          <strong>确认已核对操作预览</strong>
          <label className="mgmt-workflow__confirm">
            <input checked={approved} onChange={(event) => setApproved(event.target.checked)} type="checkbox" />
            <span>只执行上方已绑定的变更</span>
          </label>
          <div className="mgmt-workflow__buttons">
            <Button onClick={() => setStage('preview')} size="small" variant="quiet">返回预览</Button>
            <Button
              disabled={!approved}
              loading={applyMutation.isPending}
              onClick={() => applyMutation.mutate(preview)}
              size="small"
              variant={preview.summary.risk === 'R3' ? 'danger' : 'primary'}
            >
              确认并应用
            </Button>
          </div>
        </div>
      ) : null}

      {applyMutation.error ? (
        <div className="mgmt-workflow__panel">
          <InlineNotice title="应用失败" tone="danger">{publicErrorText(applyMutation.error)}</InlineNotice>
          <div className="mgmt-workflow__buttons">
            <Button onClick={() => reset()} size="small" variant="quiet">重新预览</Button>
          </div>
        </div>
      ) : null}

      {stage === 'receipt' && receipt && preview ? (
        <WorkReceipt receipt={receipt} rolledBack={false}>
          {receipt.rollbackAvailable && onRollback ? (
            <Button
              leadingIcon={<RotateCcw size={14} />}
              loading={rollbackMutation.isPending}
              onClick={() => rollbackMutation.mutate({ applied: receipt, boundPreview: preview })}
              size="small"
            >
              撤销这次操作
            </Button>
          ) : (
            <Button onClick={() => reset()} size="small" variant="quiet">完成</Button>
          )}
        </WorkReceipt>
      ) : null}

      {rollbackMutation.error ? (
        <InlineNotice title="撤销失败" tone="danger">{publicErrorText(rollbackMutation.error)}</InlineNotice>
      ) : null}

      {stage === 'rolled-back' && rollbackReceipt ? (
        <WorkReceipt receipt={rollbackReceipt} rolledBack>
          <Button onClick={() => reset()} size="small" variant="quiet">完成</Button>
        </WorkReceipt>
      ) : null}
    </div>
  );

  function reset() {
    setStage('idle');
    setApproved(false);
    setPreview(null);
    setReceipt(null);
    setRollbackReceipt(null);
    previewMutation.reset();
    applyMutation.reset();
    rollbackMutation.reset();
  }
}

export function UnsupportedWorkflow({
  description,
  reason,
  risk,
  title,
}: {
  description: string;
  reason: string;
  risk: 'R1' | 'R2' | 'R3';
  title: string;
}) {
  return (
    <div className="mgmt-workflow" data-availability="unsupported" data-stage="idle">
      <div className="mgmt-workflow__heading">
        <div>
          <span className="mgmt-workflow__risk">{riskLabel(risk)}</span>
          <strong>{title}</strong>
          <p>{description}</p>
        </div>
        <Button disabled size="small">当前不可用</Button>
      </div>
      <InlineNotice title="暂不可用" tone="warning">{reason}</InlineNotice>
    </div>
  );
}

export function parseManagementWorkPreview<Context>(
  value: unknown,
  expectedPathId: string,
  context: Context,
): ManagementWorkPreview<Context> {
  const payload = asRecord(value);
  const summary = asRecord(payload.summary);
  const expectedRevision = asRecord(payload.expectedRevision);
  const previewToken = stringValue(payload.previewToken);
  const payloadSha256 = stringValue(payload.payloadSha256);
  const pathId = stringValue(payload.pathId);
  const requiredConfirm = stringValue(payload.requiredConfirm);
  const expiresAtMs = numberValue(payload.expiresAtMs);
  const expectedRuntimeRevision = numberValue(expectedRevision.runtimeRevision);
  const items = Array.isArray(summary.items)
    ? summary.items.filter((item): item is string => typeof item === 'string' && item.length > 0)
    : [];
  const risk = stringValue(summary.risk);
  if (payload.ok !== true) throw new Error(stringValue(payload.message, stringValue(payload.error, '服务端拒绝生成预览。')));
  if (!previewToken || !payloadSha256 || pathId !== expectedPathId || requiredConfirm !== 'apply' || !expiresAtMs) {
    throw new Error('这份操作预览暂时无法确认，请刷新后重试。');
  }
  if (!Number.isInteger(expectedRuntimeRevision) || expectedRuntimeRevision < 0) {
    throw new Error('这份操作预览已经失效，请刷新后重试。');
  }
  if (!stringValue(summary.title) || items.length === 0 || !['R1', 'R2', 'R3'].includes(risk)) {
    throw new Error('这份操作预览没有可核对的影响，请重试。');
  }
  return {
    context,
    expectedRuntimeRevision,
    expiresAtMs,
    pathId,
    payloadSha256,
    previewToken,
    requiredConfirm,
    summary: {
      title: publicWorkflowText(stringValue(summary.title), '确认本次变更'),
      items: publicWorkflowItems(items),
      risk: risk as 'R1' | 'R2' | 'R3',
    },
  };
}

const internalWorkflowText = /(?:pathId|operation(?:Id)?|receipt(?:Id)?|rollbackToken|payloadSha|runtimeRevision|previewToken|expectedRevision|schema|policy(?:Id)?|profile(?:Id|Version)?|\bID\b|sha256:|https?:\/\/|\/api\/)/i;

function publicWorkflowText(value: string, fallback: string): string {
  const text = value.trim();
  if (!text || text.length > 220 || internalWorkflowText.test(text)) return fallback;
  return text;
}

function publicWorkflowItems(items: readonly string[]): string[] {
  const visible = items
    .map((item) => publicWorkflowText(item, ''))
    .filter(Boolean);
  return visible.length ? visible : ['只会应用你在页面中确认的内容。'];
}

export function parseManagementWorkReceipt(
  value: unknown,
  expectedPathId: string,
  expectedPayloadSha256: string,
): ManagementWorkReceipt {
  const payload = asRecord(value);
  const receiptId = stringValue(payload.receiptId);
  const pathId = stringValue(payload.pathId);
  const payloadSha256 = stringValue(payload.payloadSha256);
  const rollbackAvailable = booleanValue(payload.rollbackAvailable);
  const rollbackToken = stringValue(payload.rollbackToken);
  const appliedAtMs = numberValue(payload.appliedAtMs);
  if (payload.ok !== true) throw new Error(stringValue(payload.message, stringValue(payload.error, '服务拒绝了这次操作。')));
  if (!receiptId || pathId !== expectedPathId || payloadSha256 !== expectedPayloadSha256 || !appliedAtMs) {
    throw new Error('这次操作结果暂时无法确认，请刷新后重试。');
  }
  if (rollbackAvailable && !rollbackToken) throw new Error('这次操作暂时无法安全撤销，请刷新后重试。');
  return {
    appliedAtMs,
    pathId,
    payloadSha256,
    receiptId,
    rollbackAvailable,
    rollbackToken,
    raw: payload,
  };
}

function WorkReceipt({
  children,
  receipt,
  rolledBack,
}: {
  children: React.ReactNode;
  receipt: ManagementWorkReceipt;
  rolledBack: boolean;
}) {
  return (
    <div className="mgmt-workflow__receipt">
      <div>
        <StatusBadge label={rolledBack ? '已撤销' : '已应用'} tone={rolledBack ? 'info' : 'success'} />
        <strong>{rolledBack ? '已恢复到操作前' : '本机操作已记录'}</strong>
        <span>{rolledBack ? '原操作不再生效' : receipt.rollbackAvailable ? '可以撤销' : '此操作不可撤销'}</span>
        <time>{formatTimestamp(receipt.appliedAtMs)}</time>
      </div>
      {children}
    </div>
  );
}

function formatTimestamp(value: number): string {
  return new Date(value).toLocaleString('zh-CN', { hour12: false });
}

function riskLabel(value: 'R1' | 'R2' | 'R3'): string {
  return ({ R1: '需确认', R2: '较高风险', R3: '高风险' } as const)[value];
}
