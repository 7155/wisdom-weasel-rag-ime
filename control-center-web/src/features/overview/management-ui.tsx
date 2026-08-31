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
import { usePawOsAppCompact, usePawOsAppIdentity } from '@/features/paw-os/surface-context';
import { TraceAgentHandoffButton } from '@/features/trace-agent/handoff';
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
  layout = 'sheet',
  routeId,
  title,
}: {
  actions?: ReactNode;
  children: ReactNode;
  description: string;
  eyebrow?: string;
  layout?: 'sheet' | 'workbench';
  routeId: string;
  title: string;
}) {
  const appSurface = usePawOsAppIdentity();
  const compact = usePawOsAppCompact();
  const Surface = appSurface ? 'section' : 'main';
  return (
    <Surface
      aria-label={appSurface ? title : undefined}
      className="mgmt-page"
      data-layout={layout}
      data-paw-os-app={appSurface?.appId}
      data-paw-os-compact={compact || undefined}
      data-route-id={routeId}
      role={appSurface ? 'region' : undefined}
    >
      {appSurface ? (
        <>
          <h1 className="mgmt-sr-only">{title}</h1>
          {actions ? <div aria-label={`${title}页面操作`} className="mgmt-page__native-actions" role="toolbar">{actions}</div> : null}
        </>
      ) : (
        <header className="mgmt-page__header">
          <div className="mgmt-page__heading">
            {eyebrow ? <span className="mgmt-page__eyebrow">{eyebrow}</span> : null}
            <h1>{title}</h1>
            <p>{description}</p>
          </div>
          {actions ? <div className="mgmt-page__actions">{actions}</div> : null}
        </header>
      )}
      <div className="mgmt-page__body">{children}</div>
    </Surface>
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
  errorAction,
  headingLevel = 2,
  isEmpty = false,
  isPending,
  onRetry,
}: {
  children: ReactNode;
  empty?: ReactNode;
  error: Error | null;
  errorAction?: ReactNode;
  headingLevel?: 2 | 3 | 4;
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
      <div aria-atomic="true" role="alert">
        <EmptyState
          action={(
            <div className="mgmt-query-actions">
              <Button onClick={onRetry}>重试</Button>
              {errorAction}
              <TraceAgentHandoffButton
                handoff={{
                  kind: 'generic',
                  title: '读取失败',
                  summary: publicErrorText(error, '暂时无法读取这部分内容，请稍后重试。'),
                  error: error.message,
                }}
              />
            </div>
          )}
          description={publicErrorText(error, '暂时无法读取这部分内容，请稍后重试。')}
          headingLevel={headingLevel}
          icon={AlertTriangle}
          title="读取失败"
        />
      </div>
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
  className,
  items,
}: {
  className?: string;
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
    <div className={['mgmt-list', className].filter(Boolean).join(' ')}>
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
  const captionId = useId();
  return (
    <div aria-labelledby={captionId} className="mgmt-table-wrap" role="region" tabIndex={0}>
      <table className="mgmt-table">
        <caption id={captionId}>{caption}</caption>
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
      <div className="mgmt-notice__body">{children}</div>
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
      throw new Error('当前版本暂不支持这项操作。');
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
      throw new Error('当前版本暂不支持撤销这项操作。');
    },
    onSuccess: (nextReceipt) => {
      setRollbackReceipt(nextReceipt);
      setStage('rolled-back');
    },
  });

  const steps = useMemo(
    () => [
      { id: 'preview', label: '预览' },
      { id: 'approval', label: '确认' },
      { id: 'receipt', label: '结果' },
      { id: 'rolled-back', label: '撤销' },
    ] as const,
    [],
  );
  const stageIndex = stage === 'idle' ? -1 : steps.findIndex((step) => step.id === stage);

  return (
    <div className="mgmt-workflow" data-stage={stage} data-unavailable={unavailable || undefined}>
      <div className="mgmt-workflow__heading">
        <div>
          <span className="mgmt-workflow__risk">{workflowRiskLabel(risk)}</span>
          <strong>{title}</strong>
          <p>{description}</p>
        </div>
        {stage === 'idle' && !unavailable ? (
          <Button leadingIcon={<ShieldCheck size={15} />} onClick={() => setStage('preview')} size="small">
            {isRehearsal ? '查看示例' : '预览操作'}
          </Button>
        ) : null}
      </div>

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

      {stage === 'preview' ? (
        <div className="mgmt-workflow__panel" id={`${instanceId}-preview`}>
          <strong>{isRehearsal ? '示例预览' : '影响预览'}</strong>
          <ul>{preview.map((line) => <li key={line}>{line}</li>)}</ul>
          <div className="mgmt-workflow__buttons">
            <Button onClick={() => setStage('idle')} size="small" variant="quiet">取消</Button>
            <Button onClick={() => setStage('approval')} size="small" variant="primary">
              {isRehearsal ? '确认示例' : '继续确认'}
            </Button>
          </div>
        </div>
      ) : null}

      {stage === 'approval' ? (
        <div className="mgmt-workflow__panel">
          <strong>{isRehearsal ? '示例确认' : '操作确认'}</strong>
          <p>{isRehearsal ? '这是界面示例，不会修改本机状态。' : '确认后将只执行上方列出的影响。'}</p>
          <div className="mgmt-workflow__buttons">
            <Button onClick={() => setStage('preview')} size="small" variant="quiet">返回预览</Button>
            <Button
              loading={applyMutation.isPending}
              onClick={() => applyMutation.mutate()}
              size="small"
              variant={risk === 'R3' ? 'danger' : 'primary'}
            >
              {isRehearsal ? '查看示例结果' : applyLabel}
            </Button>
          </div>
        </div>
      ) : null}

      {applyMutation.error ? (
        <InlineNotice title="应用失败" tone="danger">{publicErrorText(applyMutation.error)}</InlineNotice>
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
            {receipt.status === 'mocked' ? '撤销示例' : '撤销'}
          </Button>
        </ReceiptView>
      ) : null}

      {rollbackMutation.error ? (
        <InlineNotice title="撤销失败" tone="danger">{publicErrorText(rollbackMutation.error)}</InlineNotice>
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
          label={receipt.status === 'mocked' ? '示例 / 未执行' : receipt.status === 'rolled-back' ? '已撤销' : '已完成'}
          tone={receipt.status === 'rolled-back' ? 'info' : 'success'}
        />
        <strong>{receipt.status === 'mocked' ? '示例结果' : receipt.status === 'rolled-back' ? '已恢复到操作前' : '本机操作已记录'}</strong>
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
      ? '示例已恢复；未修改本机状态。'
      : '示例已完成；未执行操作，也未修改本机状态。',
    at: now.toLocaleString('zh-CN'),
    rollbackAvailable: status !== 'rolled-back',
  });
}

