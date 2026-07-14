import { useMutation } from '@tanstack/react-query';
import {
  AlertTriangle,
  Check,
  ChevronRight,
  CircleDashed,
  RotateCcw,
  ShieldCheck,
  type LucideIcon,
} from 'lucide-react';
import {
  useId,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { useControlTransport } from '@/app/control-transport';
import { Button, EmptyState, Skeleton } from '@/components/primitives';
import './management.css';

export type JsonRecord = Record<string, unknown>;

export type ActionReceipt = {
  receiptId: string;
  status: 'applied' | 'mocked' | 'rolled-back';
  message: string;
  at: string;
  rollbackAvailable: boolean;
};

export function ManagementPage({
  actions,
  children,
  description,
  eyebrow,
  routeId,
  title,
}: {
  actions?: ReactNode;
  children: ReactNode;
  description: string;
  eyebrow?: string;
  routeId: string;
  title: string;
}) {
  return (
    <main className="mgmt-page" data-route-id={routeId}>
      <header className="mgmt-page__header">
        <div className="mgmt-page__heading">
          {eyebrow ? <span className="mgmt-page__eyebrow">{eyebrow}</span> : null}
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
        {actions ? <div className="mgmt-page__actions">{actions}</div> : null}
      </header>
      <div className="mgmt-page__body">{children}</div>
    </main>
  );
}

export function ManagementSection({
  children,
  description,
  title,
  trailing,
}: {
  children: ReactNode;
  description?: string;
  title: string;
  trailing?: ReactNode;
}) {
  return (
    <section className="mgmt-section">
      <div className="mgmt-section__header">
        <div>
          <h2>{title}</h2>
          {description ? <p>{description}</p> : null}
        </div>
        {trailing ? <div className="mgmt-section__trailing">{trailing}</div> : null}
      </div>
      {children}
    </section>
  );
}

export function QueryState({
  children,
  empty,
  error,
  isEmpty = false,
  isPending,
  onRetry,
}: {
  children: ReactNode;
  empty?: ReactNode;
  error: Error | null;
  isEmpty?: boolean;
  isPending: boolean;
  onRetry: () => void;
}) {
  if (isPending) {
    return (
      <div className="mgmt-loading" role="status" aria-label="正在加载">
        <Skeleton />
        <Skeleton />
        <Skeleton />
      </div>
    );
  }
  if (error) {
    return (
      <EmptyState
        action={<Button onClick={onRetry}>重试</Button>}
        description={error.message}
        icon={AlertTriangle}
        title="读取失败"
      />
    );
  }
  if (isEmpty && empty) return <>{empty}</>;
  return <>{children}</>;
}

export function StatusBadge({
  label,
  tone = 'neutral',
}: {
  label: ReactNode;
  tone?: 'success' | 'warning' | 'danger' | 'info' | 'neutral';
}) {
  return (
    <span className="mgmt-status" data-tone={tone}>
      <i aria-hidden="true" />
      {label}
    </span>
  );
}

export function MetricStrip({
  items,
}: {
  items: readonly {
    label: string;
    value: ReactNode;
    detail?: ReactNode;
    icon?: LucideIcon;
    tone?: 'success' | 'warning' | 'danger' | 'info' | 'neutral';
  }[];
}) {
  return (
    <dl className="mgmt-metrics">
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <div className="mgmt-metric" key={item.label} data-tone={item.tone ?? 'neutral'}>
            <dt>
              {Icon ? <Icon size={15} aria-hidden="true" /> : null}
              {item.label}
            </dt>
            <dd>{item.value}</dd>
            {item.detail ? <dd className="mgmt-metric__detail">{item.detail}</dd> : null}
          </div>
        );
      })}
    </dl>
  );
}

export function OperationalList({
  items,
}: {
  items: readonly {
    id: string;
    title: ReactNode;
    detail?: ReactNode;
    meta?: ReactNode;
    status?: ReactNode;
    onClick?: () => void;
    selected?: boolean;
  }[];
}) {
  return (
    <div className="mgmt-list">
      {items.map((item) => {
        const content = (
          <>
            <div className="mgmt-list__copy">
              <strong>{item.title}</strong>
              {item.detail ? <span>{item.detail}</span> : null}
            </div>
            {item.meta ? <span className="mgmt-list__meta">{item.meta}</span> : null}
            {item.status ? <span className="mgmt-list__status">{item.status}</span> : null}
            {item.onClick ? <ChevronRight size={15} aria-hidden="true" /> : null}
          </>
        );
        return item.onClick ? (
          <button
            className="mgmt-list__row mgmt-list__row--button"
            data-selected={item.selected || undefined}
            key={item.id}
            onClick={item.onClick}
            type="button"
          >
            {content}
          </button>
        ) : (
          <div className="mgmt-list__row" key={item.id}>
            {content}
          </div>
        );
      })}
    </div>
  );
}

