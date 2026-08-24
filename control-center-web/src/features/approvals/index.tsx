import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  Check,
  Clock3,
  ExternalLink,
  RefreshCw,
  Search,
  ShieldCheck,
  ShieldQuestion,
  X,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import { useControlTransport } from '@/app/control-transport';
import { Button, Disclosure, EmptyState, Field, Input, SegmentedControl, Select } from '@/components/primitives';
import type { AgentApprovalV1 } from '@/contracts/generated/agent-approval.v1';
import {
  ManagementPage,
  ManagementSection,
  MetricStrip,
  QueryState,
  StatusBadge,
  publicErrorText,
} from '@/features/overview/management-ui';
import './approvals.css';

type ApprovalFilter = 'pending' | 'all' | 'resolved';
type RiskFilter = 'all' | AgentApprovalV1['riskLevel'];

export function ApprovalsFeature() {
  const transport = useControlTransport();
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<ApprovalFilter>('pending');
  const [risk, setRisk] = useState<RiskFilter>('all');
  const [query, setQuery] = useState('');
  const [pendingId, setPendingId] = useState('');
  const [confirmingId, setConfirmingId] = useState('');
  const [actionError, setActionError] = useState<Record<string, string>>({});
  const approvalsQuery = useQuery({
    queryKey: ['approvals', 'all'],
    queryFn: ({ signal }) => transport.request({
      pathId: 'agent.approvals.list',
      query: { limit: 500 },
      signal,
    }),
    refetchInterval: (queryState) => approvalItems(queryState.state.data).some((item) => item.state === 'pending') ? 5_000 : false,
    retry: false,
  });
  const sessionsQuery = useQuery({
    queryKey: ['approvals', 'sessions'],
    queryFn: ({ signal }) => transport.request({
      pathId: 'agent.sessions.list',
      query: { limit: 200, includeArchived: true },
      signal,
    }),
    staleTime: 30_000,
    retry: false,
  });
  const approvals = useMemo(() => approvalItems(approvalsQuery.data), [approvalsQuery.data]);
  const sessions = useMemo(() => sessionTitles(sessionsQuery.data), [sessionsQuery.data]);
  const pending = approvals.filter((item) => item.state === 'pending');
  const highRisk = pending.filter((item) => item.riskLevel === 'R3');
  const expiring = pending.filter((item) => item.expiresAtMs > Date.now() && item.expiresAtMs - Date.now() <= 5 * 60_000);
  const completed = approvals.filter((item) => ['applied', 'rejected'].includes(item.state));
  const visible = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase('zh-CN');
    return approvals.filter((item) => {
      const matchesState = filter === 'all'
        || (filter === 'pending' ? item.state === 'pending' : item.state !== 'pending');
      const matchesRisk = risk === 'all' || item.riskLevel === risk;
      const haystack = [
        item.toolId,
        item.operation,
        previewSummary(item.preview),
        sessions.get(item.sessionId) ?? '',
      ].join(' ').toLocaleLowerCase('zh-CN');
      return matchesState && matchesRisk && (!needle || haystack.includes(needle));
    });
  }, [approvals, filter, query, risk, sessions]);

  async function decide(item: AgentApprovalV1, decision: 'approve' | 'reject'): Promise<void> {
    if (decision === 'approve' && item.riskLevel === 'R3' && confirmingId !== item.approvalId) {
      setConfirmingId(item.approvalId);
      return;
    }
    if (pendingId) return;
    setPendingId(item.approvalId);
    setActionError((current) => ({ ...current, [item.approvalId]: '' }));
    try {
      await transport.request({
        pathId: 'agent.approval.decide',
        params: { approvalId: item.approvalId },
        body: { decision, payloadSha256: item.payloadSha256 },
      });
      setConfirmingId('');
      await queryClient.invalidateQueries({ queryKey: ['approvals', 'all'] });
    } catch (error) {
      setActionError((current) => ({
        ...current,
        [item.approvalId]: publicErrorText(error, '这项审批没有更新；已保留原状态。'),
      }));
      await approvalsQuery.refetch();
    } finally {
      setPendingId('');
    }
  }

  return (
    <ManagementPage
      actions={<Button leadingIcon={<RefreshCw size={15} />} loading={approvalsQuery.isFetching} onClick={() => void approvalsQuery.refetch()} size="small">刷新</Button>}
      description="集中查看所有 Session 和 Room 伙伴等待中的高风险操作。审批只决定一个哈希绑定的具体请求，不会扩大后续权限。"
      eyebrow="人类决策队列"
      routeId="approvals"
      title="审批中心"
    >
      <QueryState error={approvalsQuery.error ? new Error(publicErrorText(approvalsQuery.error, '无法读取审批队列。')) : null} isPending={approvalsQuery.isPending} onRetry={() => void approvalsQuery.refetch()}>
        <MetricStrip items={[
          { label: '等待决定', value: pending.length, detail: pending.length ? '逐项处理' : '当前已清空', icon: ShieldQuestion, tone: pending.length ? 'warning' : 'success' },
          { label: '高风险', value: highRisk.length, detail: 'R3 需要二次确认', icon: AlertTriangle, tone: highRisk.length ? 'danger' : 'neutral' },
          { label: '即将过期', value: expiring.length, detail: '5 分钟内', icon: Clock3, tone: expiring.length ? 'warning' : 'neutral' },
          { label: '已收束', value: completed.length, detail: '已执行或已拒绝', icon: ShieldCheck, tone: 'success' },
        ]} />

        <ManagementSection
          title="审批队列"
          description="失败、过期或已被 Pi 释放的请求会保留事实记录，但不能再次批准。"
          trailing={<span className="approvals-count">{visible.length} 项</span>}
        >
          <div className="approvals-toolbar">
            <SegmentedControl
              aria-label="审批状态筛选"
              items={[
                { label: '待审批', value: 'pending' },
                { label: '全部', value: 'all' },
                { label: '已处理', value: 'resolved' },
              ]}
              onValueChange={(value) => setFilter(value as ApprovalFilter)}
              value={filter}
            />
            <Field htmlFor="approval-risk" label="风险">
              <Select
                id="approval-risk"
                onValueChange={(value) => setRisk(value as RiskFilter)}
                options={[
                  { value: 'all', label: '全部风险' },
                  { value: 'R1', label: 'R1 · 低风险' },
                  { value: 'R2', label: 'R2 · 受控操作' },
                  { value: 'R3', label: 'R3 · 高风险' },
                ]}
                value={risk}
              />
            </Field>
            <Field className="approvals-search" htmlFor="approval-search" label="搜索">
              <Input id="approval-search" onChange={(event) => setQuery(event.target.value)} placeholder="工具、操作、对话或摘要" type="search" value={query} />
            </Field>
          </div>

          {visible.length ? <ol className="approvals-list" aria-label="审批项目">
            {visible.map((item) => (
              <ApprovalCard
                error={actionError[item.approvalId] ?? ''}
                item={item}
                key={item.approvalId}
                pending={pendingId === item.approvalId}
                confirming={confirmingId === item.approvalId}
                sessionTitle={sessions.get(item.sessionId) ?? '所属对话'}
                onCancelConfirm={() => setConfirmingId('')}
                onDecide={(decision) => void decide(item, decision)}
              />
            ))}
          </ol> : (
            <EmptyState
              action={(query || risk !== 'all' || filter !== 'pending') ? <Button onClick={() => { setQuery(''); setRisk('all'); setFilter('pending'); }} size="small">查看待审批</Button> : undefined}
              description={filter === 'pending' && !query && risk === 'all' ? '新的高风险请求会在这里逐项出现。' : '调整筛选条件后再查看。'}
              icon={Search}
              title={filter === 'pending' && !query && risk === 'all' ? '当前没有待审批请求' : '没有匹配的审批'}
            />
          )}
        </ManagementSection>
      </QueryState>
    </ManagementPage>
  );
}

