import { useMutation } from '@tanstack/react-query';
import { Check, CircleDashed, RotateCcw, ShieldCheck } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Button } from '@/components/primitives';
import { InlineNotice, StatusBadge, asRecord, booleanValue, numberValue, stringValue } from './management-ui';

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
      if (!onRollback) throw new Error('此收据没有可用的回滚边界。');
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
    { id: 'receipt', label: '收据' },
    { id: 'rolled-back', label: '回滚' },
  ] as const, []);
  const stageIndex = stage === 'idle' ? -1 : steps.findIndex((step) => step.id === stage);
  const actionable = availability.state === 'available';
  const previewExpired = Boolean(preview && preview.expiresAtMs <= Date.now());

  return (
    <div className="mgmt-workflow" data-availability={availability.state} data-stage={stage}>
      <div className="mgmt-workflow__heading">
        <div>
          <span className="mgmt-workflow__risk">{risk}</span>
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
            {availability.state === 'unsupported' ? '后端暂不支持' : availability.state === 'blocked' ? '尚不可预览' : '预览操作'}
          </Button>
        ) : null}
      </div>

      {availability.state !== 'available' && availability.state !== 'checking' && availability.reason ? (
        <InlineNotice title={availability.state === 'unsupported' ? '能力未开放' : '等待必要信息'} tone="warning">
          {availability.reason}
        </InlineNotice>
      ) : null}

      {previewMutation.error ? (
        <InlineNotice title="预览失败" tone="danger">{asError(previewMutation.error).message}</InlineNotice>
      ) : null}

      {stage !== 'idle' ? (
        <ol className="mgmt-workflow__steps" aria-label="写操作进度">
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
            <span>绑定 {shortHash(preview.payloadSha256)}</span>
            <span>{previewExpired ? '预览已过期' : `有效至 ${formatTimestamp(preview.expiresAtMs)}`}</span>
          </div>
          {previewExpired ? <InlineNotice title="需要重新预览" tone="warning">这份绑定已过期，不会进入确认。</InlineNotice> : null}
          <div className="mgmt-workflow__buttons">
            <Button onClick={() => reset()} size="small" variant="quiet">取消</Button>
            <Button disabled={previewExpired} onClick={() => setStage('approval')} size="small" variant="primary">进入确认</Button>
          </div>
        </div>
      ) : null}

      {stage === 'approval' && preview ? (
        <div className="mgmt-workflow__panel">
          <strong>确认已核对服务端预览</strong>
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
        <InlineNotice title="应用失败" tone="danger">{asError(applyMutation.error).message}</InlineNotice>
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
              回滚
            </Button>
          ) : (
            <Button onClick={() => reset()} size="small" variant="quiet">完成</Button>
          )}
        </WorkReceipt>
      ) : null}

      {rollbackMutation.error ? (
        <InlineNotice title="回滚失败" tone="danger">{asError(rollbackMutation.error).message}</InlineNotice>
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
          <span className="mgmt-workflow__risk">{risk}</span>
          <strong>{title}</strong>
          <p>{description}</p>
        </div>
        <Button disabled size="small">后端暂不支持</Button>
      </div>
      <InlineNotice title="能力未开放" tone="warning">{reason}</InlineNotice>
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
    throw new Error('服务端返回了不完整的写操作预览。');
  }
  if (!Number.isInteger(expectedRuntimeRevision) || expectedRuntimeRevision < 0) {
    throw new Error('服务端预览缺少绑定的运行版本。');
  }
  if (!stringValue(summary.title) || items.length === 0 || !['R1', 'R2', 'R3'].includes(risk)) {
    throw new Error('服务端预览缺少可核对的影响摘要。');
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
      title: stringValue(summary.title),
      items,
      risk: risk as 'R1' | 'R2' | 'R3',
    },
  };
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
  if (payload.ok !== true) throw new Error(stringValue(payload.message, stringValue(payload.error, '服务端拒绝写操作。')));
  if (!receiptId || pathId !== expectedPathId || payloadSha256 !== expectedPayloadSha256 || !appliedAtMs) {
    throw new Error('服务端返回了无法验证的写操作收据。');
  }
  if (rollbackAvailable && !rollbackToken) throw new Error('可回滚收据缺少 rollbackToken。');
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
        <StatusBadge label={rolledBack ? '已回滚' : '已应用'} tone={rolledBack ? 'info' : 'success'} />
        <strong>{receipt.receiptId}</strong>
        <span>{receipt.pathId} · {shortHash(receipt.payloadSha256)}</span>
        <time>{formatTimestamp(receipt.appliedAtMs)}</time>
      </div>
      {children}
    </div>
  );
}

function shortHash(value: string): string {
  const normalized = value.startsWith('sha256:') ? value.slice(7) : value;
  return `sha256:${normalized.slice(0, 10)}`;
}

function formatTimestamp(value: number): string {
  return new Date(value).toLocaleString('zh-CN', { hour12: false });
}

function asError(value: unknown): Error {
  return value instanceof Error ? value : new Error(String(value));
}
