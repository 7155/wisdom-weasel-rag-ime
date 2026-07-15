import { BookOpenCheck, Cloud, Database, ExternalLink, Search, Sparkles } from 'lucide-react';
import { useMemo, useState, type CSSProperties } from 'react';
import { EmptyState, Input } from '@/components/primitives';
import {
  asRecord,
  booleanValue,
  stringValue,
} from '@/features/overview/management-ui';

export interface KnowledgeEvidenceItem {
  id: string;
  title: string;
  excerpt: string;
  sourceType: string;
  source: string;
  score: number | null;
  url: string;
}

export function KnowledgeRouteVisualization({
  route,
  session,
}: {
  route: Record<string, unknown>;
  session: Record<string, unknown>;
}) {
  const notion = asRecord(route.notion);
  const streaming = asRecord(route.streaming);
  const deepseekRoute = asRecord(route.deepseekRoute);
  const modes = Array.isArray(route.modes) ? route.modes.map(String).filter(Boolean) : [];
  const modelReady = booleanValue(route.deepseekReady) && booleanValue(deepseekRoute.remoteReady ?? route.deepseekReady);
  const workbenchStreaming = booleanValue(streaming.knowledgeWorkbench);
  const notionReady = booleanValue(notion.ready);
  const sessionStatus = knowledgeStatusLabel(stringValue(session.status));

  return (
    <div className="knowledge-route-visual" aria-label="知识来源可用状态" role="region">
      <section aria-label="本地知识检索">
        <header><Database aria-hidden="true" size={15} /><strong>本地知识检索</strong><RouteState ready={workbenchStreaming} /></header>
        <dl>
          <div><dt>用途</dt><dd>从本机记忆与知识库查找证据</dd></div>
          <div><dt>当前任务</dt><dd>{sessionStatus}</dd></div>
          <div><dt>进度</dt><dd>{knowledgeStageLabel(stringValue(session.stage))}</dd></div>
          <div><dt>任务类型</dt><dd>{modes.length ? modes.map(knowledgeModeLabel).join(' · ') : '等待服务返回'}</dd></div>
        </dl>
      </section>
      <section aria-label="回答生成">
        <header><Sparkles aria-hidden="true" size={15} /><strong>回答生成</strong><RouteState ready={modelReady} /></header>
        <dl>
          <div><dt>用途</dt><dd>根据召回证据组织回答与长文</dd></div>
          <div><dt>启用方式</dt><dd>只在你明确启动知识任务时使用</dd></div>
          <div><dt>后台自动调用</dt><dd>{booleanValue(deepseekRoute.passivePostCommitRemoteAllowed) ? '已允许' : '不会调用'}</dd></div>
          <div><dt>证据要求</dt><dd>回答与来源分开呈现</dd></div>
        </dl>
      </section>
      <section aria-label="远程笔记" data-disabled={!notionReady || undefined}>
        <header><Cloud aria-hidden="true" size={15} /><strong>远程笔记</strong><RouteState ready={notionReady} /></header>
        <dl>
          <div><dt>用途</dt><dd>补充你主动选择的远程资料</dd></div>
          <div><dt>提交任务</dt><dd>{booleanValue(notion.submitConfigured) ? '可用' : '尚未连接'}</dd></div>
          <div><dt>读取结果</dt><dd>{booleanValue(notion.pollConfigured) ? '可用' : '尚未连接'}</dd></div>
          <div><dt>使用范围</dt><dd>{notionReady ? '仅用于本次任务' : '连接完成后可选'}</dd></div>
        </dl>
      </section>
    </div>
  );
}

