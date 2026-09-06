import { ChevronRight, GitBranch, RefreshCw } from 'lucide-react';
import { lazy, Suspense, useState } from 'react';
import { Button, Disclosure } from '@/components/primitives';
import type { MemoryEntityV1 } from '@/contracts/generated/memory-entity.v1';
import { asRecord, stringValue } from '@/features/overview/management-ui';
import { useMemoryEntityQuery } from './api';
import type { MemoryReferenceSelection } from './MemoryReferenceDialog';
import { MemoryTopicMap } from './MemoryTopicMap';
import { publicMemoryText } from './public-copy';
import './memory-topic-page.css';

const MemoryRelations = lazy(() => import('./MemoryRelations').then((module) => ({ default: module.MemoryRelations })));
type TopicPage = NonNullable<MemoryEntityV1['topicPage']>;
type TopicEntry = TopicPage['sections']['current'][number];
type TopicReference = TopicPage['sources'][number];

/** The Book summary is navigation. Only the current Atom projection owns these sections. */
export function MemoryTopicPage({ bookId, title, fallbackSummary, fallbackReferences = [], ownerLabel, redacted = false, onOpenReference, onOpenBook }: {
  bookId: string;
  title: string;
  fallbackSummary?: string;
  fallbackReferences?: readonly MemoryReferenceSelection[];
  ownerLabel?: string;
  redacted?: boolean;
  onOpenReference: (reference: MemoryReferenceSelection) => void;
  onOpenBook: (bookId: string) => void;
}) {
  const query = useMemoryEntityQuery('book', bookId, Boolean(bookId) && !redacted);
  const payload = asRecord(query.data);
  const entity = asRecord(payload.entity);
  const candidate = asRecord(payload.topicPage);
  const page = !redacted && candidate.schemaVersion === 'rag-ime.memory-topic-page.v1'
    && candidate.authority === 'atom_projection' && candidate.bookId === bookId
    ? candidate as unknown as TopicPage : null;
  const topicTitle = publicMemoryText(stringValue(entity.label, title || '主题'));
  const legacySummary = publicMemoryText(stringValue(entity.description, fallbackSummary));
  const historical = !redacted && stringValue(entity.status).toLowerCase() === 'superseded';
  const [relationsOpen, setRelationsOpen] = useState(false);
  const retry = () => void query.refetch();
  const sources = originalTopicSources(page?.sources ?? []);

  return <section aria-label={`${topicTitle} 主题页`} className="memory-topic-page">
    <header className="memory-topic-page__header">
      <h3>{topicTitle}</h3>
      <p>从当前记忆读起，再核对变化与原始来源。</p>
      {ownerLabel ? <small>{ownerLabel}</small> : null}
    </header>

    {redacted ? <p role="status">正文因为隐私策略已隐藏，只保留可审计的来源和状态。</p> : null}
    {!redacted && query.isPending ? <p role="status">正在读取主题认识…</p> : null}
    {!redacted && query.error ? <div className="memory-topic-page__notice" role="alert">
      <strong>主题内容读取失败</strong><p>可以重新读取；已有摘要不会替代当前认识。</p>
      <Button leadingIcon={<RefreshCw size={14} />} onClick={retry} size="small" variant="quiet">重新读取主题</Button>
    </div> : !redacted && !query.isPending && !page ? <div className="memory-topic-page__notice" role="status">
      <p>当前服务尚未提供主题的当前认识。</p>
      <Button leadingIcon={<RefreshCw size={14} />} onClick={retry} size="small" variant="quiet">重新读取主题</Button>
    </div> : null}

    {page && !query.error ? <>
      {historical ? <div className="memory-topic-page__notice" role="status">
        <strong>这是已替代的历史主题。</strong><p>以下内容按可读记忆原子重建，原主题摘要不作为当前认识。</p>
      </div> : null}
      {page.freshness === 'needs_refresh' ? <div className="memory-topic-page__notice" role="status">
        <strong>主题需要更新</strong><p>以下按当前可读记忆展示，主题整理仍待更新。</p>
      </div> : null}
      {page.coverage.omittedAtomCount > 0 || page.coverage.truncated ? <p className="memory-topic-page__coverage" role="status">
        展示 {page.coverage.visibleAtomCount} 条可读记忆；主题原关联 {page.coverage.memberCount} 条。另有 {page.coverage.omittedAtomCount} 条未展示。
        {page.coverage.truncated ? <span>内容超过本次读取范围，可从记忆原文继续核对。</span> : null}
      </p> : null}
      <TopicSection entries={page.sections.current} onOpenReference={onOpenReference} title="当前认识" emptyText="这个主题还没有可展示的当前认识。" />
      <TopicSection entries={page.sections.constraints} onOpenReference={onOpenReference} title="需要遵守的约束" />
      <TopicSection entries={page.sections.history} history onOpenReference={onOpenReference} title="最近变化" />
      <TopicSection entries={page.sections.openQuestions} onOpenReference={onOpenReference} title="仍未确定" />
      <section aria-label="主题来源" className="memory-topic-page__section">
        <h4>来源</h4>
        {sources.length ? <Disclosure summary={`核对原始来源 · ${sources.length} 条`}>
          <TopicReferences onOpenReference={onOpenReference} references={sources} />
        </Disclosure> : <p className="memory-topic-page__muted">本次主题投影没有可读的原始来源引用。</p>}
      </section>
      <Disclosure summary="查看依据与变化图">
        <MemoryTopicMap page={page} onOpenReference={onOpenReference} />
      </Disclosure>
      <Disclosure className="memory-topic-page__explore" onOpenChange={setRelationsOpen} summary="探索主题关系">
        <p className="memory-topic-page__muted">标签共现用于查找相关主题，不表示事实支持或因果关系。</p>
        <Suspense fallback={<p role="status">正在读取关系探索…</p>}>
          <MemoryRelations enabled={relationsOpen} initialTopic={{ id: bookId, title: topicTitle }} onOpenBook={onOpenBook} />
        </Suspense>
      </Disclosure>
    </> : null}

    {!page && !redacted ? <>
      {legacySummary ? <Disclosure className="memory-topic-page__legacy" summary="查看已有摘要">
        <p className="memory-topic-page__muted">这份摘要仅供回看，尚未核对为当前认识。</p>
        <p>{legacySummary}</p>
        {fallbackReferences.length ? <ul className="memory-topic-page__sources">{fallbackReferences.map((reference) => <li key={`${reference.kind}:${reference.referenceId}`}>
          <button onClick={() => onOpenReference(reference)} type="button">{publicMemoryText(reference.label || '查看已有引用')}<ChevronRight aria-hidden="true" size={14} /></button>
        </li>)}</ul> : null}
      </Disclosure> : null}
      <Button onClick={() => onOpenReference({ kind: 'book', referenceId: bookId, label: title ? topicTitle : undefined })} size="small" variant="quiet">查看主题已有来源</Button>
    </> : null}
  </section>;
}

