import { useMutation } from '@tanstack/react-query';
import { Check, RotateCcw } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Button, EmptyState } from '@/components/primitives';
import { InlineNotice, StatusBadge, publicErrorText } from '@/features/overview/management-ui';
import type { ControlTransport } from '@/platform/transport';
import {
  applyLexiconReview,
  rollbackLexiconReview,
  type LexiconMutationReceipt,
  type LexiconReview,
} from './api';

type WorkflowStage = 'select' | 'receipt' | 'rolled-back';
type TimedReceipt = LexiconMutationReceipt & { atMs: number };

export function LexiconWorkflow({
  onRefresh,
  review,
  transport,
}: {
  onRefresh: () => void;
  review: LexiconReview;
  transport: ControlTransport;
}) {
  const [stage, setStage] = useState<WorkflowStage>('select');
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(() => defaultSelection(review));
  const [applyReceipt, setApplyReceipt] = useState<TimedReceipt | null>(null);
  const [rollbackReceipt, setRollbackReceipt] = useState<TimedReceipt | null>(null);

  useEffect(() => {
    setStage('select');
    setSelectedKeys(defaultSelection(review));
    setApplyReceipt(null);
    setRollbackReceipt(null);
  }, [review.reviewToken]);

  const selectedEntries = useMemo(
    () => review.entries.filter((entry) => selectedKeys.has(entry.reviewKey)),
    [review.entries, selectedKeys],
  );
  const applyMutation = useMutation({
    mutationKey: ['input-method', 'lexicon', 'apply', review.reviewToken],
    mutationFn: async () => ({
      ...await applyLexiconReview(transport, review, selectedEntries.map((entry) => entry.reviewKey)),
      atMs: Date.now(),
    }),
    onSuccess: (receipt) => {
      setApplyReceipt(receipt);
      setStage('receipt');
    },
  });
  const rollbackMutation = useMutation({
    mutationKey: ['input-method', 'lexicon', 'rollback'],
    mutationFn: async (rollbackId: string) => ({
      ...await rollbackLexiconReview(transport, rollbackId),
      atMs: Date.now(),
    }),
    onSuccess: (receipt) => {
      setRollbackReceipt(receipt);
      setSelectedKeys(defaultSelection(review));
      setStage('rolled-back');
      onRefresh();
    },
  });

  if (!review.applySupported || !review.reviewRequired) {
    return <InlineNotice title="词库写入暂不可用" tone="warning">当前服务不能安全保存审阅后的词条，本页不会提交任何更改。</InlineNotice>;
  }
  if (review.entries.length === 0) {
    return (
      <EmptyState
        description="当前没有待加入用户词库的条目。"
        headingLevel={3}
        icon={Check}
        title="暂无待审词条"
      />
    );
  }

  return (
    <div className="mgmt-stack">
      <div className="mgmt-toolbar">
        <span className="mgmt-muted">待审 {review.entryCount} 条 · 已选 {selectedEntries.length} 条</span>
        {stage === 'select' ? (
          <span className="input-lexicon-review__bulk">
            <Button
              disabled={selectedKeys.size === review.entries.length}
              onClick={() => setSelectedKeys(new Set(review.entries.map((entry) => entry.reviewKey)))}
              size="small"
              variant="quiet"
            >
              全选
            </Button>
            <Button
              onClick={() => setSelectedKeys(defaultSelection(review))}
              size="small"
              variant="quiet"
            >
              恢复默认建议
            </Button>
          </span>
        ) : null}
      </div>

      <InlineNotice title="筛选规则" tone="info">
        {selectionPolicyLabel(review.selectionPolicy)}
        {review.filteredEntryCount ? ` 本轮已拦截 ${review.filteredEntryCount} 条单字、生僻噪声或使用记录不足的候选。` : ''}
      </InlineNotice>

      {stage === 'select' ? (
        <div className="mgmt-list input-lexicon-review__list">
          {review.entries.map((entry) => {
            const detail = reviewEntryDetail(entry);
            const risk = reviewRisk(entry);
            return (
              <label className="mgmt-list__row input-lexicon-review__row" data-input-lexicon-row="true" key={entry.reviewKey}>
                <input
                  aria-label={`选择 ${entry.text}`}
                  checked={selectedKeys.has(entry.reviewKey)}
                  onChange={(event) => setSelectedKeys((current) => toggled(current, entry.reviewKey, event.target.checked))}
                  type="checkbox"
                />
                <span className="mgmt-list__content">
                  <strong title={entry.text}>{entry.text}</strong>
                  <span title={detail}>{detail}</span>
                </span>
                <span className="input-lexicon-review__badges">
                  <StatusBadge label={reviewSourceLabel(entry.reviewSource)} tone="info" />
                  <StatusBadge label={risk.label} tone={risk.tone} />
                </span>
              </label>
            );
          })}
        </div>
      ) : null}

      <div className="mgmt-workflow" data-stage={stage}>
        <div className="mgmt-workflow__heading">
          <div>
            <strong>加入所选词条</strong>
            <p>保存后仍需重载输入法，并通过实际选词检查效果。</p>
          </div>
          {stage === 'select' ? (
            <Button
              disabled={selectedEntries.length === 0}
              loading={applyMutation.isPending}
              onClick={() => applyMutation.mutate()}
              size="small"
              variant="primary"
            >
              加入所选词条
            </Button>
          ) : null}
        </div>

        {applyMutation.error ? <InlineNotice title="更新失败" tone="danger">{publicErrorText(applyMutation.error)}</InlineNotice> : null}

        {stage === 'receipt' && applyReceipt ? (
          <>
            <LexiconReceipt receipt={applyReceipt} rolledBack={false} />
            <InlineNotice title="尚未生效" tone="warning">词条已经加入用户词库，但输入法尚未重载。请在重载后用实际输入与选词结果确认效果。</InlineNotice>
            <div className="mgmt-workflow__buttons">
              <Button leadingIcon={<RotateCcw size={14} />} loading={rollbackMutation.isPending} onClick={() => rollbackMutation.mutate(applyReceipt.rollbackId)} size="small">撤销这次更新</Button>
            </div>
          </>
        ) : null}

        {rollbackMutation.error ? <InlineNotice title="撤销失败" tone="danger">{publicErrorText(rollbackMutation.error)}</InlineNotice> : null}

        {stage === 'rolled-back' && rollbackReceipt ? (
          <>
            <LexiconReceipt receipt={rollbackReceipt} rolledBack />
            <InlineNotice title="撤销尚未生效" tone="warning">词库已经恢复，但重载输入法尚未完成。请在重载后用实际选词结果确认。</InlineNotice>
            <div className="mgmt-workflow__buttons">
              <Button onClick={() => setStage('select')} size="small" variant="quiet">返回审阅</Button>
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}

function LexiconReceipt({ receipt, rolledBack }: { receipt: TimedReceipt; rolledBack: boolean }) {
  return (
    <div className="mgmt-workflow__receipt">
      <div>
        <StatusBadge label={rolledBack ? '已撤销 · 等待重载' : '已加入 · 等待重载'} tone="warning" />
        <strong>{rolledBack ? '词库更新已撤销' : '词条已加入用户词库'}</strong>
        <span>{rolledBack ? '重载输入法后恢复生效' : `已加入 ${receipt.entryCount} 条 · 可以撤销`}</span>
        <time>{new Date(receipt.atMs).toLocaleString('zh-CN', { hour12: false })}</time>
      </div>
    </div>
  );
}

/* 默认勾选跟随后端的真实建议：重复使用的真实选词反馈默认勾选，
 * 模型批量建议保持未选，等待人工确认。 */
function defaultSelection(review: LexiconReview): Set<string> {
  return new Set(review.entries
    .filter((entry) => entry.selected || entry.defaultSelected)
    .map((entry) => entry.reviewKey));
}

function toggled(current: Set<string>, key: string, selected: boolean): Set<string> {
  const next = new Set(current);
  if (selected) next.add(key);
  else next.delete(key);
  return next;
}

function selectionPolicyLabel(value?: string): string {
  return ({
    review_required: '重复使用的常用词才进入审阅；系统建议默认不勾选。',
    repeated_usage: '重复使用的常用词才进入审阅；系统建议默认不勾选。',
    manual_review: '每条建议都需要你审阅后才能加入词库。',
  } as Record<string, string>)[value ?? ''] ?? '重复使用的常用词才进入审阅；系统建议默认不勾选。';
}

function reviewSourceLabel(value: string): string {
  return ({ usage: '输入记录', local_feedback: '本机选词反馈', manual: '手动添加', imported: '已导入' } as Record<string, string>)[value] ?? '待审词条';
}

/* riskLabel 是后端给出的真实归类：模型批量建议必须与真实选词反馈在
 * 视觉上分开，缺失时如实说“风险未标注”，不冒充已判定。 */
function reviewRisk(entry: LexiconReview['entries'][number]): {
  label: string;
  tone: 'success' | 'warning' | 'neutral';
} {
  if (!entry.riskLabel) return { label: '风险未标注', tone: 'neutral' };
  if (entry.riskLabel.includes('模型建议')) return { label: entry.riskLabel, tone: 'warning' };
  if (entry.riskLabel.includes('真实选词')) return { label: entry.riskLabel, tone: 'success' };
  return { label: entry.riskLabel, tone: 'neutral' };
}

function reviewEntryDetail(entry: LexiconReview['entries'][number]): string {
  return `${entry.pinyin || '无拼音'} · 被采用 ${entry.positiveCount} 次 · 被跳过 ${entry.negativeCount} 次`;
}