export function KnowledgeEvidenceExplorer({ items }: { items: readonly KnowledgeEvidenceItem[] }) {
  const [query, setQuery] = useState('');
  const [sourceType, setSourceType] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const sources = useMemo(() => sourceSummary(items), [items]);
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase('zh-CN');
    return items.filter((item) => {
      if (sourceType && item.sourceType !== sourceType) return false;
      if (!needle) return true;
      return `${item.title}\n${item.excerpt}\n${item.sourceType}\n${item.source}`
        .toLocaleLowerCase('zh-CN')
        .includes(needle);
    });
  }, [items, query, sourceType]);
  const activeId = filtered.some((item) => item.id === selectedId) ? selectedId : filtered[0]?.id ?? '';
  const selected = filtered.find((item) => item.id === activeId) ?? null;
  const largestSource = Math.max(1, ...sources.map((item) => item.count));

  if (!items.length) {
    return <EmptyState description="当前任务没有返回可追溯证据；没有生成示例来源。" icon={BookOpenCheck} title="暂无证据" />;
  }

  return (
    <div className="knowledge-evidence">
      <div className="knowledge-evidence__toolbar">
        <label>
          <Search aria-hidden="true" size={14} />
          <Input aria-label="筛选知识证据" onChange={(event) => setQuery(event.target.value)} placeholder="筛选标题、证据或来源" value={query} />
        </label>
        <button aria-pressed={!sourceType} data-selected={!sourceType || undefined} onClick={() => setSourceType('')} type="button">
          全部 <b>{items.length}</b>
        </button>
      </div>
      <div className="knowledge-source-bars" aria-label="证据来源分布" role="group">
        {sources.map((item) => (
          <button
            aria-pressed={sourceType === item.sourceType}
            data-selected={sourceType === item.sourceType || undefined}
            key={item.sourceType}
            onClick={() => setSourceType((current) => current === item.sourceType ? '' : item.sourceType)}
            type="button"
          >
            <span><strong>{knowledgeSourceTypeLabel(item.sourceType)}</strong><b>{item.count}</b></span>
            <i aria-hidden="true" style={{ '--source-ratio': item.count / largestSource } as CSSProperties} />
          </button>
        ))}
      </div>
      {filtered.length ? (
        <div className="knowledge-evidence__explorer">
          <div className="knowledge-evidence__list" role="listbox" aria-label="知识证据">
            {filtered.map((item) => (
              <button
                aria-selected={activeId === item.id}
                data-selected={activeId === item.id || undefined}
                key={item.id}
                onClick={() => setSelectedId(item.id)}
                role="option"
                type="button"
              >
                <span><strong>{item.title}</strong><small>{item.excerpt || '这条来源没有可显示的摘录'}</small></span>
                <span><b>{knowledgeSourceTypeLabel(item.sourceType)}</b><small>{knowledgeSourceLabel(item)}</small></span>
              </button>
            ))}
          </div>
          {selected ? (
            <article className="knowledge-evidence__detail" aria-label={`${selected.title} 证据详情`}>
              <span>{knowledgeSourceTypeLabel(selected.sourceType)}</span>
              <h3>{selected.title}</h3>
              <p>{selected.excerpt || '这条来源没有可显示的证据摘录。'}</p>
              <dl>
                <div><dt>来源</dt><dd>{knowledgeSourceLabel(selected)}</dd></div>
                <div><dt>相关程度</dt><dd>{relevanceLabel(selected.score)}</dd></div>
                <div><dt>原文</dt><dd>{safeExternalUrl(selected.url) ? <a href={safeExternalUrl(selected.url)} rel="noreferrer" target="_blank">打开来源 <ExternalLink aria-hidden="true" size={12} /></a> : '仅保存在本机'}</dd></div>
              </dl>
            </article>
          ) : null}
        </div>
      ) : <EmptyState description="真实证据中没有符合当前筛选的条目。" icon={Search} title="没有匹配证据" />}
    </div>
  );
}