function ApprovalCard({
  item,
  sessionTitle,
  pending,
  confirming,
  error,
  onDecide,
  onCancelConfirm,
}: {
  item: AgentApprovalV1;
  sessionTitle: string;
  pending: boolean;
  confirming: boolean;
  error: string;
  onDecide: (decision: 'approve' | 'reject') => void;
  onCancelConfirm: () => void;
}) {
  const summary = previewSummary(item.preview) || `${item.toolId} · ${item.operation}`;
  const facts = previewFacts(item.preview);
  const compactFacts = facts.slice(0, 5);
  return <li data-risk={item.riskLevel} data-state={item.state}>
    <header>
      <span className="approvals-list__risk">{item.riskLevel}</span>
      <span><strong>{summary}</strong><small>{toolLabel(item.toolId)} · {operationLabel(item.operation)}</small></span>
      <StatusBadge label={stateLabel(item.state)} tone={stateTone(item.state)} />
    </header>
    <div className="approvals-list__context">
      <a href={`#/agent?session=${encodeURIComponent(item.sessionId)}`}>{sessionTitle}<ExternalLink size={12} /></a>
      <span>请求于 {formatTime(item.requestedAtMs)}</span>
      <span>{item.state === 'pending' ? expiryLabel(item.expiresAtMs) : `决定于 ${formatTime(item.decidedAtMs ?? item.requestedAtMs)}`}</span>
    </div>
    {compactFacts.length ? <dl>{compactFacts.map((fact) => <div key={fact.label}><dt>{fact.label}</dt><dd>{compactPreviewValue(fact.value)}</dd></div>)}</dl> : null}
    {Object.keys(item.preview).length ? <ApprovalPreviewDisclosure item={item} /> : null}
    {confirming ? <p className="approvals-list__confirm"><AlertTriangle size={15} /><span><strong>确认批准 R3 高风险操作？</strong><small>只批准当前哈希绑定请求；不会自动批准同类操作。</small></span></p> : null}
    {error ? <p className="approvals-list__error" role="alert">{error}</p> : null}
    {item.state === 'pending' ? <footer>
      {confirming ? <Button disabled={pending} onClick={onCancelConfirm} size="small" variant="quiet">取消</Button> : null}
      <Button disabled={pending} leadingIcon={<X size={14} />} onClick={() => onDecide('reject')} size="small" variant="quiet">拒绝</Button>
      <Button loading={pending} leadingIcon={<Check size={14} />} onClick={() => onDecide('approve')} size="small" variant="primary">{confirming ? '确认批准' : '批准'}</Button>
    </footer> : null}
  </li>;
}

