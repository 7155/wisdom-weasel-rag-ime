import {
  Check,
  Clock3,
  Copy,
  Eye,
  History,
  MessageSquareText,
  RefreshCw,
  Search,
  ShieldCheck,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  EmptyState,
  Field,
  Input,
  Select,
} from '@/components/primitives';
import { writeClipboardText } from '@/platform/clipboard';
import {
  historyMutationPathIds,
  useHistoryDetail,
  useHistoryMutationBoundary,
  useHistoryPages,
} from './api';
import {
  InlineNotice,
  ManagementPage,
  ManagementSection,
  MetricStrip,
  PaginationBar,
  QueryState,
  arrayRecords,
  asRecord,
  formatTime,
  numberValue,
  stringValue,
} from '@/features/overview/management-ui';
import {
  ManagementMutationWorkflow,
  UnsupportedWorkflow,
  parseManagementWorkPreview,
  parseManagementWorkReceipt,
} from '@/features/overview/management-mutation';
import './history.css';

export function HistoryFeature() {
  const [draftQuery, setDraftQuery] = useState('');
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const [detailEventId, setDetailEventId] = useState<number | null>(null);
  const { pages } = useHistoryPages(query, filter);
  const mutationBoundary = useHistoryMutationBoundary();
  const rows = useMemo(() => (pages.data?.pages ?? [])
    .flatMap((page) => arrayRecords(asRecord(page).items))
    .map((item) => ({
      ...item,
      created: formatTime(item.createdAtMs),
      sourceLabel: sourceLabel(stringValue(item.source), stringValue(item.sourceCategory)),
      text: stringValue(item.textPreview, `已脱敏 · ${numberValue(item.textChars)} 字`),
    } as Record<string, unknown>)), [pages.data]);
  const sources = new Set(rows.map((row) => stringValue(row.source)).filter(Boolean));
  const rawRuntimeRevision = asRecord(pages.data?.pages[0]).runtimeRevision;
  const runtimeRevision = typeof rawRuntimeRevision === 'number'
    && Number.isInteger(rawRuntimeRevision)
    && rawRuntimeRevision >= 0
    ? rawRuntimeRevision
    : null;
  const selectedEventId = Number(selectedId);
  const tombstoneDraft = {
    eventId: selectedEventId,
    reason: 'control-center-history',
  };
  const openDetail = (row: Record<string, unknown>) => {
    const eventId = numberValue(row.id);
    if (!Number.isInteger(eventId) || eventId <= 0) return;
    setSelectedId(String(eventId));
    setDetailEventId(eventId);
  };

  return (
    <ManagementPage
      actions={<Button leadingIcon={<RefreshCw size={15} />} loading={pages.isRefetching} onClick={() => void pages.refetch()} size="small">刷新</Button>}
      description="查看脱敏的输入记录、候选来源与反馈。"
      eyebrow="记录"
      routeId="history"
      title="输入历史"
    >
      <QueryState error={pages.error as Error | null} isPending={pages.isPending} onRetry={() => void pages.refetch()}>
        <ManagementSection title="已加载快照">
          <MetricStrip items={[
            { label: '记录', value: rows.length, detail: '当前分页窗口', icon: History },
            { label: '来源', value: sources.size, detail: '候选来源', icon: MessageSquareText },
            { label: '原文保护', value: '仅摘要', detail: '脱敏显示', icon: ShieldCheck, tone: 'success' },
            { label: '更多记录', value: pages.hasNextPage ? '可继续加载' : '已到末尾', detail: '分页读取', icon: Clock3, tone: pages.hasNextPage ? 'info' : 'neutral' },
          ]} />
          <InlineNotice title="隐私" tone="info">列表只显示脱敏摘要；完整输入仅在你主动打开详情时读取。</InlineNotice>
        </ManagementSection>

        <ManagementSection title="筛选与分页">
          <div aria-label="筛选输入历史" className="history-filter-toolbar" role="search">
            <Field className="history-filter-toolbar__search" htmlFor="history-search" label="搜索">
              <Input id="history-search" onChange={(event) => setDraftQuery(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') setQuery(draftQuery.trim()); }} placeholder="文本、应用或项目" value={draftQuery} />
            </Field>
            <Button className="history-filter-toolbar__submit" leadingIcon={<Search size={14} />} onClick={() => setQuery(draftQuery.trim())} size="small">搜索</Button>
            <Field className="history-filter-toolbar__source" htmlFor="history-source-filter" label="来源">
              <Select id="history-source-filter" onValueChange={setFilter} options={[
                { value: '', label: '全部来源' },
                { value: 'rime_commit', label: '输入法' },
                { value: 'assistant_candidate', label: '模型候选' },
                { value: 'voice', label: '语音' },
                { value: 'import', label: '导入' },
              ]} value={filter} />
            </Field>
          </div>
          {rows.length ? (
            <>
              <HistoryTable onOpen={openDetail} rows={rows} />
              <PaginationBar count={rows.length} hasMore={pages.hasNextPage} isFetching={pages.isFetchingNextPage} onLoadMore={() => void pages.fetchNextPage()} />
            </>
          ) : <EmptyState description="当前筛选没有历史记录。" icon={Search} title="历史为空" />}
        </ManagementSection>

        <ManagementSection title="反馈与移除" description="选择已加载记录后，所有写动作都先预览影响并保留可撤销记录。">
          <Field htmlFor="history-record" label="记录" style={{ maxWidth: 420 }}>
            <Select id="history-record" onValueChange={setSelectedId} options={[
              { value: '', label: '请选择' },
              ...rows.map((row) => ({ value: stringValue(row.id), label: `${stringValue(row.created)} · ${stringValue(row.text)}` })),
            ]} value={selectedId} />
          </Field>
          <div className="mgmt-grid-2" style={{ marginTop: 12 }}>
            <UnsupportedWorkflow
              description="为所选候选提交负反馈，并保留来源信息。"
              reason="当前记录没有关联到可验证的候选反馈信息，因此不会提供无法生效的反馈按钮。"
              risk="R1"
              title="记录负反馈"
            />
            <ManagementMutationWorkflow
              availability={mutationBoundary.availability(
                !Number.isInteger(selectedEventId) || selectedEventId <= 0
                  ? '先从已加载记录中选择一项。'
                  : runtimeRevision === null
                    ? '当前历史状态尚未同步，请刷新后重试。'
                    : '',
              )}
              description="从后续召回中隐藏所选记录，原始记录仍保留。"
              draftKey={JSON.stringify(tombstoneDraft)}
              mutationKey={['history', 'mutation', 'tombstone']}
              onApply={async (preview) => parseManagementWorkReceipt(
                await mutationBoundary.request({
                  pathId: historyMutationPathIds.apply,
                  body: {
                    ...preview.context,
                    expectedRuntimeRevision: preview.expectedRuntimeRevision,
                    previewToken: preview.previewToken,
                    payloadSha256: preview.payloadSha256,
                    confirmText: preview.requiredConfirm,
                  },
                }),
                historyMutationPathIds.apply,
                preview.payloadSha256,
              )}
              onApplied={() => {
                setSelectedId('');
                void pages.refetch();
              }}
              onPreview={async () => {
                if (runtimeRevision === null) throw new Error('当前历史状态尚未同步，请刷新后重试。');
                return parseManagementWorkPreview(
                  await mutationBoundary.request({
                    pathId: historyMutationPathIds.preview,
                    body: {
                      ...tombstoneDraft,
                      expectedRuntimeRevision: runtimeRevision,
                    },
                  }),
                  historyMutationPathIds.apply,
                  tombstoneDraft,
                );
              }}
              onRollback={async (receipt, preview) => parseManagementWorkReceipt(
                await mutationBoundary.request({
                  pathId: historyMutationPathIds.rollback,
                  body: {
                    receiptId: receipt.receiptId,
                    rollbackToken: receipt.rollbackToken,
                    payloadSha256: receipt.payloadSha256,
                    confirmText: 'rollback',
                  },
                }),
                historyMutationPathIds.rollback,
                preview.payloadSha256,
              )}
              onRolledBack={() => void pages.refetch()}
              risk="R2"
              title="隐藏记录"
            />
          </div>
        </ManagementSection>
      </QueryState>
      <HistoryDetailDialog eventId={detailEventId} onOpenChange={(open) => { if (!open) setDetailEventId(null); }} />
    </ManagementPage>
  );
}

function HistoryTable({
  rows,
  onOpen,
}: {
  rows: readonly Record<string, unknown>[];
  onOpen: (row: Record<string, unknown>) => void;
}) {
  return (
    <div className="history-table-wrap" tabIndex={0}>
      <table className="history-table">
        <caption>输入历史分页；选择任意记录查看完整详情</caption>
        <thead><tr><th scope="col">时间</th><th scope="col">来源</th><th scope="col">文本预览</th><th scope="col">应用</th><th scope="col">项目</th><th scope="col"><span className="history-sr-only">操作</span></th></tr></thead>
        <tbody>
          {rows.map((row) => {
            const id = stringValue(row.id);
            const label = `查看 ${stringValue(row.created, '这条记录')} 的输入详情`;
            return (
              <tr
                aria-label={label}
                key={id}
                onClick={() => onOpen(row)}
                onKeyDown={(event) => {
                  if (event.key !== 'Enter' && event.key !== ' ') return;
                  event.preventDefault();
                  onOpen(row);
                }}
                tabIndex={0}
              >
                <td>{stringValue(row.created, '未记录')}</td>
                <td>{stringValue(row.sourceLabel, '未知来源')}</td>
                <td className="history-table__preview">{stringValue(row.text, '没有可显示的摘要')}</td>
                <td>{stringValue(row.app, '未记录')}</td>
                <td>{projectLabel(stringValue(row.project))}</td>
                <td><button aria-label={label} className="history-table__open" onClick={(event) => { event.stopPropagation(); onOpen(row); }} type="button"><Eye aria-hidden="true" size={15} /></button></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function HistoryDetailDialog({
  eventId,
  onOpenChange,
}: {
  eventId: number | null;
  onOpenChange: (open: boolean) => void;
}) {
  const detail = useHistoryDetail(eventId);
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const response = asRecord(detail.data);
  const item = asRecord(response.item);
  const feedback = asRecord(item.feedback);
  const text = stringValue(item.text);
  const candidateRank = item.candidateRank === null ? 0 : numberValue(item.candidateRank);
  const hasFeedback = feedback.available === true;

  const copyText = async () => {
    if (!text) return;
    try {
      await writeClipboardText(text);
      setCopyState('copied');
    } catch {
      setCopyState('failed');
    }
  };

  return (
    <Dialog onOpenChange={(open) => { setCopyState('idle'); onOpenChange(open); }} open={eventId !== null}>
      <DialogContent className="history-detail-dialog">
        <DialogHeader>
          <DialogTitle>输入详情</DialogTitle>
          <DialogDescription>{response.ok === true ? `${formatTime(item.createdAtMs)} 保存的内容` : '读取已保存的完整输入内容'}</DialogDescription>
        </DialogHeader>
        {detail.isPending ? <p className="history-detail__state" role="status">正在读取详情...</p> : null}
        {detail.error ? <p className="history-detail__state history-detail__state--error" role="alert">详情读取失败。请关闭后重试。</p> : null}
        {!detail.isPending && !detail.error && response.ok !== true ? <p className="history-detail__state history-detail__state--error" role="alert">这条记录已不存在或当前不可读取。</p> : null}
        {response.ok === true ? (
          <div className="history-detail__body">
            <dl className="history-detail__facts">
              <DetailFact label="时间" value={formatTime(item.createdAtMs)} />
              <DetailFact label="来源" value={sourceLabel(stringValue(item.source), stringValue(item.sourceCategory))} />
              <DetailFact label="应用" value={applicationLabel(stringValue(item.app))} />
              <DetailFact label="项目" value={projectLabel(stringValue(item.project))} />
              <DetailFact label="识别或候选服务" value={providerLabel(stringValue(item.provider))} />
              <DetailFact label="候选位置" value={candidateRank > 0 ? `第 ${candidateRank} 位` : '未记录'} />
              <DetailFact label="记录状态" value={stringValue(item.status) === 'hidden' ? '已隐藏' : '可参与后续召回'} />
              <DetailFact label="上下文范围" value={groupLevelLabel(stringValue(item.groupLevel))} />
            </dl>
            <section aria-labelledby="history-detail-text" className="history-detail__text">
              <div className="history-detail__section-heading">
                <div><h3 id="history-detail-text">完整文本</h3><small>{numberValue(item.textChars)} 字</small></div>
                <Button leadingIcon={copyState === 'copied' ? <Check size={14} /> : <Copy size={14} />} onClick={() => void copyText()} size="small" variant="quiet">{copyState === 'copied' ? '已复制' : '复制全文'}</Button>
              </div>
              <pre tabIndex={0}>{text}</pre>
              {copyState === 'failed' ? <p className="history-detail__copy-error" role="status">复制失败，可直接选择上方全文复制。</p> : null}
            </section>
            <section aria-labelledby="history-detail-feedback" className="history-detail__feedback">
              <div className="history-detail__section-heading"><div><h3 id="history-detail-feedback">反馈与状态</h3><small>服务端已保存的真实状态</small></div></div>
              {hasFeedback ? (
                <dl className="history-detail__feedback-grid">
                  <DetailFact label="采用" value={`${numberValue(feedback.acceptedCount)} 次`} />
                  <DetailFact label="跳过" value={`${numberValue(feedback.skippedCount)} 次`} />
                  <DetailFact label="置顶" value={feedback.pinned === true ? '是' : '否'} />
                  <DetailFact label="降低排序" value={feedback.downranked === true ? '是' : '否'} />
                  <DetailFact label="最近动作" value={latestActionLabel(stringValue(feedback.latestAction))} />
                  <DetailFact label="状态更新时间" value={formatTime(feedback.updatedAtMs)} />
                </dl>
              ) : <p className="history-detail__empty">这条记录没有关联到可验证的反馈状态。</p>}
            </section>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function DetailFact({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value || '未记录'}</dd></div>;
}

function sourceLabel(source: string, category = ''): string {
  if (category === 'rime_commit') return '输入法';
  if (category === 'voice') return '语音';
  if (category === 'assistant_candidate') return '模型候选';
  if (category === 'import') return '导入';
  const normalized = source.toLocaleLowerCase('en-US');
  if (normalized.includes('rime')) return '输入法';
  if (normalized.includes('voice')) return '语音';
  if (normalized.includes('rag')) return '知识检索';
  if (normalized.includes('memory')) return '个人记忆';
  if (normalized.includes('assistant') || normalized.includes('model')) return '模型候选';
  return source ? '其他来源' : '未知来源';
}

function providerLabel(provider: string): string {
  const normalized = provider.toLocaleLowerCase('en-US');
  if (!provider || normalized === 'local') return '本机';
  if (normalized.includes('volc') || normalized.includes('doubao')) return '豆包语音';
  if (normalized.includes('voice') || normalized.includes('asr')) return '流式语音识别';
  if (normalized.includes('rime')) return '输入法';
  return '其他识别服务';
}

function applicationLabel(app: string): string {
  const normalized = app.toLocaleLowerCase('en-US');
  if (!app) return '未记录';
  if (normalized.includes('openai.codex')) return 'Codex';
  if (normalized.includes('ghostty')) return 'Ghostty';
  if (normalized.includes('squirrel') || normalized.includes('rime')) return '输入法';
  if (/^[\p{L}\p{N} _+-]{1,48}$/u.test(app)) return app;
  return '其他应用';
}

function projectLabel(project: string): string {
  if (!project) return '未记录';
  if (project === 'wisdom-weasel-rag-ime') return '智鼬输入法';
  if (/^[\p{L}\p{N} _+\u00b7-]{1,48}$/u.test(project) && /[\u3400-\u9fff]/u.test(project)) return project;
  return '本机项目';
}

function groupLevelLabel(level: string): string {
  if (level === 'document') return '当前文档';
  if (level === 'project') return '当前项目';
  if (level === 'app') return '当前应用';
  if (level === 'global') return '全部应用';
  return level ? '已分组' : '未记录';
}

function latestActionLabel(action: string): string {
  if (!action) return '无';
  if (action === 'accept') return '采用';
  if (action === 'skip') return '跳过';
  if (action === 'pin') return '置顶';
  if (action === 'unpin') return '取消置顶';
  if (action === 'downrank') return '降低排序';
  if (action === 'restore') return '恢复';
  if (action === 'hide' || action === 'delete') return '隐藏';
  return '已记录反馈';
}
