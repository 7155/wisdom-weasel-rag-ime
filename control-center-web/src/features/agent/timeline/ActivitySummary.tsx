import {
  BookOpenText,
  Bot,
  Brain,
  CheckCircle2,
  CircleDashed,
  Database,
  GitBranch,
  Search,
  ShieldAlert,
  TerminalSquare,
  TriangleAlert,
  Wrench,
  type LucideIcon,
} from 'lucide-react';
import { Button } from '@/components/primitives';
import type { AgentActivityProjection } from '@/contracts/agent-reducer';
import { SafeFieldList } from './BlockRenderer';
import { publicToolResultView, safeSourceLabels, type PublicToolResultView } from './public-tool-result';

export function ActivitySummary({
  activities,
  onApprovalDecision,
}: {
  activities: AgentActivityProjection[];
  onApprovalDecision?: (approvalId: string, decision: 'approved' | 'rejected', hash: string) => void;
}) {
  if (activities.length === 0) return null;
  const running = activities.some((activity) => activity.status === 'running');
  const waiting = activities.some((activity) => activity.status === 'waiting');
  const failed = activities.some((activity) => activity.status === 'failed');
  const summary = aggregateSummary(activities);
  return (
    <details className="agent-activity" data-state={failed ? 'failed' : waiting ? 'waiting' : running ? 'running' : 'done'}>
      <summary>
        <span className="agent-activity__status" aria-hidden="true">
          {failed ? <TriangleAlert size={15} /> : waiting ? <ShieldAlert size={15} /> : running ? <CircleDashed size={15} /> : <CheckCircle2 size={15} />}
        </span>
        <span>
          <strong>{running ? '正在处理' : waiting ? '等待你的确认' : failed ? '活动中有失败项' : '活动已完成'}</strong>
          <small>{summary}</small>
        </span>
      </summary>
      <div className="agent-activity__timeline">
        {activities.map((activity) => (
          <ActivityRow
            key={activity.id}
            activity={activity}
            onApprovalDecision={onApprovalDecision}
          />
        ))}
      </div>
    </details>
  );
}

function ActivityRow({
  activity,
  onApprovalDecision,
}: {
  activity: AgentActivityProjection;
  onApprovalDecision?: (approvalId: string, decision: 'approved' | 'rejected', hash: string) => void;
}) {
  const presentation = activityPresentation(activity);
  const Icon = presentation.icon;
  const payload = activity.payload;
  const isToolActivity = activity.kind === 'tool_started' || activity.kind === 'tool_progress' || activity.kind === 'tool_finished';
  const toolView = isToolActivity ? publicToolResultView(activity) : null;
  const approvalId = text(payload.approvalId);
  const hash = text(payload.payloadSha256);
  const canDecide = activity.status === 'waiting' && approvalId && hash && onApprovalDecision;
  return (
    <details className="agent-activity-row">
      <summary>
        <span className="agent-activity-row__icon" data-kind={presentation.kind}><Icon size={15} /></span>
        <span>
          <strong>{presentation.title}</strong>
          <small>{activity.kind === 'reasoning_summary' ? '正在整理信息与下一步' : toolView?.summary ?? publicActivitySummary(activity.summary, presentation.title)}</small>
        </span>
        <i data-status={activity.status}>{statusLabel(activity.status)}</i>
      </summary>
      <div className="agent-activity-row__details">
        {presentation.detail ? <p>{presentation.detail}</p> : null}
        {toolView ? <PublicToolFields view={toolView} /> : <SafeFieldList data={payload} />}
        <SourceList items={toolView?.sources ?? safeSourceLabels(payload.sources ?? payload.documents ?? payload.books)} />
        {canDecide ? (
          <div className="agent-activity-row__approval-actions">
            <Button size="small" variant="quiet" onClick={() => onApprovalDecision(approvalId, 'rejected', hash)}>拒绝</Button>
            <Button size="small" variant="primary" onClick={() => onApprovalDecision(approvalId, 'approved', hash)}>批准</Button>
          </div>
        ) : null}
      </div>
    </details>
  );
}

function PublicToolFields({ view }: { view: PublicToolResultView }) {
  if (view.fields.length === 0) return <p>工具没有返回可公开展示的结构化明细。</p>;
  return (
    <dl className="agent-safe-fields">
      {view.fields.map((field) => (
        <div key={field.id}><dt>{field.label}</dt><dd>{field.value}</dd></div>
      ))}
    </dl>
  );
}

function SourceList({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return <ul className="agent-activity-row__sources">{items.map((item) => <li key={item}>{item}</li>)}</ul>;
}

interface ActivityPresentation {
  title: string;
  kind: 'thinking' | 'tool' | 'rag' | 'memory' | 'subagent' | 'approval' | 'runtime';
  icon: LucideIcon;
  detail?: string;
}

function activityPresentation(activity: AgentActivityProjection): ActivityPresentation {
  const payload = activity.payload;
  const toolId = text(payload.toolId ?? payload.toolName).toLowerCase();
  const toolView = activity.kind.startsWith('tool_') ? publicToolResultView(activity) : null;
  if (activity.kind === 'reasoning_summary') {
    return { title: '处理说明', kind: 'thinking', icon: Brain };
  }
  if (activity.kind.includes('approval') || activity.kind === 'user_input_required') {
    return { title: '权限确认', kind: 'approval', icon: ShieldAlert, detail: '是否执行以你的本机确认结果为准。' };
  }
  if (activity.kind.includes('memory') || toolId.includes('memory')) {
    return { title: '记忆', kind: 'memory', icon: BookOpenText };
  }
  if (toolId.includes('knowledge') || toolId.includes('rag') || text(payload.operation) === 'search') {
    return { title: toolId === 'ime_knowledge' ? '文档知识库' : '知识检索', kind: 'rag', icon: Search };
  }
  if (toolId.includes('subagent') || activity.kind.includes('subagent')) {
    return { title: '协作 Agent', kind: 'subagent', icon: GitBranch };
  }
  if (toolId.includes('runtime') || toolId.includes('workspace')) {
    return { title: '运行环境', kind: 'runtime', icon: toolId.includes('workspace') ? TerminalSquare : Database };
  }
  if (toolId.includes('planning')) return { title: '规划', kind: 'tool', icon: Bot };
  return { title: toolView?.toolLabel ?? '工具操作', kind: 'tool', icon: Wrench };
}

function publicActivitySummary(value: string, fallback: string): string {
  const summary = value.trim();
  if (!summary) return `${fallback}已更新`;
  if (/^[a-z][a-z0-9_.:/-]*$/i.test(summary) || /(?:session|participant|activity|event|tool_call|tool_result)/i.test(summary)) {
    return `${fallback}已更新`;
  }
  return summary;
}

function aggregateSummary(activities: AgentActivityProjection[]): string {
  const counts = new Map<string, number>();
  for (const activity of activities) {
    const label = activityPresentation(activity).title;
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([label, count]) => `${label} ${count}`)
    .join(' · ');
}

function statusLabel(status: AgentActivityProjection['status']): string {
  switch (status) {
    case 'running': return '进行中';
    case 'waiting': return '待确认';
    case 'failed': return '失败';
    case 'completed': return '完成';
  }
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