export function DataTable({
  caption,
  columns,
  rows,
}: {
  caption: string;
  columns: readonly { key: string; label: string; width?: string }[];
  rows: readonly JsonRecord[];
}) {
  return (
    <div className="mgmt-table-wrap" tabIndex={0}>
      <table className="mgmt-table">
        <caption>{caption}</caption>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} style={column.width ? { width: column.width } : undefined} scope="col">
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={stringValue(row.id) || `row-${index}`}>
              {columns.map((column) => (
                <td key={column.key}>{displayValue(row[column.key])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PaginationBar({
  count,
  hasMore,
  isFetching,
  onLoadMore,
}: {
  count: number;
  hasMore: boolean;
  isFetching: boolean;
  onLoadMore: () => void;
}) {
  return (
    <div className="mgmt-pagination">
      <span>已加载 {count} 条</span>
      <Button disabled={!hasMore} loading={isFetching} onClick={onLoadMore} size="small">
        {hasMore ? '加载下一页' : '已到末页'}
      </Button>
    </div>
  );
}

export function InlineNotice({
  children,
  title,
  tone = 'info',
}: {
  children: ReactNode;
  title: string;
  tone?: 'info' | 'warning' | 'danger' | 'success';
}) {
  return (
    <div className="mgmt-notice" data-tone={tone} role={tone === 'danger' ? 'alert' : 'status'}>
      <strong>{title}</strong>
      <span>{children}</span>
    </div>
  );
}

export function WorkflowAction({
  actionId,
  applyLabel = '批准并应用',
  description,
  mutationKey,
  onApply,
  onRollback,
  preview,
  risk = 'R1',
  title,
}: {
  actionId: string;
  applyLabel?: string;
  description: string;
  mutationKey: readonly unknown[];
  onApply?: () => Promise<ActionReceipt>;
  onRollback?: (receipt: ActionReceipt) => Promise<ActionReceipt>;
  preview: readonly string[];
  risk?: 'R0' | 'R1' | 'R2' | 'R3';
  title: string;
}) {
  const transport = useControlTransport();
  const isRehearsal = !onApply && transport.kind === 'mock';
  const unavailable = !onApply && !isRehearsal;
  const instanceId = useId();
  const [stage, setStage] = useState<'idle' | 'preview' | 'approval' | 'receipt' | 'rolled-back'>('idle');
  const [receipt, setReceipt] = useState<ActionReceipt | null>(null);
  const [rollbackReceipt, setRollbackReceipt] = useState<ActionReceipt | null>(null);

  const applyMutation = useMutation({
    mutationKey: [...mutationKey, 'apply'],
    mutationFn: async () => {
      if (onApply) return onApply();
      if (isRehearsal) return mockReceipt(actionId, 'applied');
      throw new Error('真实写入合同尚未接入。');
    },
    onSuccess: (nextReceipt) => {
      setReceipt(nextReceipt);
      setStage('receipt');
    },
  });
  const rollbackMutation = useMutation({
    mutationKey: [...mutationKey, 'rollback'],
    mutationFn: async (appliedReceipt: ActionReceipt) => {
      if (onRollback) return onRollback(appliedReceipt);
      if (isRehearsal) return mockReceipt(actionId, 'rolled-back');
      throw new Error('真实回滚合同尚未接入。');
    },
    onSuccess: (nextReceipt) => {
      setRollbackReceipt(nextReceipt);
      setStage('rolled-back');
    },
  });

  const steps = useMemo(
    () => [
      { id: 'preview', label: '预览' },
      { id: 'approval', label: '审批' },
      { id: 'receipt', label: '收据' },
      { id: 'rolled-back', label: '回滚' },
    ] as const,
    [],
  );
  const stageIndex = stage === 'idle' ? -1 : steps.findIndex((step) => step.id === stage);

  return (
    <div className="mgmt-workflow" data-stage={stage} data-unavailable={unavailable || undefined}>
      <div className="mgmt-workflow__heading">
        <div>
          <span className="mgmt-workflow__risk">{risk}</span>
          <strong>{title}</strong>
          <p>{description}</p>
        </div>
        {stage === 'idle' ? (
          <Button disabled={unavailable} leadingIcon={<ShieldCheck size={15} />} onClick={() => setStage('preview')} size="small">
            {unavailable ? '真实写入尚未接入' : isRehearsal ? '演练流程' : '预览操作'}
          </Button>
        ) : null}
      </div>

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

      {stage === 'preview' ? (
        <div className="mgmt-workflow__panel" id={`${instanceId}-preview`}>
          <strong>{isRehearsal ? '演练预览' : '影响预览'}</strong>
          <ul>{preview.map((line) => <li key={line}>{line}</li>)}</ul>
          <div className="mgmt-workflow__buttons">
            <Button onClick={() => setStage('idle')} size="small" variant="quiet">取消</Button>
            <Button onClick={() => setStage('approval')} size="small" variant="primary">
              {isRehearsal ? '进入演练确认' : '进入审批'}
            </Button>
          </div>
        </div>
      ) : null}

      {stage === 'approval' ? (
        <div className="mgmt-workflow__panel">
          <strong>{isRehearsal ? '演练确认' : '审批确认'}</strong>
          <p>{isRehearsal ? '本次仅演练确认、收据与回滚流程，不会修改本机状态。' : '确认后将只执行上方列出的影响。'}</p>
          <div className="mgmt-workflow__buttons">
            <Button onClick={() => setStage('preview')} size="small" variant="quiet">返回预览</Button>
            <Button
              loading={applyMutation.isPending}
              onClick={() => applyMutation.mutate()}
              size="small"
              variant={risk === 'R3' ? 'danger' : 'primary'}
            >
              {isRehearsal ? '生成演练收据' : applyLabel}
            </Button>
          </div>
        </div>
      ) : null}

      {applyMutation.error ? (
        <InlineNotice title="应用失败" tone="danger">{asError(applyMutation.error).message}</InlineNotice>
      ) : null}

      {stage === 'receipt' && receipt ? (
        <ReceiptView receipt={receipt}>
          <Button
            disabled={!receipt.rollbackAvailable || (!onRollback && !isRehearsal)}
            leadingIcon={<RotateCcw size={14} />}
            loading={rollbackMutation.isPending}
            onClick={() => rollbackMutation.mutate(receipt)}
            size="small"
          >
            {receipt.status === 'mocked' ? '回滚演练' : '回滚'}
          </Button>
        </ReceiptView>
      ) : null}

      {rollbackMutation.error ? (
        <InlineNotice title="回滚失败" tone="danger">{asError(rollbackMutation.error).message}</InlineNotice>
      ) : null}

      {stage === 'rolled-back' && rollbackReceipt ? (
        <ReceiptView receipt={rollbackReceipt}>
          <Button onClick={() => {
            setReceipt(null);
            setRollbackReceipt(null);
            setStage('idle');
          }} size="small" variant="quiet">
            完成
          </Button>
        </ReceiptView>
      ) : null}
    </div>
  );
}

function ReceiptView({ children, receipt }: { children: ReactNode; receipt: ActionReceipt }) {
  return (
    <div className="mgmt-workflow__receipt">
      <div>
        <StatusBadge
          label={receipt.status === 'mocked' ? '演练 / 未执行' : receipt.status === 'rolled-back' ? '已回滚' : '已应用'}
          tone={receipt.status === 'rolled-back' ? 'info' : 'success'}
        />
        <strong>{receipt.receiptId}</strong>
        <span>{receipt.message}</span>
        <time>{receipt.at}</time>
      </div>
      {children}
    </div>
  );
}

function mockReceipt(actionId: string, status: 'applied' | 'rolled-back'): Promise<ActionReceipt> {
  const now = new Date();
  return Promise.resolve({
    receiptId: `rehearsal:${actionId}:${now.getTime()}`,
    status: status === 'rolled-back' ? 'rolled-back' : 'mocked',
    message: status === 'rolled-back'
      ? '演练状态已回滚；未修改本机状态。'
      : '演练已完成；未执行操作，也未修改本机状态。',
    at: now.toLocaleString('zh-CN'),
    rollbackAvailable: status !== 'rolled-back',
  });
}

export function asRecord(value: unknown): JsonRecord {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as JsonRecord : {};
}

export function arrayRecords(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.map(asRecord).filter((item) => Object.keys(item).length > 0) : [];
}

export function stringValue(value: unknown, fallback = ''): string {
  return typeof value === 'string'
    ? value
    : typeof value === 'number' || typeof value === 'boolean'
      ? String(value)
      : fallback;
}

export function numberValue(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

export function booleanValue(value: unknown, fallback = false): boolean {
  return typeof value === 'boolean' ? value : fallback;
}

export function valueAt(value: unknown, path: string): unknown {
  let cursor: unknown = value;
  for (const part of path.split('.')) cursor = asRecord(cursor)[part];
  return cursor;
}

export function formatTime(value: unknown): string {
  const timestamp = numberValue(value);
  if (!timestamp) return '暂无';
  return new Date(timestamp).toLocaleString('zh-CN', { hour12: false });
}

export function configuredLabel(value: unknown): string {
  if (typeof value === 'boolean') return value ? 'configured' : 'not configured';
  if (typeof value === 'string') return value.trim() ? 'configured' : 'not configured';
  return value === null || value === undefined ? 'not configured' : 'configured';
}

function displayValue(value: unknown): ReactNode {
  if (value === null || value === undefined || value === '') return <span className="mgmt-muted">-</span>;
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'number') return value.toLocaleString('zh-CN');
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map((item) => stringValue(item)).filter(Boolean).join(' · ');
  return <span className="mgmt-muted">结构化数据</span>;
}

function asError(value: unknown): Error {
  return value instanceof Error ? value : new Error(String(value));
}
