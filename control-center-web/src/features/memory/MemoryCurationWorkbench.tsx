import { ListChecks, RefreshCw, ShieldCheck, Sparkles } from 'lucide-react';
import { useState } from 'react';
import { Button, EmptyState } from '@/components/primitives';
import { useProductIdentity } from '@/features/identity/product-identity';
import {
  ManagementMutationWorkflow,
  parseManagementWorkPreview,
  parseManagementWorkReceipt,
} from '@/features/overview/management-mutation';
import {
  InlineNotice,
  ManagementSection,
  MetricStrip,
  QueryState,
  StatusBadge,
  arrayRecords,
  asRecord,
  booleanValue,
  numberValue,
  publicErrorText,
  stringValue,
} from '@/features/overview/management-ui';
import type { JsonValue } from '@/platform/transport';
import { useMemoryCurationQueries } from './api';
import { knowledgeMutationPathIds, useKnowledgeMutationBoundary } from './knowledge-workbench-api';

export function MemoryCurationWorkbench({ enabled }: { enabled: boolean }) {
  const identity = useProductIdentity();
  const queries = useMemoryCurationQueries(enabled);
  const mutationBoundary = useKnowledgeMutationBoundary();
  const [editingDiffId, setEditingDiffId] = useState(0);
  const [editError, setEditError] = useState('');
  const statusPayload = asRecord(queries.status.data);
  const compileState = asRecord(statusPayload.compileState);
  const payload = asRecord(queries.run.data);
  const run = asRecord(payload.run);
  const changes = arrayRecords(run.changes);
  const runId = stringValue(run.runId, queries.runId);
  const runStatus = stringValue(run.status);
  const stale = booleanValue(payload.stale);
  const selectedCount = changes.filter((change) => booleanValue(change.selected)).length;
  const rejectedCount = changes.length - selectedCount;
  const error = (queries.status.error ?? queries.run.error) as Error | null;
  const pending = queries.status.isPending || (Boolean(queries.runId) && queries.run.isPending);
  const draftKey = `${runId}:${changes.map((change) => `${numberValue(change.diffId)}:${booleanValue(change.selected)}`).join(',')}`;
  const applyBlockedReason = !runId
    ? `等待自动整理，或让${identity.assistantName}现在准备一份草案。`
    : stale
      ? '这份草案基于旧数据，请重新生成后再应用。'
      : runStatus !== 'draft'
        ? '当前整理批次已经结束，不能重复应用。'
        : !booleanValue(payload.canApply)
          ? '当前草案不能完成审核，请刷新后重试。'
          : '';
  const refresh = () => void Promise.all([
    queries.status.refetch(),
    ...(queries.runId ? [queries.run.refetch()] : []),
  ]);

  return (
    <div className="memory-curation">
      <div className="memory-curation__header">
        <div>
          <h2>记忆整理审核</h2>
          <span>系统会先整理成一条条可审阅的事实草案；这里只逐项选择和确认写入。</span>
        </div>
        <div className="memory-curation__actions">
          <Button leadingIcon={<Sparkles size={15} />} onClick={handoffToAgent} size="small">让{identity.assistantName}整理</Button>
          <Button aria-label="刷新记忆整理草案" leadingIcon={<RefreshCw size={15} />} loading={queries.status.isFetching || queries.run.isFetching} onClick={refresh} size="small" variant="quiet">刷新</Button>
        </div>
      </div>

      <QueryState error={error} isPending={pending} onRetry={refresh}>
        <ManagementSection title="当前草案" description="整理任务不会直接改库；你选择的项目会在最终确认后一次写入。">
          <InlineNotice title="自动草案" tone={booleanValue(statusPayload.due) ? 'warning' : 'info'}>
            {numberValue(compileState.undraftedEventCount)} 条新证据尚未生成草案；达到 50 条、输入空闲 20 分钟或每日周期时自动整理，正式记忆始终需要你的确认。
          </InlineNotice>
          {runId ? (
            <>
              <MetricStrip items={[
                { label: '批次状态', value: curationStatusLabel(runStatus, stale), detail: formatCreatedAt(numberValue(run.createdAtMs)), icon: ShieldCheck, tone: runStatus === 'draft' && !stale ? 'warning' : 'success' },
                { label: '建议更新', value: changes.length, detail: `${identity.assistantName}整理结果`, icon: ListChecks },
                { label: '待生成', value: numberValue(compileState.undraftedEventCount), detail: '尚未覆盖的新证据', icon: RefreshCw, tone: numberValue(compileState.undraftedEventCount) ? 'warning' : 'neutral' },
                { label: '已选择', value: selectedCount, detail: '将进入最终预览', icon: ShieldCheck, tone: selectedCount ? 'success' : 'warning' },
                { label: '已排除', value: rejectedCount, detail: '不会写入', icon: ListChecks, tone: 'neutral' },
              ]} />
              <InlineNotice title={stale ? '草案已过期' : '审核边界'} tone={stale ? 'warning' : 'info'}>
                {stale
                  ? '记忆库在草案生成后已有变化，请重新整理，避免覆盖新内容。'
                  : '勾选只改变草案，不改变正式记忆；最终写入仍需预览和二次确认。'}
              </InlineNotice>
            </>
          ) : (
            <EmptyState description={`自动整理或${identity.assistantName}生成的去重、合并、标签与归档建议会出现在这里。`} icon={Sparkles} title="还没有整理草案" />
          )}
        </ManagementSection>

        {runId ? (
          <ManagementSection title="逐项选择" description="按内容判断是否更新；不同 App 的输入来源会继续分开保留。" trailing={<StatusBadge label={`${selectedCount} / ${changes.length} 已选择`} tone={selectedCount ? 'success' : 'warning'} />}>
            {editError ? <InlineNotice title="草案更新失败" tone="danger">{editError}</InlineNotice> : null}
            <div className="memory-curation__list" role="list" aria-label="记忆整理建议">
              {changes.map((change) => {
                const diffId = numberValue(change.diffId);
                const selected = booleanValue(change.selected);
                const disabled = stale || runStatus !== 'draft' || editingDiffId === diffId;
                return (
                  <label className="memory-curation__row" data-selected={selected || undefined} key={diffId} role="listitem">
                    <input
                      aria-label={`选择 ${stringValue(change.title, '未命名更新')}`}
                      checked={selected}
                      disabled={disabled}
                      onChange={(event) => void updateSelection(diffId, event.target.checked)}
                      type="checkbox"
                    />
                    <span className="memory-curation__copy">
                      <span className="memory-curation__title">
                        <strong>{stringValue(change.title, '未命名更新')}</strong>
                        <StatusBadge label={diffStatusLabel(stringValue(change.status))} tone={selected ? 'success' : 'neutral'} />
                      </span>
                      <span>{stringValue(change.detail, '这项建议没有补充说明。')}</span>
                      <small>{stringValue(change.operationLabel, operationLabel(stringValue(change.operation)))} · {numberValue(change.sourceCount)} 条来源证据</small>
                    </span>
                  </label>
                );
              })}
            </div>
          </ManagementSection>
        ) : null}

        <ManagementSection title="完成本批审核" description={selectedCount
          ? '正式写入前会再次显示影响范围；应用完成后可以立即撤销本批次。'
          : '全部排除时只结束本批审核，不会改动正式记忆。'}>
          <ManagementMutationWorkflow
            availability={mutationBoundary.databaseAvailability(applyBlockedReason)}
            description={selectedCount
              ? '只应用上方已选择的整理建议，并重建本地检索索引。'
              : '不写入任何建议，只确认本批证据已经审核完成。'}
            draftKey={draftKey}
            mutationKey={['memory', 'curation', runId]}
            onApply={async (preview) => parseManagementWorkReceipt(
              await mutationBoundary.request({
                pathId: knowledgeMutationPathIds.databaseApply,
                body: {
                  runId: preview.context.runId,
                  confirm: 'apply',
                  previewToken: preview.previewToken,
                  payloadSha256: preview.payloadSha256,
                  expectedRuntimeRevision: preview.expectedRuntimeRevision,
                },
              }),
              knowledgeMutationPathIds.databaseApply,
              preview.payloadSha256,
            )}
            onApplied={refresh}
            onPreview={async () => {
              const context: Record<string, JsonValue> = { runId };
              return parseManagementWorkPreview(
                await mutationBoundary.request({
                  pathId: knowledgeMutationPathIds.databaseApplyPreview,
                  body: context,
                }),
                knowledgeMutationPathIds.databaseApply,
                context,
              );
            }}
            onRollback={async (receipt, preview) => parseManagementWorkReceipt(
              await mutationBoundary.request({
                pathId: knowledgeMutationPathIds.databaseRollback,
                body: {
                  runId: preview.context.runId,
                  confirm: 'rollback',
                  receiptId: receipt.receiptId,
                  rollbackToken: receipt.rollbackToken,
                  payloadSha256: receipt.payloadSha256,
                },
              }),
              knowledgeMutationPathIds.databaseRollback,
              preview.payloadSha256,
            )}
            onRolledBack={refresh}
            risk="R2"
            title={selectedCount ? '确认写入记忆' : '确认排除本批建议'}
          />
        </ManagementSection>
      </QueryState>
    </div>
  );

  async function updateSelection(diffId: number, selected: boolean) {
    setEditingDiffId(diffId);
    setEditError('');
    try {
      await mutationBoundary.request({
        pathId: knowledgeMutationPathIds.databaseDraftEdit,
        body: { runId, diffId, selected },
      });
      await queries.run.refetch();
    } catch (cause) {
      setEditError(publicErrorText(cause, '未能保存这项选择，正式记忆没有变化。'));
    } finally {
      setEditingDiffId(0);
    }
  }

  function handoffToAgent() {
    const prompt = '请调用 memory Tool 的 curation_prepare 操作，以 conservative 策略增量整理当前记忆。只生成一个 Atom-first 可审阅草案并返回 runId，不要逐条复述数据库操作，也不要直接应用。';
    window.location.hash = `/agent?draft=${encodeURIComponent(prompt)}`;
  }
}

function curationStatusLabel(status: string, stale: boolean): string {
  if (stale) return '需要重建';
  return {
    draft: '等待审核',
    applied: '已应用',
    partial: '部分应用',
    rolled_back: '已撤销',
    superseded: '已被替代',
    dismissed: '已全部排除',
    empty: '无需更新',
  }[status] ?? '暂无状态';
}

function diffStatusLabel(status: string): string {
  return {
    pending: '待审核',
    approved: '已选择',
    rejected: '已排除',
    applied: '已应用',
    rolled_back: '已撤销',
  }[status] ?? '未知';
}

function operationLabel(operation: string): string {
  return {
    upsert_semantic_group: '更新分组',
    upsert_semantic_tag: '更新标签',
    upsert_memory_book: '更新长期主题',
    upsert_memory_atom: '更新一条事实',
    upsert_tag_edge: '更新标签关系',
    merge_semantic_tag: '合并标签',
    add_phrase_candidate: '添加短语候选',
    add_negative_phrase: '添加负反馈',
    supersede_memory: '替代旧记忆',
  }[operation] ?? '整理记忆';
}

function formatCreatedAt(value: number): string {
  if (!value) return '尚未生成';
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(value);
}
