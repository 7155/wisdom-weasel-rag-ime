import {
  Activity,
  CheckCircle2,
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
      <header><strong>{title}</strong></header>
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
  return (
    <details className="agent-rich-checklist agent-rich-collapsible" open={items.length <= 8}>
      <summary>
        <ListChecks size={16} />
        {title}
        <small>{items.filter((item) => item.checked).length}/{items.length}</small>
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
    <details className="agent-rich-table agent-rich-collapsible" open={rows.length <= 8}>
      <summary><Table2 size={16} />{title}<small>{rows.length} 行</small></summary>
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
                      <td key={column.key}>{displayScalar(rowArray[columnIndex] ?? rowRecord[column.key])}</td>
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
    : ['done', 'completed', 'success'].includes(state) ? 'success' : 'info';
  const title = text(data.title) || '状态更新';
  const fields = safeLabelValuePairs(data.fields);
  return (
    <section className="agent-rich-status" data-tone={tone} aria-label={title}>
      <Activity size={17} />
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
  return (
    <section className="agent-task-plan">
      <strong>{text(data.title) || '任务计划'}</strong>
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
  const pending = !['approved', 'rejected', 'applied'].includes(text(data.state));
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
            onClick={() => onApprovalDecision(approvalId, 'rejected', hash)}
          >
            拒绝
          </Button>
          <Button
            size="small"
            variant="primary"
            onClick={() => onApprovalDecision(approvalId, 'approved', hash)}
          >
            批准
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
    <details className="agent-structured-block">
      <summary>处理进度</summary>
      <p>{identity.assistantName}正在整理信息与下一步。</p>
    </details>
  );
}

export function ProgressBlockRenderer({ block }: AgentBlockRenderProps) {
  return <StructuredSummaryBlock type="progress" data={block.data} />;
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
  const summary = text(data.summary ?? data.title)
    || (type === 'tool_call' ? `${label}正在处理` : `${label}已返回`);
  return (
    <details className="agent-tool-activity agent-structured-block" open={running}>
      <summary>
        {running ? <CircleDashed className="agent-tool-activity__spinner" size={15} /> : <Wrench size={15} />}
        <span>{summary}</span>
        <small>{running ? '进行中' : publicStructuredValue(status)}</small>
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
    <details className="agent-structured-block">
      <summary>{text(data.summary ?? data.title ?? data.label) || structuredLabel(type)}</summary>
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