export function normalizeKnowledgeEvidence(
  evidence: readonly Record<string, unknown>[],
  sources: readonly Record<string, unknown>[],
): KnowledgeEvidenceItem[] {
  const normalized = [...evidence, ...sources].map((item, index) => {
    const id = stringValue(item.sourceId, stringValue(item.id, `source-${index + 1}`));
    const title = publicEvidenceTitle(
      stringValue(item.title, stringValue(item.label)),
      stringValue(item.url),
    );
    const excerpt = stringValue(item.excerpt, stringValue(item.text, stringValue(item.preview, stringValue(item.summary))));
    const sourceType = stringValue(item.sourceType, stringValue(item.kind, stringValue(item.provider, 'local')));
    const source = stringValue(item.provider, stringValue(item.source, sourceType));
    const rawScore = item.score ?? item.similarity ?? item.relevance;
    const score = typeof rawScore === 'number' && Number.isFinite(rawScore) ? rawScore : null;
    return { id, title, excerpt, sourceType, source, score, url: stringValue(item.url) };
  });
  const unique = new Map<string, KnowledgeEvidenceItem>();
  for (const item of normalized) {
    const key = `${item.id}\u0000${item.title}\u0000${item.excerpt}`;
    if (!unique.has(key)) unique.set(key, item);
  }
  return [...unique.values()];
}

function publicEvidenceTitle(value: string, url: string): string {
  const title = value.trim();
  if (title && title.length <= 120 && !/^(?:https?:\/\/|file:|\/)/i.test(title)) return title;
  return safeExternalUrl(url) ? '网页来源' : '未命名来源';
}

function RouteState({ ready }: { ready: boolean }) {
  return <span className="knowledge-route-state" data-ready={ready || undefined}><i aria-hidden="true" />{ready ? '可用' : '暂不可用'}</span>;
}

function sourceSummary(items: readonly KnowledgeEvidenceItem[]): { sourceType: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const item of items) counts.set(item.sourceType, (counts.get(item.sourceType) ?? 0) + 1);
  return [...counts.entries()]
    .map(([sourceType, count]) => ({ sourceType, count }))
    .sort((left, right) => right.count - left.count || left.sourceType.localeCompare(right.sourceType, 'zh-CN'));
}

export function knowledgeModeLabel(value: string): string {
  return ({
    knowledge_answer: '知识问答',
    long_form: '长文生成',
    recall: '帮我回忆',
    organize_database: '整理知识库',
  } as Record<string, string>)[value] ?? '其他任务';
}

export function knowledgeStatusLabel(value: string): string {
  return ({
    idle: '尚未开始',
    missing: '尚未开始',
    queued: '等待开始',
    running: '进行中',
    retrieving: '正在查找证据',
    generating: '正在组织回答',
    organizing: '正在整理知识库',
    ready: '已完成',
    completed: '已完成',
    blocked: '需要处理',
    error: '发生错误',
    cancelled: '已取消',
  } as Record<string, string>)[value] ?? (value ? '处理中' : '尚未开始');
}

export function knowledgeStageLabel(value: string): string {
  return ({
    queued: '正在排队',
    retrieving: '查找本地证据',
    generating: '整理回答',
    building_memory_bundle: '整理历史资料',
    ready: '结果已就绪',
    completed: '结果已就绪',
    failed: '未能完成',
    cancelled: '已取消',
  } as Record<string, string>)[value] ?? (value ? '正在处理' : '未开始');
}

function knowledgeSourceTypeLabel(value: string): string {
  return ({
    memory_atom: '记忆片段',
    memory_book: '记忆簿',
    memory: '记忆',
    notion: '远程笔记',
    document: '文档',
    rag: '知识库',
    local: '本地知识',
  } as Record<string, string>)[value.toLocaleLowerCase('en-US')] ?? '其他来源';
}

function knowledgeSourceLabel(item: KnowledgeEvidenceItem): string {
  const source = item.source.toLocaleLowerCase('en-US');
  if (!source || ['sqlite', 'local', 'memory', 'memory_atom', 'memory_book'].includes(source)) return '本机';
  if (source === 'notion') return 'Notion';
  return knowledgeSourceTypeLabel(item.sourceType);
}

function relevanceLabel(score: number | null): string {
  if (score === null) return '未提供';
  if (score >= 0 && score <= 1) return `${Math.round(score * 100)}%`;
  return '已匹配';
}

function safeExternalUrl(value: string): string {
  if (!value) return '';
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.toString() : '';
  } catch {
    return '';
  }
}