function ApprovalPreviewDisclosure({ item }: { item: AgentApprovalV1 }) {
  const fieldCount = Object.keys(item.preview).length;
  return (
    <Disclosure
      className="approvals-preview"
      revealClassName="approvals-preview__reveal"
      summary={<>
        <span>完整预览</span>
        <small>{fieldCount} 个字段 · SHA-256 绑定</small>
      </>}
    >
      <div className="approvals-preview__body">
        <p><ShieldCheck size={15} /><span>以下完整预览与本次审批哈希绑定</span></p>
        <div className="approvals-preview__binding"><span>SHA-256</span><code>{item.payloadSha256}</code></div>
        <pre>{JSON.stringify(redactApprovalPreview(item.preview), null, 2)}</pre>
      </div>
    </Disclosure>
  );
}

function approvalItems(value: unknown): AgentApprovalV1[] {
  const items = record(value).items;
  return Array.isArray(items) ? items.filter(isApproval) : [];
}

function isApproval(value: unknown): value is AgentApprovalV1 {
  const item = record(value);
  return item.schemaVersion === 'rag-ime.agent-approval.v1'
    && typeof item.approvalId === 'string'
    && typeof item.sessionId === 'string'
    && typeof item.payloadSha256 === 'string'
    && ['R1', 'R2', 'R3'].includes(String(item.riskLevel))
    && ['pending', 'approved', 'external_pending', 'rejected', 'expired', 'stale', 'applied', 'failed'].includes(String(item.state));
}

function sessionTitles(value: unknown): Map<string, string> {
  const envelope = record(value);
  const items = Array.isArray(envelope.items) ? envelope.items : Array.isArray(envelope.sessions) ? envelope.sessions : [];
  return new Map(items.flatMap((value) => {
    const item = record(value);
    const id = text(item.id);
    return id ? [[id, text(item.title) || '所属对话'] as const] : [];
  }));
}

function previewSummary(preview: Record<string, unknown>): string {
  return [preview.summary, preview.title, preview.message, preview.description].map(text).find(Boolean) ?? '';
}

function previewFacts(preview: Record<string, unknown>): Array<{ label: string; value: string }> {
  const ignored = new Set(['summary', 'title', 'message', 'description']);
  return Object.entries(preview).flatMap(([key, value]) => {
    if (ignored.has(key)) return [];
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      return [{ label: publicKey(key), value: String(value) }];
    }
    if (Array.isArray(value)) return [{ label: publicKey(key), value: `${value.length} 项` }];
    return [];
  });
}

function compactPreviewValue(value: string): string {
  return value.length > 160 ? `${value.slice(0, 157)}…` : value;
}

function redactApprovalPreview(value: unknown, key = ''): unknown {
  if (/token|secret|password|api.?key|authorization|cookie/i.test(key)) return value ? '已隐藏' : '未配置';
  if (Array.isArray(value)) return value.map((item) => redactApprovalPreview(item));
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([entryKey, item]) => (
    [entryKey, redactApprovalPreview(item, entryKey)]
  )));
}

function stateLabel(state: AgentApprovalV1['state']): string {
  return ({ pending: '等待决定', approved: '已批准待执行', external_pending: '等待外部完成', rejected: '已拒绝', expired: '已过期', stale: '已失效', applied: '已执行', failed: '执行失败' })[state];
}

function stateTone(state: AgentApprovalV1['state']): 'success' | 'warning' | 'danger' | 'info' | 'neutral' {
  if (state === 'applied') return 'success';
  if (state === 'pending' || state === 'approved' || state === 'external_pending') return 'warning';
  if (state === 'failed') return 'danger';
  return 'neutral';
}

function toolLabel(value: string): string {
  return ({ workspace_shell: '运行命令', workspace_patch: '修改文件', workspace_write: '写入文件', runtime: '运行时', configuration: '设置', memory: '记忆', input: '输入法' } as Record<string, string>)[value] ?? value;
}

function operationLabel(value: string): string {
  return ({ run: '执行', apply: '应用', restart: '重启', restore_apply: '恢复', apply_settings: '应用设置' } as Record<string, string>)[value] ?? value;
}

function publicKey(value: string): string {
  return ({ command: '命令', path: '路径', changes: '变更', target: '目标', scope: '范围', files: '文件' } as Record<string, string>)[value] ?? value;
}

function expiryLabel(value: number): string {
  const remaining = value - Date.now();
  if (remaining <= 0) return '正在核对是否过期';
  const minutes = Math.max(1, Math.ceil(remaining / 60_000));
  return `${minutes} 分钟后过期`;
}

function formatTime(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '时间未记录';
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value));
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}
