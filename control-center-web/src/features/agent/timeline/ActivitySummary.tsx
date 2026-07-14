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
  const approvalId = text(payload.approvalId);
  const hash = text(payload.payloadSha256);
  const canDecide = activity.status === 'waiting' && approvalId && hash && onApprovalDecision;
  return (
    <details className="agent-activity-row">
      <summary>
        <span className="agent-activity-row__icon" data-kind={presentation.kind}><Icon size={15} /></span>
        <span>
          <strong>{presentation.title}</strong>
          <small>{activity.summary}</small>
        </span>
        <i data-status={activity.status}>{statusLabel(activity.status)}</i>
      </summary>
      <div className="agent-activity-row__details">
        {presentation.detail ? <p>{presentation.detail}</p> : null}
        <SafeFieldList data={payload} />
        <SourceList value={payload.sources ?? payload.documents ?? payload.books} />
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

function SourceList({ value }: { value: unknown }) {
  if (!Array.isArray(value)) return null;
  const items = value.map((item) => text(item) || text(record(item).title ?? record(item).name)).filter(Boolean).slice(0, 8);
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
  if (activity.kind === 'reasoning_summary') {
    return { title: '思考摘要', kind: 'thinking', icon: Brain };
  }
  if (activity.kind.includes('approval') || activity.kind === 'user_input_required') {
    return { title: '权限确认', kind: 'approval', icon: ShieldAlert, detail: '批准状态以服务端回执为准。' };
  }
  if (activity.kind.includes('memory') || toolId.includes('memory')) {
    return { title: '记忆', kind: 'memory', icon: BookOpenText };
  }
  if (toolId.includes('knowledge') || toolId.includes('rag') || text(payload.operation) === 'search') {
    return { title: 'RAG 检索', kind: 'rag', icon: Search };
  }
  if (toolId.includes('subagent') || activity.kind.includes('subagent')) {
    return { title: '子 Agent', kind: 'subagent', icon: GitBranch };
  }
  if (toolId.includes('runtime') || toolId.includes('workspace')) {
    return { title: '运行时', kind: 'runtime', icon: toolId.includes('workspace') ? TerminalSquare : Database };
  }
  if (toolId.includes('planning')) return { title: '规划', kind: 'tool', icon: Bot };
  return { title: text(payload.toolName ?? payload.label) || '工具', kind: 'tool', icon: Wrench };
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

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}
