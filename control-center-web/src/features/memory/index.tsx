import { Archive, BookOpen, BrainCircuit, Database, RefreshCw, Search, Tags } from 'lucide-react';
import { useMemo, useState } from 'react';
import {
  Button,
  EmptyState,
  Field,
  Input,
  SegmentedControl,
  Tabs as ViewTabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@/components/primitives';
import { useMemoryQueries, type MemoryKind } from './api';
import { MemoryRelations } from './MemoryRelations';
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
  numberValue,
  stringValue,
} from '@/features/overview/management-ui';
import './memory.css';

const kinds = [
  { value: 'books', label: '主题书' },
  { value: 'atoms', label: '原子' },
  { value: 'tags', label: '标签' },
  { value: 'phrases', label: '短语' },
  { value: 'groups', label: 'Group' },
  { value: 'negative', label: '负反馈' },
] as const;

export function MemoryFeature() {
  const [view, setView] = useState<'catalog' | 'relations'>('catalog');
  const [kind, setKind] = useState<MemoryKind>('books');
  const [draftQuery, setDraftQuery] = useState('');
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const { pages, summary } = useMemoryQueries(kind, query, status);
  const summaryPayload = asRecord(summary.data);
  const rows = useMemo(() =>
    (pages.data?.pages ?? []).flatMap((page) => arrayRecords(asRecord(page).items)).map(normalizeMemoryRow),
  [pages.data]);
  const selected = rows.find((row) => stringValue(row.id) === selectedId);
  const error = (pages.error ?? summary.error) as Error | null;
  const pending = pages.isPending || summary.isPending;
  const refresh = () => void Promise.all([pages.refetch(), summary.refetch()]);

  return (
    <ManagementPage
      actions={<Button leadingIcon={<RefreshCw size={15} />} loading={pages.isRefetching} onClick={refresh} size="small">刷新</Button>}
      description="搜索、筛选、编辑、归档并审阅本地记忆。"
      eyebrow="KNOWLEDGE"
      routeId="memory"
      title="记忆"
    >
      <QueryState error={error} isPending={pending} onRetry={refresh}>
        <ManagementSection title="本地 Memory Core">
          <MetricStrip items={[
            { label: '输入事件', value: numberValue(summaryPayload.eventCount), detail: 'source events', icon: Database },
            { label: '记忆项', value: numberValue(summaryPayload.memoryItemCount), detail: 'active + archived', icon: BrainCircuit },
            { label: '主题书', value: numberValue(summaryPayload.memoryBookCount), detail: 'Memory Books', icon: BookOpen },
            { label: '原子', value: numberValue(summaryPayload.memoryAtomCount), detail: 'Memory Atoms', icon: Tags },
            { label: '待编译', value: numberValue(summaryPayload.pendingCompileEvents), detail: 'maintenance queue', icon: Archive, tone: numberValue(summaryPayload.pendingCompileEvents) ? 'warning' : 'success' },
          ]} />
        </ManagementSection>

        <ViewTabs
          className="memory-view-tabs"
          onValueChange={(next) => setView(next === 'relations' ? 'relations' : 'catalog')}
          value={view}
        >
          <TabsList aria-label="记忆视图">
            <TabsTrigger value="catalog">目录</TabsTrigger>
            <TabsTrigger value="relations">关系图</TabsTrigger>
          </TabsList>
          <TabsContent value="catalog">
            <ManagementSection title="记忆目录" description="每次加载最多 50 条，可继续读取下一页。">
              <div className="mgmt-stack">
                <SegmentedControl aria-label="记忆类型" items={kinds} onValueChange={(next) => { setKind(next); setSelectedId(''); }} value={kind} />
                <div className="mgmt-filter-row">
                  <Field htmlFor="memory-search" label="搜索">
                    <Input id="memory-search" onChange={(event) => setDraftQuery(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') setQuery(draftQuery.trim()); }} placeholder="标题、正文或标签" value={draftQuery} />
                  </Field>
                  <Button leadingIcon={<Search size={14} />} onClick={() => setQuery(draftQuery.trim())} size="small">搜索</Button>
                  <label className="ui-field">
                    <span className="ui-field__label">状态</span>
                    <select className="ui-input" onChange={(event) => setStatus(event.target.value)} value={status}>
                      <option value="">全部</option>
                      <option value="active">active</option>
                      <option value="archived">archived</option>
                      <option value="suppressed">suppressed</option>
                    </select>
                  </label>
                </div>
              </div>
              {rows.length ? (
                <>
                  <DataTable caption={`${kind} 记忆分页`} columns={[
                    { key: 'id', label: 'ID', width: '18%' },
                    { key: 'title', label: '标题', width: '24%' },
                    { key: 'detail', label: '内容' },
                    { key: 'source', label: '来源', width: '14%' },
                    { key: 'status', label: '状态', width: '11%' },
                  ]} rows={rows} />
                  <PaginationBar count={rows.length} hasMore={pages.hasNextPage} isFetching={pages.isFetchingNextPage} onLoadMore={() => void pages.fetchNextPage()} />
                </>
              ) : (
                <EmptyState description="当前筛选没有记忆项。" icon={Search} title="没有匹配结果" />
              )}
            </ManagementSection>

            <ManagementSection title="编辑与归档" description="选择条目后预览字段差异与归档影响；当前操作为演练。">
              <div className="mgmt-filter-row">
                <label className="ui-field" style={{ minWidth: 280 }}>
                  <span className="ui-field__label">条目</span>
                  <select className="ui-input" onChange={(event) => setSelectedId(event.target.value)} value={selectedId}>
                    <option value="">请选择</option>
                    {rows.map((row) => <option key={stringValue(row.id)} value={stringValue(row.id)}>{stringValue(row.title, stringValue(row.id))}</option>)}
                  </select>
                </label>
              </div>
              <div className="mgmt-grid-2">
                <WorkflowAction
                  actionId="memory.edit"
                  description="编辑标题、正文、标签、别名或合并目标。"
                  mutationKey={['memory', 'mutation', 'edit']}
                  preview={[`kind：${kind}`, `memoryId：${selectedId || '尚未选择'}`, `当前标题：${stringValue(selected?.title, '尚未选择')}`]}
                  risk="R1"
                  title="保存记忆差异"
                />
                <WorkflowAction
                  actionId="memory.archive"
                  description="归档所选记忆；原始记录与来源关系保留，可回滚。"
                  mutationKey={['memory', 'mutation', 'archive']}
                  preview={[`memoryId：${selectedId || '尚未选择'}`, `当前状态：${stringValue(selected?.status, 'unknown')}`, '归档不会物理删除来源事件。']}
                  risk="R2"
                  title="归档记忆"
                />
              </div>
            </ManagementSection>

            <ManagementSection title="维护草案" description="清理与合并先生成草案，再逐项审阅差异。">
              <InlineNotice title="维护边界" tone="warning">维护只影响已选草案，完成后可查看结果并回滚。</InlineNotice>
              <WorkflowAction
                actionId="memory.maintenance.apply"
                description="应用已审阅的去重、合并、归档或标签关系草案。"
                mutationKey={['memory', 'mutation', 'maintenance']}
                preview={['只应用已批准的差异。', '同时更新来源关系与检索索引。', '完成后提供可回滚收据。']}
                risk="R2"
                title="应用维护草案"
              />
            </ManagementSection>
          </TabsContent>
          <TabsContent value="relations">
            <MemoryRelations enabled={view === 'relations'} />
          </TabsContent>
        </ViewTabs>
      </QueryState>
    </ManagementPage>
  );
}

function normalizeMemoryRow(item: Record<string, unknown>): Record<string, unknown> {
  return {
    ...item,
    id: item.id ?? item.bookId ?? item.atomId ?? item.tagId ?? item.groupId ?? item.phraseId,
    title: item.title ?? item.name ?? item.label ?? item.text ?? item.phrase,
    detail: item.summary ?? item.note ?? item.description ?? item.text ?? item.aliases,
    source: item.source ?? item.sourceType ?? item.project ?? item.kind,
    status: item.status ?? (item.active === false ? 'inactive' : 'active'),
  };
}
