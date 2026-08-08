import {
  ArrowLeft,
  ChevronRight,
  EyeOff,
  Fingerprint,
  GitBranch,
  LoaderCircle,
  ShieldAlert,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/primitives';
import {
  InlineNotice,
  StatusBadge,
  publicErrorText,
} from '@/features/overview/management-ui';
import { useMemoryReference, type MemoryReferenceKind } from './api';
import type { MemoryReferenceV1 } from '@/contracts/generated/memory-reference.v1';

export interface MemoryReferenceSelection {
  kind: MemoryReferenceKind;
  referenceId: string;
  label?: string;
}

interface MemoryReferenceDialogProps extends MemoryReferenceSelection {
  onOpenChange: (open: boolean) => void;
}

const maximumReferenceDepth = 6;

export function MemoryReferenceDialog({
  kind,
  label = '',
  onOpenChange,
  referenceId,
}: MemoryReferenceDialogProps) {
  const root = useMemo<MemoryReferenceSelection>(
    () => ({ kind, referenceId, label }),
    [kind, label, referenceId],
  );
  const [stack, setStack] = useState<MemoryReferenceSelection[]>(referenceId ? [root] : []);

  useEffect(() => {
    setStack(referenceId ? [root] : []);
  }, [referenceId, root]);

  const current = stack[stack.length - 1] ?? root;
  const query = useMemoryReference(current.kind, current.referenceId, Boolean(referenceId));
  const payload = query.data;
  const refetch = query.refetch;
  const item = payload?.item;
  const source = payload?.source;
  const resolvedReference = item && source ? { item, source } : undefined;
  const references: MemoryReferenceSelection[] = (payload?.evidenceRefs ?? []).map((reference) => ({
    kind: reference.referenceKind,
    referenceId: reference.referenceId,
    ...(reference.label ? { label: reference.label } : {}),
  }));
  const sourceContext = item?.sourceContext;
  const sourceContextAvailable = item?.sourceContextAvailable === true && Boolean(sourceContext);
  const sourceContextRedacted = sourceContext?.redacted === true;
  const disposition = item?.status ?? '';
  const redacted = item?.sensitive === true;
  const forgotten = ['not_for_memory', 'expired', 'tombstoned', 'forgotten'].includes(disposition);
  const title = item?.title || item?.textPreview || item?.text || current.label || current.referenceId;
  const content = redacted ? '' : item?.detail || item?.summary || item?.text || '';
  const currentKey = referenceKey(current);
  const visited = new Set(stack.map(referenceKey));

  function openReference(next: MemoryReferenceSelection) {
    const nextKey = referenceKey(next);
    if (visited.has(nextKey) || stack.length >= maximumReferenceDepth) return;
    setStack((currentStack) => [...currentStack, next]);
  }

  return (
    <Dialog open={Boolean(referenceId)} onOpenChange={onOpenChange}>
      <DialogContent className="memory-reference-dialog">
        <DialogHeader>
          <DialogTitle>{title || '记忆引用'}</DialogTitle>
          <DialogDescription>
            {referenceKindLabel(current.kind)} · {current.referenceId}
          </DialogDescription>
        </DialogHeader>

        {query.isPending ? (
          <p aria-live="polite" className="memory-layer-loading" role="status"><LoaderCircle size={15} />正在读取引用详情</p>
        ) : null}
        {query.error ? (
          <div className="memory-reference-dialog__feedback">
            <InlineNotice title="引用暂时无法读取" tone="danger">
              {publicErrorText(query.error, '引用可能已归档，或当前服务尚未完成投影。')}
            </InlineNotice>
            <Button disabled={query.isFetching} onClick={() => void refetch()} size="small" variant="quiet">
              {query.isFetching ? '正在重试' : '重试读取'}
            </Button>
          </div>
        ) : null}
        {!query.isPending && !query.error && !resolvedReference ? (
          <div className="memory-reference-dialog__feedback">
            <InlineNotice title="没有可显示的引用" tone="info">
              当前来源没有返回可安全显示的详情。它可能已归档，或不在当前控制中心的所属范围内。
            </InlineNotice>
            <Button onClick={() => void refetch()} size="small" variant="quiet">重新读取</Button>
          </div>
        ) : null}

        {!query.isPending && !query.error && resolvedReference ? (
          <div className="memory-reference-view" data-reference-key={currentKey}>
            <nav className="memory-reference-path" aria-label="Book Atom Evidence 引用路径">
              <ol>
                {stack.map((step, index) => (
                  <li data-current={index === stack.length - 1 || undefined} key={referenceKey(step)}>
                    <span>{referenceKindCode(step.kind)}</span>
                    <small>{step.label || step.referenceId}</small>
                    {index < stack.length - 1 ? <ChevronRight aria-hidden="true" size={13} /> : null}
                  </li>
                ))}
              </ol>
            </nav>
            <div className="memory-reference-view__identity">
              <span><Fingerprint size={16} /></span>
              <div><small>稳定引用</small><strong>{current.referenceId}</strong></div>
              <StatusBadge
                label={referenceStatusLabel(disposition, current.kind)}
                tone={referenceStatusTone(disposition, current.kind)}
              />
            </div>

            {redacted ? (
              <InlineNotice title="内容已脱敏" tone="warning">
                <span className="memory-reference-view__notice"><EyeOff size={14} />正文不会在控制中心显示；稳定引用、来源类别和治理状态仍保留用于审计。</span>
              </InlineNotice>
            ) : null}
            {!redacted && forgotten ? (
              <InlineNotice title="这条来源已退出记忆召回" tone="info">
                遗忘态不会破坏证据链。它不再参与整理或召回，但仍保留最小审计信息，避免下游事实变成无来源记录。
              </InlineNotice>
            ) : null}
            {content ? <p className="memory-reference-view__content">{content}</p> : null}

            <dl className="memory-reference-view__facts">
              <ReferenceFact label="当前层" value={referenceKindLabel(current.kind)} />
              <ReferenceFact label="来源类别" value={resolvedReference.source.sourceKind || resolvedReference.source.kind} />
              <ReferenceFact label="来源对象" value={resolvedReference.source.id} />
              <ReferenceFact
                label="归属"
                value={resolvedReference.item.ownerKind && resolvedReference.item.ownerId ? `${resolvedReference.item.ownerKind} · ${resolvedReference.item.ownerId}` : '未标注'}
              />
              <ReferenceFact label="时间" value={referenceTime(resolvedReference.item)} />
              <ReferenceFact label="下级引用" value={`${references.length} 条`} />
            </dl>
            {current.kind === 'event' ? (
              <section className="memory-reference-view__source-context" aria-label="整理使用的输入上下文">
                <header>
                  <span><GitBranch size={15} /><strong>整理使用的输入上下文</strong></span>
                  <small>仅所属范围可读</small>
                </header>
                {!sourceContextAvailable ? (
                  <p>当前引用不在本控制中心的所属范围内，因此不返回输入上下文。</p>
                ) : sourceContextRedacted ? (
                  <InlineNotice title="输入上下文已脱敏" tone="warning">
                    上下文参与了来源指纹与语义分组，但正文不会显示。
                  </InlineNotice>
                ) : (
                  <>
                    <dl>
                      <ReferenceFact label="当时上下文" value={sourceContext?.recentContext || '空'} />
                      <ReferenceFact label="当时预编辑" value={sourceContext?.preedit || '空'} />
                    </dl>
                    <p>这些字段来自原始事件，仅用于来源指纹和语义分组；活动时间线只保留稳定引用。</p>
                  </>
                )}
              </section>
            ) : null}

            <section className="memory-reference-view__children" aria-label={referenceChildrenTitle(current.kind)}>
              <header><span><GitBranch size={15} /><strong>{referenceChildrenTitle(current.kind)}</strong></span><small>{references.length} 条</small></header>
              {references.length ? references.map((reference) => {
                const childKey = referenceKey(reference);
                const loop = visited.has(childKey);
                const depthLimited = stack.length >= maximumReferenceDepth;
                return (
                  <button
                    disabled={loop || depthLimited}
                    key={childKey}
                    onClick={() => openReference(reference)}
                    type="button"
                  >
                    <span><small>{referenceKindCode(reference.kind)} · {referenceKindLabel(reference.kind)}</small><strong>{reference.label || reference.referenceId}</strong><em>{reference.referenceId}</em></span>
                    {loop ? <b>已在路径中</b> : depthLimited ? <b>已到最深层</b> : <ChevronRight size={15} />}
                  </button>
                );
              }) : (
                <p>这是当前证据链的叶子节点，没有更深一层引用。</p>
              )}
            </section>

            {stack.length >= maximumReferenceDepth ? (
              <p className="memory-reference-view__guard"><ShieldAlert size={14} />已达到 {maximumReferenceDepth} 层查看上限，避免异常引用链无限展开。</p>
            ) : null}
          </div>
        ) : null}

        <DialogFooter>
          {stack.length > 1 ? (
            <Button leadingIcon={<ArrowLeft size={14} />} onClick={() => setStack((items) => items.slice(0, -1))} variant="quiet">
              返回 {referenceKindCode(stack[stack.length - 2]!.kind)}
            </Button>
          ) : null}
          <Button onClick={() => onOpenChange(false)}>关闭</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ReferenceFact({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value || '未标注'}</dd></div>;
}


function referenceTime(item: MemoryReferenceV1['item'] | undefined): string {
  const value = item?.updatedAtMs || item?.occurredAtMs || item?.createdAtMs;
  return value
    ? new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(value)
    : '未标注';
}

function referenceKindCode(kind: MemoryReferenceKind): string {
  return ({
    event: 'Evidence',
    evidence: 'Evidence',
    atom: 'Atom',
    book: 'Book',
    timeline: 'Timeline',
    role_book_revision: 'Role Book',
  } as const)[kind];
}

function referenceKindLabel(kind: MemoryReferenceKind): string {
  return ({
    event: 'Evidence · 原始来源事件',
    evidence: 'Evidence · 不可变证据',
    atom: 'Atom · 记忆单元',
    book: 'Book · 主题书',
    timeline: 'Timeline · 活动时间线',
    role_book_revision: 'Role Book · 伙伴记忆版本',
  } as const)[kind];
}

function referenceChildrenTitle(kind: MemoryReferenceKind): string {
  return ({
    book: 'Book 中聚合的 Atom',
    atom: 'Atom 的 Evidence',
    evidence: 'Evidence 的原始来源',
    event: '原始来源的关联证据',
    timeline: 'Timeline 的 Evidence',
    role_book_revision: 'Role Book 的 Evidence',
  } as const)[kind];
}

function referenceStatusLabel(status: string, kind: MemoryReferenceKind): string {
  if (kind === 'evidence' && status === 'active') return '已引用';
  return ({
    active: '使用中',
    approved: '已确认',
    archived: '已归档',
    superseded: '历史版本',
    tombstoned: '已移除',
    not_for_memory: '已遗忘',
    forgotten: '已遗忘',
    expired: '已过期',
  } as Record<string, string>)[status] ?? '可追溯';
}

function referenceStatusTone(status: string, kind: MemoryReferenceKind): 'success' | 'info' | 'danger' | 'neutral' {
  if (kind === 'evidence' && status === 'active') return 'info';
  if (status === 'active' || status === 'approved') return 'success';
  if (status === 'archived' || status === 'superseded' || status === 'not_for_memory' || status === 'forgotten' || status === 'expired') return 'info';
  if (status === 'tombstoned') return 'danger';
  return 'neutral';
}

function referenceKey(value: MemoryReferenceSelection): string {
  return `${value.kind}\u0000${value.referenceId}`;
}