function TopicSection({ entries, title, history = false, emptyText, onOpenReference }: {
  entries: readonly TopicEntry[];
  title: string;
  history?: boolean;
  emptyText?: string;
  onOpenReference: (reference: MemoryReferenceSelection) => void;
}) {
  if (!entries.length && !emptyText) return null;
  return <section aria-label={title} className="memory-topic-page__section" data-history={history || undefined}>
    <h4>{title}</h4>
    {!entries.length ? <p className="memory-topic-page__muted">{emptyText}</p> : <ol className="memory-topic-page__entries">
      {entries.map((entry) => {
        const sources = originalTopicSources(entry.references);
        return <li key={entry.id}>
          <p className="memory-topic-page__claim">{publicMemoryText(entry.text)}</p>
          {history ? <div className="memory-topic-page__history">
            <span>{entry.supersededByIds.length ? '已有后续记忆' : '历史记忆'}{entry.validToMs ? ` · 有效至 ${topicDate(entry.validToMs)}` : ''}</span>
            {entry.supersededByIds.map((id) => <button key={id} onClick={() => onOpenReference({ kind: 'atom', referenceId: id, label: '后续记忆' })} type="button">查看后续记忆 <ChevronRight aria-hidden="true" size={13} /></button>)}
            <p>{entry.reason ? publicMemoryText(entry.reason) : '尚未提供可核对的变更理由。'}</p>
          </div> : entry.validFromMs > 0 ? <span className="memory-topic-page__time">有效自 {topicDate(entry.validFromMs)}</span> : null}
          {entry.sourceStatus === 'unavailable' || !sources.length ? <p className="memory-topic-page__muted">这条记忆的来源暂不可读。</p> : null}
          <Disclosure className="memory-topic-page__evidence" summary={`查看依据 · ${sources.length} 条来源`}>
            <Button leadingIcon={<GitBranch size={13} />} onClick={() => onOpenReference({ kind: 'atom', referenceId: entry.id, label: '记忆原文' })} size="small" variant="quiet">查看记忆原文</Button>
            <TopicReferences onOpenReference={onOpenReference} references={sources} />
          </Disclosure>
        </li>;
      })}
    </ol>}
  </section>;
}

/** Atom links open memory records; only Evidence/Event links count as original
 * sources. One source can support multiple records without becoming new proof. */
function originalTopicSources(references: readonly TopicReference[]): TopicReference[] {
  return [...new Map(references
    .filter((reference) => reference.referenceKind === 'evidence' || reference.referenceKind === 'event')
    .map((reference) => [`${reference.referenceKind}:${reference.referenceId}`, reference])).values()];
}

function TopicReferences({ references, onOpenReference }: {
  references: readonly TopicReference[];
  onOpenReference: (reference: MemoryReferenceSelection) => void;
}) {
  return <ul className="memory-topic-page__sources">
    {references.map((reference) => <li key={`${reference.referenceKind}:${reference.referenceId}`}>
      <button onClick={() => onOpenReference({ kind: reference.referenceKind, referenceId: reference.referenceId, label: reference.label })} type="button">
        <span>{publicMemoryText(reference.label || '查看原始来源')}</span><ChevronRight aria-hidden="true" size={14} />
      </button>
    </li>)}
  </ul>;
}

function topicDate(value: number) {
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'short', day: 'numeric' }).format(value);
}
