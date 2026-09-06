import { ArrowUpRight, FileText, GitBranch } from 'lucide-react';
import { useState } from 'react';
import { Select } from '@/components/primitives';
import type { MemoryEntityV1 } from '@/contracts/generated/memory-entity.v1';
import type { MemoryReferenceSelection } from './MemoryReferenceDialog';
import { publicMemoryText } from './public-copy';
import './memory-topic-map.css';

type TopicPage = NonNullable<MemoryEntityV1['topicPage']>;
type Entry = TopicPage['sections']['current'][number];

/** Every line joins an existing reference. This view neither infers semantic
 * relations nor turns the Book or its Atom into another independent source. */
export function MemoryTopicMap({ page, onOpenReference }: {
  page: TopicPage;
  onOpenReference: (reference: MemoryReferenceSelection) => void;
}) {
  const entries = [
    ...page.sections.current.map((entry) => ({ entry, label: '当前认识' })),
    ...page.sections.constraints.map((entry) => ({ entry, label: '约束' })),
    ...page.sections.openQuestions.map((entry) => ({ entry, label: '待确认' })),
  ];
  const [selectedId, setSelectedId] = useState('');
  const selected = entries.find(({ entry }) => entry.id === selectedId) ?? entries[0];
  if (!selected) return <p className="memory-topic-map__empty">当前没有可追溯的认识。已有历史仍可从上方展开。</p>;
  const { entry, label } = selected;
  const references = [...new Map(entry.references
    .filter((reference) => reference.referenceKind === 'evidence' || reference.referenceKind === 'event')
    .map((reference) => [`${reference.referenceKind}:${reference.referenceId}`, reference])).values()];
  const history = page.sections.history.filter((past) => isRelatedPast(past, entry));
  const openAtom = (atom: Entry) => onOpenReference({ kind: 'atom', referenceId: atom.id, label: '记忆原文' });

  return <section aria-label="主题依据与变化图" className="memory-topic-map">
    <div className="memory-topic-map__selection">
      <label htmlFor={`topic-map-${page.bookId}`}>选择要追溯的记忆</label>
      <Select id={`topic-map-${page.bookId}`} aria-label="选择要追溯的记忆" value={entry.id} onValueChange={setSelectedId}
        options={entries.map(({ entry: item, label: kind }) => ({ value: item.id, label: `${kind} · ${publicMemoryText(item.text)}` }))} />
    </div>
    <div aria-label="选中记忆的来源关系" role="group" className="memory-topic-map__diagram" data-has-sources={references.length > 0 || undefined}>
      <button className="memory-topic-map__claim" onClick={() => openAtom(entry)} type="button">
        <span><GitBranch aria-hidden="true" size={14} />{label}</span>
        <strong>{publicMemoryText(entry.text)}</strong>
        <small>查看记忆原文 <ArrowUpRight aria-hidden="true" size={13} /></small>
      </button>
      <div aria-hidden="true" className="memory-topic-map__connections">
        {references.length ? <svg viewBox="0 0 100 100" preserveAspectRatio="none">
          {references.map((reference, index) => <path key={`${reference.referenceKind}:${reference.referenceId}`}
            d={`M 0 50 C 50 50, 50 ${(index + .5) / references.length * 100}, 100 ${(index + .5) / references.length * 100}`} />)}
        </svg> : null}
      </div>
      <div className="memory-topic-map__originals">
        <span className="memory-topic-map__source-count">{references.length} 条原始依据</span>
        {references.length ? references.map((reference) => <button key={`${reference.referenceKind}:${reference.referenceId}`}
          onClick={() => onOpenReference({ kind: reference.referenceKind, referenceId: reference.referenceId, label: reference.label })} type="button">
          <FileText aria-hidden="true" size={15} /><span>{publicMemoryText(reference.label || '打开原始来源')}</span><ArrowUpRight aria-hidden="true" size={13} />
        </button>) : <p className="memory-topic-map__empty">原始依据暂不可读，未绘制来源连线。</p>}
      </div>
    </div>
    {history.length ? <div className="memory-topic-map__history">
      <h5>这条认识的过去版本</h5>
      <ol>{history.map((past) => <li key={past.id}><button onClick={() => openAtom(past)} type="button">
        <span>历史记忆</span><strong>{publicMemoryText(past.text)}</strong><ArrowUpRight aria-hidden="true" size={13} />
      </button></li>)}</ol>
      <p>谱系连接保留过往版本；变更理由以可核对的来源为准。</p>
    </div> : null}
  </section>;
}

function isRelatedPast(past: Entry, current: Entry) {
  return (Boolean(current.lineageId) && past.lineageId === current.lineageId)
    || current.supersedesId === past.id || past.supersededByIds.includes(current.id);
}