function workflowRiskLabel(value: 'R0' | 'R1' | 'R2' | 'R3'): string {
  return ({
    R0: '无需确认',
    R1: '确认后执行',
    R2: '谨慎确认',
    R3: '高风险',
  } as const)[value];
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
  if (typeof value === 'boolean') return value ? '已配置' : '未配置';
  if (typeof value === 'string') return value.trim() ? '已配置' : '未配置';
  return value === null || value === undefined ? '未配置' : '已配置';
}

function displayValue(value: unknown): ReactNode {
  if (value === null || value === undefined || value === '') return <span className="mgmt-muted">-</span>;
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'number') return value.toLocaleString('zh-CN');
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map((item) => stringValue(item)).filter(Boolean).join(' · ');
  return <span className="mgmt-muted">结构化数据</span>;
}

export function publicErrorText(
  value: unknown,
  fallback = '操作未完成，请刷新状态后重试。',
): string {
  const message = (value instanceof Error ? value.message : String(value ?? '')).trim();
  if (!message || message.length > 180 || !/[\u3400-\u9fff]/u.test(message)) return fallback;
  if (/运行版本.*(?:变化|失效)|内容版本.*(?:变化|失效)/u.test(message)) return '页面内容已经变化，请重新预览。';
  if (/pathId|operation(?:Id)?|receipt|rollbackToken|payloadSha|runtimeRevision|previewToken|work.?contract|schema|policy(?:Id)?|profile(?:Id|Version)?|运行版本|traceback|stack|sqlite|\b(?:GET|POST|PUT|PATCH|DELETE)\b|https?:\/\/|\/api\/|\bat\s+\S+[:(]\d+/i.test(message)) {
    return fallback;
  }
  return message;
}
