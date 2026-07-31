import { useMutation } from '@tanstack/react-query';
import { Check, CircleDashed, RefreshCw, RotateCcw } from 'lucide-react';
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

type WorkflowStage = 'select' | 'preview' | 'confirm' | 'receipt' | 'rolled-back';
type TimedReceipt = LexiconMutationReceipt & { atMs: number };

export function LexiconWorkflow({
  isFetching,
  onRefresh,
  review,
  transport,
}: {
  isFetching: boolean;
  onRefresh: () => void;
  review: LexiconReview;
  transport: ControlTransport;
}) {
  const [stage, setStage] = useState<WorkflowStage>('select');
  const [approved, setApproved] = useState(false);
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(() => defaultSelection(review));
  const [applyReceipt, setApplyReceipt] = useState<TimedReceipt | null>(null);
  const [rollbackReceipt, setRollbackReceipt] = useState<TimedReceipt | null>(null);

  useEffect(() => {
    setStage('select');
    setApproved(false);
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
    return <InlineNotice title="词库写入未开放" tone="warning">服务端没有开放受审词库写入，本页不会提交变更。</InlineNotice>;
  }
  if (review.entries.length === 0) {
    return (
      <EmptyState
        action={<Button leadingIcon={<RefreshCw size={15} />} loading={isFetching} onClick={onRefresh} size="small">刷新审阅</Button>}
        description="当前没有待加入用户词库的条目。"
        icon={Check}
        title="暂无待审词条"
      />
    );
  }

  const steps = [
    { id: 'preview', label: '核对词条' },
    { id: 'confirm', label: '确认' },
    { id: 'receipt', label: '完成' },
    { id: 'rolled-back', label: '撤销' },
  ] as const;
  const stageIndex = stage === 'select' ? -1 : steps.findIndex((step) => step.id === stage);

  return (
    <div className="mgmt-stack">
      <div className="mgmt-toolbar">
        <span className="mgmt-muted">待审 {review.entryCount} 条 · 已选 {selectedEntries.length} 条</span>
        <Button leadingIcon={<RefreshCw size={15} />} loading={isFetching} onClick={onRefresh} size="small">刷新审阅</Button>
      </div>

      <InlineNotice title="常用词质量门" tone="info">
        {selectionPolicyLabel(review.selectionPolicy)}
        {review.filteredEntryCount ? ` 本轮已拦截 ${review.filteredEntryCount} 条单字、生僻噪声或证据不足的候选。` : ''}
      </InlineNotice>

      {stage === 'select' ? (
        <div className="mgmt-list">
          {review.entries.map((entry) => (
            <label className="mgmt-list__row" key={entry.reviewKey}>
              <input
                aria-label={`选择 ${entry.text}`}
                checked={selectedKeys.has(entry.reviewKey)}
                onChange={(event) => setSelectedKeys((current) => toggled(current, entry.reviewKey, event.target.checked))}
                type="checkbox"
              />
              <span className="mgmt-list__content">
                <strong>{entry.text}</strong>
                <span>{entry.pinyin || '无拼音'} · 正向 {entry.positiveCount} · 负向 {entry.negativeCount} · {entry.riskLabel || '待人工确认'}</span>
              </span>
              <StatusBadge label={reviewSourceLabel(entry.reviewSource)} tone="info" />
            </label>
          ))}
        </div>
      ) : null}

      <div className="mgmt-workflow" data-stage={stage}>
        <div className="mgmt-workflow__heading">
          <div>
            <span className="mgmt-workflow__risk">需要确认</span>
            <strong>加入已审词条</strong>
            <p>把所选词条加入用户词库；重载输入法后生效。</p>
          </div>
          {stage === 'select' ? (
            <Button disabled={selectedEntries.length === 0} onClick={() => setStage('preview')} size="small">查看已选词条</Button>
          ) : null}
        </div>

        {stage !== 'select' ? (
          <ol aria-label="词库更新进度" className="mgmt-workflow__steps">
            {steps.map((step, index) => (
              <li data-state={index < stageIndex ? 'complete' : index === stageIndex ? 'current' : 'pending'} key={step.id}>
                {index < stageIndex ? <Check size={13} /> : index === stageIndex ? <CircleDashed size={13} /> : <i />}
                {step.label}
              </li>
            ))}
          </ol>
        ) : null}

        {stage === 'preview' ? (
          <div className="mgmt-workflow__panel">
            <strong>本次将写入的词条</strong>
            <ul>{selectedEntries.map((entry) => <li key={entry.reviewKey}>{entry.text} · {entry.pinyin || '无拼音'}</li>)}</ul>
            <div className="mgmt-workflow__binding">
              <span>已选 {selectedEntries.length} 条</span>
              <span>确认后只更新上方这些词条</span>
            </div>
            <InlineNotice title="生效状态" tone="warning">更新后还需重载输入法，并通过实际选词确认效果。</InlineNotice>
            <div className="mgmt-workflow__buttons">
              <Button onClick={() => setStage('select')} size="small" variant="quiet">返回选择</Button>
              <Button onClick={() => { setApproved(false); setStage('confirm'); }} size="small" variant="primary">确认这些词条</Button>
            </div>
          </div>
        ) : null}

        {stage === 'confirm' ? (
          <div className="mgmt-workflow__panel">
            <strong>确认本次词条</strong>
            <label className="mgmt-workflow__confirm">
              <input checked={approved} onChange={(event) => setApproved(event.target.checked)} type="checkbox" />
              <span>只加入上方 {selectedEntries.length} 条词条</span>
            </label>
            <div className="mgmt-workflow__buttons">
              <Button onClick={() => setStage('preview')} size="small" variant="quiet">返回查看</Button>
              <Button disabled={!approved} loading={applyMutation.isPending} onClick={() => applyMutation.mutate()} size="small" variant="primary">确认加入词库</Button>
            </div>
          </div>
        ) : null}

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

function defaultSelection(review: LexiconReview): Set<string> {
  return new Set(review.entries.filter((entry) => entry.selected).map((entry) => entry.reviewKey));
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
