import { Clock3, History, MessageSquareText, RefreshCw, Search, ShieldCheck } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Button, EmptyState, Field, Input } from '@/components/primitives';
import { useHistoryPages } from './api';
import {
  DataTable,
  InlineNotice,
  ManagementPage,
  ManagementSection,
  MetricStrip,
  PaginationBar,
  QueryState,
  WorkflowAction,
  arrayRecords,
  asRecord,
  formatTime,
  numberValue,
  stringValue,
} from '@/features/overview/management-ui';

export function HistoryFeature() {
  const [draftQuery, setDraftQuery] = useState('');
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const { pages } = useHistoryPages(query, filter);
  const rows = useMemo(() => (pages.data?.pages ?? [])
    .flatMap((page) => arrayRecords(asRecord(page).items))
    .map((item) => ({
      ...item,
      created: formatTime(item.createdAtMs),
      sourceLabel: sourceLabel(stringValue(item.source)),
      text: stringValue(item.textPreview, `已脱敏 · ${numberValue(item.textChars)} 字`),
      context: stringValue(item.contextHash, 'none'),
    } as Record<string, unknown>)), [pages.data]);
  const sources = new Set(rows.map((row) => stringValue(row.source)).filter(Boolean));
  const selected = rows.find((row) => stringValue(row.id) === selectedId);

  return (
    <ManagementPage
      actions={<Button leadingIcon={<RefreshCw size={15} />} loading={pages.isRefetching} onClick={() => void pages.refetch()} size="small">刷新</Button>}
      description="查看脱敏的输入记录、候选来源与反馈。"
      eyebrow="ACTIVITY"
      routeId="history"
      title="输入历史"
    >
      <QueryState error={pages.error as Error | null} isPending={pages.isPending} onRetry={() => void pages.refetch()}>
        <ManagementSection title="已加载快照">
          <MetricStrip items={[
            { label: '记录', value: rows.length, detail: '当前分页窗口', icon: History },
            { label: '来源', value: sources.size, detail: '候选来源', icon: MessageSquareText },
            { label: '原文策略', value: 'redacted', detail: '脱敏摘要', icon: ShieldCheck, tone: 'success' },
            { label: '下一页', value: pages.hasNextPage ? 'available' : 'end', detail: '继续加载', icon: Clock3, tone: pages.hasNextPage ? 'info' : 'neutral' },
          ]} />
          <InlineNotice title="隐私" tone="info">历史记录仅展示脱敏摘要与来源，不显示完整个人输入。</InlineNotice>
        </ManagementSection>

        <ManagementSection title="筛选与分页">
          <div className="mgmt-filter-row">
            <Field htmlFor="history-search" label="搜索">
              <Input id="history-search" onChange={(event) => setDraftQuery(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') setQuery(draftQuery.trim()); }} placeholder="文本、应用或项目" value={draftQuery} />
            </Field>
            <Button leadingIcon={<Search size={14} />} onClick={() => setQuery(draftQuery.trim())} size="small">搜索</Button>
            <label className="ui-field">
              <span className="ui-field__label">来源</span>
              <select className="ui-input" onChange={(event) => setFilter(event.target.value)} value={filter}>
                <option value="">全部来源</option>
                <option value="rime_commit">Rime 提交</option>
                <option value="assistant_candidate">助手候选</option>
                <option value="voice">语音</option>
                <option value="import">导入</option>
              </select>
            </label>
          </div>
          {rows.length ? (
            <>
              <DataTable caption="输入历史分页" columns={[
                { key: 'id', label: 'ID', width: '8%' },
                { key: 'created', label: '时间', width: '18%' },
                { key: 'sourceLabel', label: '来源', width: '14%' },
                { key: 'text', label: '文本预览' },
                { key: 'app', label: '应用', width: '14%' },
                { key: 'project', label: '项目', width: '14%' },
              ]} rows={rows} />
              <PaginationBar count={rows.length} hasMore={pages.hasNextPage} isFetching={pages.isFetchingNextPage} onLoadMore={() => void pages.fetchNextPage()} />
            </>
          ) : <EmptyState description="当前筛选没有历史记录。" icon={Search} title="历史为空" />}
        </ManagementSection>

        <ManagementSection title="反馈与移除" description="选择已加载记录后，所有写动作都先预览影响并生成可回滚收据。">
          <label className="ui-field" style={{ maxWidth: 420 }}>
            <span className="ui-field__label">记录</span>
            <select className="ui-input" onChange={(event) => setSelectedId(event.target.value)} value={selectedId}>
              <option value="">请选择</option>
              {rows.map((row) => <option key={stringValue(row.id)} value={stringValue(row.id)}>#{stringValue(row.id)} · {stringValue(row.text)}</option>)}
            </select>
          </label>
          <div className="mgmt-grid-2" style={{ marginTop: 12 }}>
            <WorkflowAction
              actionId="history.feedback"
              description="为所选候选提交负反馈，并保留来源信息。"
              mutationKey={['history', 'mutation', 'feedback']}
              preview={[`记录 ID：${selectedId || '尚未选择'}`, `来源：${stringValue(selected?.sourceLabel, 'unknown')}`, '反馈会保留候选来源和排序位置。']}
              risk="R1"
              title="记录负反馈"
            />
            <WorkflowAction
              actionId="history.tombstone"
              description="从后续召回中隐藏所选记录，原始记录仍保留。"
              mutationKey={['history', 'mutation', 'tombstone']}
              preview={[`记录 ID：${selectedId || '尚未选择'}`, '不会删除原始记录。', '回滚后可重新参与召回。']}
              risk="R2"
              title="隐藏记录"
            />
          </div>
        </ManagementSection>
      </QueryState>
    </ManagementPage>
  );
}

function sourceLabel(source: string): string {
  const normalized = source.toLocaleLowerCase('en-US');
  if (normalized.includes('rime')) return 'Rime';
  if (normalized.includes('voice')) return '语音';
  if (normalized.includes('rag')) return 'RAG';
  if (normalized.includes('memory')) return 'Memory';
  if (normalized.includes('assistant') || normalized.includes('model')) return '模型候选';
  return source || 'unknown';
}
