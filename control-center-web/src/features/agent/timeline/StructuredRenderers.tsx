import { useState } from 'react';
import {
  Activity,
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  ListChecks,
  ShieldAlert,
  Table2,
  TriangleAlert,
  Wrench,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { Button } from '@/components/primitives';
import type { UiAgentBlock } from '@/contracts/ui-events';
import { publicAgentErrorText } from '../public-error';
import { useProductIdentity } from '@/features/identity/product-identity';
import { MarkdownBody } from './MarkdownRenderer';
import { publicToolLabel } from './public-tool-result';
import type { AgentBlockRenderProps } from './renderer-contract';
import {
  displayScalar,
  publicStructuredValue,
  record,
  safeLabelValuePairs,
  text,
} from './renderer-values';

export function CardBlockRenderer({ block }: AgentBlockRenderProps) {
  const data = block.data;
  const title = text(data.title) || '信息卡片';
  const tone = ['info', 'success', 'warning', 'danger'].includes(text(data.tone))
    ? text(data.tone)
    : 'info';
  const fields = safeLabelValuePairs(data.fields);
  return (
    <section className="agent-rich-card" data-tone={tone} aria-label={title}>
      <header>
        <span className="agent-insert-icon">{statusIcon(tone)}</span>
        <strong>{title}</strong>
      </header>
      {text(data.bodyMarkdown) ? <MarkdownBody text={text(data.bodyMarkdown)} /> : null}
      {fields.length ? (
        <dl>
          {fields.map((field, index) => (
            <div key={`${field.label}:${index}`}>
              <dt>{field.label}</dt><dd>{field.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </section>
  );
}

export function ChecklistBlockRenderer({ block }: AgentBlockRenderProps) {
  const data = block.data;
  const items = (Array.isArray(data.items) ? data.items : [])
    .map((item, index) => {
      const value = record(item);
      return {
        id: text(value.id) || String(index),
        label: text(value.text ?? value.label) || `项目 ${index + 1}`,
        checked: value.checked === true
          || ['done', 'completed', 'passed'].includes(text(value.status)),
      };
    })
    .slice(0, 100);
  const title = text(data.title) || '检查清单';
  const completed = items.filter((item) => item.checked).length;
  const tone = items.length > 0 && completed === items.length ? 'success' : 'warning';
  return (
    <details
      className="agent-rich-checklist agent-rich-collapsible"
      data-tone={tone}
      open={items.length <= 8}
    >
      <summary>
        <span className="agent-insert-icon"><ListChecks size={16} /></span>
        <span>{title}</span>
        <small>{completed}/{items.length}</small>
        <ChevronRight className="agent-rich-collapsible__chevron" size={14} />
      </summary>
      {items.length ? (
        <ul>
          {items.map((item) => (
            <li key={item.id} data-checked={item.checked}>
              <span aria-hidden="true">
                {item.checked
                  ? <CheckCircle2 size={16} />
                  : <span className="agent-rich-checklist__empty" />}
              </span>
              <span>{item.label}</span>
            </li>
          ))}
        </ul>
      ) : <p>暂无清单项。</p>}
    </details>
  );
}

export function TableBlockRenderer({ block }: AgentBlockRenderProps) {
  const data = block.data;
  const columns = (Array.isArray(data.columns) ? data.columns : [])
    .map((column, index) => {
      const value = record(column);
      return {
        key: text(value.key) || text(column) || String(index),
        label: text(value.label ?? value.title) || text(column) || `列 ${index + 1}`,
      };
    })
    .slice(0, 12);
  const rows = (Array.isArray(data.rows) ? data.rows : []).slice(0, 100);
  const title = text(data.title ?? data.caption) || '数据表';
  return (
    <details
      className="agent-rich-table agent-rich-collapsible"
      data-tone="info"
      open={rows.length <= 8}
    >
      <summary>
        <span className="agent-insert-icon"><Table2 size={16} /></span>
        <span>{title}</span>
        <small>{rows.length} 行</small>
        <ChevronRight className="agent-rich-collapsible__chevron" size={14} />
      </summary>
      {columns.length ? (
        <div>
          <table>
            <thead><tr>{columns.map((column) => <th scope="col" key={column.key}>{column.label}</th>)}</tr></thead>
            <tbody>
              {rows.map((row, rowIndex) => {
                const rowRecord = record(row);
                const rowArray = Array.isArray(row) ? row : [];
                return (
                  <tr key={rowIndex}>
                    {columns.map((column, columnIndex) => (
                      <TableCell
                        key={column.key}
                        value={rowArray[columnIndex] ?? rowRecord[column.key]}
                      />
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : <p>表格缺少可展示的列。</p>}
    </details>
  );
}

export function StatusBlockRenderer({ block }: AgentBlockRenderProps) {
  const data = block.data;
  const state = text(data.state ?? data.status) || 'recorded';
  const tone = ['failed', 'blocked', 'danger'].includes(state)
    ? 'danger'
    : ['waiting', 'pending', 'paused'].includes(state)
      ? 'warning'
      : ['done', 'completed', 'success'].includes(state) ? 'success' : 'info';
  const title = text(data.title) || '状态更新';
  const fields = safeLabelValuePairs(data.fields);
  return (
    <section className="agent-rich-status" data-state={state} data-tone={tone} aria-label={title}>
      <span className="agent-insert-icon">{statusIcon(tone)}</span>
      <span>
        <strong>{title}</strong>
        <small>{text(data.detail ?? data.summary ?? data.label) || publicStructuredValue(state)}</small>
      </span>
      {fields.length ? (
        <dl>
          {fields.map((field, index) => (
            <div key={`${field.label}:${index}`}><dt>{field.label}</dt><dd>{field.value}</dd></div>
          ))}
        </dl>
      ) : null}
    </section>
  );
}

export function TaskPlanBlockRenderer({ block }: AgentBlockRenderProps) {
  const data = block.data;
  const items = Array.isArray(data.items)
    ? data.items
    : Array.isArray(data.tasks) ? data.tasks : [];
  const completed = items.filter((item) => {
    const state = text(record(item).status);
    return ['done', 'completed', 'passed', 'success'].includes(state);
  }).length;
  return (
    <section className="agent-task-plan" data-tone="project">
      <header>
        <span className="agent-insert-icon"><ListChecks size={16} /></span>
        <strong>{text(data.title) || '任务计划'}</strong>
        {items.length ? <small>{completed}/{items.length}</small> : null}
      </header>
      <ol>
        {items.map((item, index) => {
          const value = record(item);
          const label = text(value.title ?? value.label ?? item);
          return (
            <li key={`${label}-${index}`} data-status={text(value.status)}>
              {label || `步骤 ${index + 1}`}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export function ApprovalBlockRenderer({
  block,
  onApprovalDecision,
}: AgentBlockRenderProps) {
  const data = block.data;
  const approvalId = text(data.approvalId ?? data.id);
  const hash = text(data.payloadSha256);
  const state = text(data.state);
  const pending = !['approved', 'rejected', 'applied'].includes(state);
  /* One decision per approval: the projection may take a moment to echo the
     new state back, and a second click in that window would submit twice.
     The latch is keyed to the approval itself — React reuses this component
     for whatever block occupies the same position, so instance-only state
     would render a *new* approval as already decided and trap the user. */
  const [latched, setLatched] = useState<{ id: string; decision: 'approved' | 'rejected' } | null>(null);
  const submitted = latched && latched.id === approvalId ? latched.decision : null;
  const decide = (decision: 'approved' | 'rejected') => {
    if (submitted || !onApprovalDecision || !approvalId || !hash) return;
    setLatched({ id: approvalId, decision });
    onApprovalDecision(approvalId, decision, hash);
  };
  return (
    <section className="agent-approval-block">
      <ShieldAlert size={18} />
      <span>
        <strong>{text(data.title ?? data.summary) || '需要批准'}</strong>
        <small>{text(data.detail ?? data.action)}</small>
      </span>
      {pending && onApprovalDecision && approvalId && hash ? (
        <span className="agent-approval-block__actions">
          <Button
            size="small"
            variant="quiet"
            disabled={submitted !== null}
            onClick={() => decide('rejected')}
          >
            {submitted === 'rejected' ? '已拒绝' : '拒绝'}
          </Button>
          <Button
            size="small"
            variant="primary"
            disabled={submitted !== null}
            onClick={() => decide('approved')}
          >
            {submitted === 'approved' ? '已批准' : '批准'}
          </Button>
        </span>
      ) : null}
    </section>
  );
}

export function ErrorBlockRenderer({ block }: AgentBlockRenderProps) {
  const data = block.data;
  return (
    <div className="agent-inline-notice" data-tone="danger" role="alert">
      <TriangleAlert size={16} />
      <span>{publicAgentErrorText(data.message ?? data.summary)}</span>
    </div>
  );
}

export function ReasoningSummaryBlockRenderer() {
  const identity = useProductIdentity();
  return (
    <details className="agent-rich-collapsible agent-reasoning-summary" data-tone="info">
      <summary>
        <span className="agent-insert-icon"><CircleDashed size={16} /></span>
        <span>处理进度</span>
        <small>思考中</small>
        <ChevronRight className="agent-rich-collapsible__chevron" size={14} />
      </summary>
      <p>{identity.assistantName}正在整理信息与下一步。</p>
    </details>
  );
}

export function ProgressBlockRenderer({ block }: AgentBlockRenderProps) {
  const data = block.data;
  const state = text(data.state ?? data.status) || 'running';
  const title = text(data.title ?? data.summary) || '处理进度';
  const detail = text(data.detail ?? data.label) || publicStructuredValue(state);
  const percent = typeof data.percent === 'number'
    ? Math.max(0, Math.min(100, Math.round(data.percent)))
    : null;
  return (
    <section
      aria-label={title}
      className="agent-rich-status agent-rich-progress"
      data-state={state}
      data-tone={['failed', 'blocked'].includes(state) ? 'danger' : 'info'}
    >
      <span className="agent-insert-icon">
        <CircleDashed className={state === 'running' ? 'agent-tool-activity__spinner' : undefined} size={16} />
      </span>
      <span><strong>{title}</strong><small>{detail}</small></span>
      {percent === null ? null : (
        <strong className="agent-rich-status__metric">{percent}%</strong>
      )}
    </section>
  );
}

export function ToolCallBlockRenderer({ block }: AgentBlockRenderProps) {
  return <ToolActivityBlock type="tool_call" block={block} />;
}

export function ToolResultBlockRenderer({ block }: AgentBlockRenderProps) {
  return <ToolActivityBlock type="tool_result" block={block} />;
}

function ToolActivityBlock({
  block,
  type,
}: {
  block: UiAgentBlock;
  type: 'tool_call' | 'tool_result';
}) {
  const data = block.data;
  const toolId = text(data.toolName ?? data.toolId ?? data.name);
  const label = publicToolLabel(toolId);
  const status = text(data.status) || block.status;
  const running = status === 'running' || status === 'pending';
  const tone = ['failed', 'error', 'blocked'].includes(status)
    ? 'danger'
    : ['waiting', 'pending', 'paused'].includes(status)
      ? 'warning'
      : running ? 'info' : 'success';
  const summary = text(data.summary ?? data.title)
    || (type === 'tool_call' ? `${label}正在处理` : `${label}已返回`);
  return (
    <details
      className="agent-tool-activity agent-structured-block"
      data-state={status}
      data-tone={tone}
      open={running}
    >
      <summary>
        <span className="agent-insert-icon">
          {running ? <CircleDashed className="agent-tool-activity__spinner" size={15} /> : <Wrench size={15} />}
        </span>
        <span>{summary}</span>
        <small>{running ? '进行中' : publicStructuredValue(status)}</small>
        <ChevronRight className="agent-rich-collapsible__chevron" size={14} />
      </summary>
      <SafeFieldList data={data} />
    </details>
  );
}

function StructuredSummaryBlock({
  type,
  data,
}: {
  type: UiAgentBlock['type'];
  data: Record<string, unknown>;
}) {
  return (
    <details className="agent-structured-block" data-tone="info">
      <summary>
        <span>{text(data.summary ?? data.title ?? data.label) || structuredLabel(type)}</span>
        <ChevronRight className="agent-rich-collapsible__chevron" size={14} />
      </summary>
      <SafeFieldList data={data} />
    </details>
  );
}

export function SafeFieldList({ data }: { data: Record<string, unknown> }) {
  const allowed = [
    'query',
    'status',
    'resultCount',
    'books',
    'recentItems',
    'completed',
    'artifacts',
    'risk',
  ];
  const entries = allowed
    .filter((key) => Object.hasOwn(data, key))
    .map((key) => [key, safeFieldValue(data[key])] as const)
    .filter((entry) => entry[1]);
  if (entries.length === 0) return <p>暂无可展示的结构化明细。</p>;
  return (
    <dl className="agent-safe-fields">
      {entries.map(([key, value]) => (
        <div key={key}><dt>{fieldLabel(key)}</dt><dd>{value}</dd></div>
      ))}
    </dl>
  );
}

function structuredLabel(type: UiAgentBlock['type']): string {
  return type === 'reasoning_summary' ? '处理说明' : '进度';
}

function fieldLabel(key: string): string {
  return ({
    query: '查询',
    status: '状态',
    resultCount: '结果数',
    books: '工具书',
    recentItems: '近期记录',
    completed: '已完成',
    artifacts: '产物',
    risk: '确认级别',
  } as Record<string, string>)[key] ?? key;
}

function safeFieldValue(value: unknown): string {
  if (typeof value === 'string') return publicStructuredValue(value);
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) {
    return value
      .filter((item) => ['string', 'number', 'boolean'].includes(typeof item))
      .map((item) => typeof item === 'string' ? publicStructuredValue(item) : String(item))
      .join('、');
  }
  return '';
}

export function BlockedMedia({ icon, label }: { icon: ReactNode; label: string }) {
  return <div className="agent-inline-notice" data-tone="neutral">{icon}<span>{label}</span></div>;
}

function statusIcon(tone: string): ReactNode {
  if (tone === 'success') return <CheckCircle2 size={16} />;
  if (tone === 'danger' || tone === 'warning') return <TriangleAlert size={16} />;
  return <Activity size={16} />;
}

function TableCell({ value }: { value: unknown }) {
  const label = displayScalar(value);
  const tone = tableCellTone(label);
  return (
    <td data-tone={tone || undefined}>
      {tone ? <span>{label}</span> : label}
    </td>
  );
}

function tableCellTone(value: string): 'success' | 'warning' | 'danger' | 'info' | null {
  const normalized = value.trim().toLowerCase();
  if ([
    '已完成', '完成', '通过', '已通过', '成功', '已覆盖', '健康',
    'completed', 'done', 'passed', 'success', 'healthy',
  ].includes(normalized)) return 'success';
  if ([
    '需确认', '待确认', '等待', '等待中', '待处理', '待审批',
    'pending', 'waiting', 'needs review',
  ].includes(normalized)) return 'warning';
  if ([
    '失败', '错误', '阻塞', '已阻塞', '不健康',
    'failed', 'error', 'blocked', 'unhealthy',
  ].includes(normalized)) return 'danger';
  if ([
    '进行中', '处理中', '运行中',
    'running', 'in progress', 'processing',
  ].includes(normalized)) return 'info';
  return null;
}
