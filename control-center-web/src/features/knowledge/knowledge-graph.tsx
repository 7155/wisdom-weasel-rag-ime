import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Expand, ExternalLink, GitBranch, Network, RefreshCw, Search, SlidersHorizontal, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { Virtuoso } from 'react-virtuoso';
import { Button, Disclosure, EmptyState, IconButton, Input, SegmentedControl, Select, Switch } from '@/components/primitives';
import { InlineNotice, StatusBadge, publicErrorText } from '@/features/overview/management-ui';
import type { ControlTransport } from '@/platform/transport';
import {
  knowledgeLibraryKeys,
  rebuildKnowledgeGraph,
  useKnowledgeGraphQuery,
  type DocumentKnowledgeBase,
  type KnowledgeDocument,
  type KnowledgeGraphEdge,
  type KnowledgeGraphExtractorMode,
  type KnowledgeGraphNode,
  type KnowledgeGraphNodeKind,
} from './api';
import { InteractiveGraphCanvas, type GraphSelection } from './interactive-graph-canvas';
import { publicKnowledgeRelationKind, publicKnowledgeRelationLabel, publicKnowledgeText } from './public-copy';

type Selection = GraphSelection;

const KIND_OPTIONS = [
  { value: 'all', label: '全部类型' },
  { value: 'document', label: '文档' },
  { value: 'topic', label: '主题' },
  { value: 'entity', label: '实体' },
  { value: 'term', label: '术语' },
  { value: 'chunk', label: '片段' },
] as const;

export function KnowledgeGraphPanel({
  active = true,
  base,
  documents,
  onOpenSource,
  transport,
}: {
  active?: boolean;
  base: DocumentKnowledgeBase;
  documents: readonly KnowledgeDocument[];
  onOpenSource: (node: KnowledgeGraphNode) => void;
  transport: ControlTransport;
}) {
  const [view, setView] = useState<'graph' | 'nodes' | 'edges' | 'status'>('graph');
  const [query, setQuery] = useState('');
  const [documentId, setDocumentId] = useState('all');
  const [kind, setKind] = useState<'all' | KnowledgeGraphNodeKind>('all');
  const [limit, setLimit] = useState('80');
  const [depth, setDepth] = useState('2');
  const [excludeChunks, setExcludeChunks] = useState(true);
  const [showStructure, setShowStructure] = useState(false);
  const [extractorMode, setExtractorMode] = useState<KnowledgeGraphExtractorMode>('model');
  const [selection, setSelection] = useState<Selection>(null);
  const [focusMode, setFocusMode] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(true);
  const debouncedQuery = useDebouncedValue(query.trim(), 300);
  const filters = useMemo(() => ({
    documentId: documentId === 'all' ? undefined : documentId,
    query: debouncedQuery || undefined,
    kinds: kind === 'all' ? undefined : [kind],
    limit: Number(limit),
    depth: Number(depth),
    excludeChunks,
  }), [debouncedQuery, depth, documentId, excludeChunks, kind, limit]);
  const graphQuery = useKnowledgeGraphQuery(base.id, filters, active);
  const queryClient = useQueryClient();
  const rebuild = useMutation({
    mutationFn: () => rebuildKnowledgeGraph(transport, base.id, graphQuery.data?.revision ?? 0, { extractorMode }),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: [...knowledgeLibraryKeys.root, 'graph', base.id] }),
  });
  const graph = graphQuery.data;
  const rebuilding = rebuild.isPending || graph?.status === 'building';
  const canvasNodes = useMemo(() => showStructure ? graph?.nodes ?? [] : (graph?.nodes ?? []).filter((node) => node.kind !== 'document' && node.kind !== 'chunk'), [graph?.nodes, showStructure]);
  const canvasEdges = useMemo(() => showStructure ? graph?.edges ?? [] : (graph?.edges ?? []).filter((edge) => isSemanticEdge(edge, graph?.nodes ?? [])), [graph?.edges, graph?.nodes, showStructure]);
  const selectedNode = selection?.type === 'node' ? graph?.nodes.find((node) => node.id === selection.id) ?? null : null;
  const selectedEdge = selection?.type === 'edge' ? graph?.edges.find((edge) => edge.id === selection.id) ?? null : null;

  useEffect(() => setSelection(null), [base.id, debouncedQuery, depth, documentId, excludeChunks, kind, limit]);
  useEffect(() => {
    if (!focusMode) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setFocusMode(false);
        setSettingsOpen(true);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [focusMode]);

  const panel = (
    <div aria-label="知识图谱工作区" className="knowledge-panel knowledge-graph" data-focus={focusMode || undefined}>
      <div className="knowledge-graph__toolbar">
        <div className="knowledge-graph__search-group">
          {focusMode ? <Button className="knowledge-graph__focus-back" leadingIcon={<ArrowLeft size={14} />} onClick={() => { setFocusMode(false); setSettingsOpen(true); }} size="small" variant="quiet">返回知识库</Button> : null}
          <div className="knowledge-graph__search"><Search aria-hidden="true" size={14} /><Input aria-label="搜索图谱" onChange={(event) => setQuery(event.target.value)} placeholder="搜索节点、主题或实体" value={query} /></div>
        </div>
        <Select aria-label="材料范围" onValueChange={setDocumentId} options={[{ value: 'all', label: '全部材料' }, ...documents.map((document) => ({ value: document.id, label: document.name }))]} value={documentId} />
        <Select aria-label="节点类型" onValueChange={setKind} options={KIND_OPTIONS} value={kind} />
        <SegmentedControl aria-label="图谱显示方式" items={[{ value: 'graph', label: <><Network size={13} />图谱</> }, { value: 'nodes', label: '节点' }, { value: 'edges', label: '关系' }, { value: 'status', label: '构建状态' }]} onValueChange={setView} value={view} />
        <div className="knowledge-graph__toolbar-actions">
          <Button aria-pressed={settingsOpen} leadingIcon={<SlidersHorizontal size={14} />} onClick={() => setSettingsOpen((value) => !value)} size="small" variant="quiet">{settingsOpen ? '收起设置' : '展开设置'}</Button>
          {!focusMode ? <Button leadingIcon={<Expand size={14} />} onClick={() => { setFocusMode(true); setSettingsOpen(false); }} size="small" variant="quiet">专注查看</Button> : null}
          <Button disabled={rebuilding} leadingIcon={<RefreshCw className={rebuilding ? 'ui-spin' : ''} size={14} />} loading={rebuild.isPending} onClick={() => rebuild.mutate()} size="small">重建图谱</Button>
        </div>
      </div>
      <div className="knowledge-graph__settings" aria-label="图谱加载设置" data-collapsed={!settingsOpen || undefined}>
        {settingsOpen ? <>
          <label><span>节点上限</span><Select aria-label="节点上限" onValueChange={setLimit} options={['50', '80', '100', '200', '500', '1000'].map((value) => ({ value, label: value }))} value={limit} /></label>
          <label><span>搜索深度</span><Select aria-label="搜索深度" onValueChange={setDepth} options={['1', '2', '3', '4', '5'].map((value) => ({ value, label: `${value} 层` }))} value={depth} /></label>
          <label><span>抽取方式</span><Select aria-label="图谱抽取方式" onValueChange={(value) => setExtractorMode(value as KnowledgeGraphExtractorMode)} options={[{ value: 'model', label: '模型抽取（推荐）' }, { value: 'deterministic', label: '确定性规则（降级）' }]} value={extractorMode} /></label>
          <Switch checked={excludeChunks} label="隐藏片段节点" onCheckedChange={setExcludeChunks} />
          <Switch checked={showStructure} label="显示结构关系" onCheckedChange={setShowStructure} />
        </> : null}
        <span className="knowledge-graph__status"><StatusBadge label={graphStatusLabel(graph?.status, graphQuery.isFetching)} tone={graph?.status === 'failed' ? 'danger' : graph?.status === 'stale' ? 'warning' : 'success'} />{graph?.updatedAtMs ? `更新于 ${formatTime(graph.updatedAtMs)}` : '等待图谱数据'}</span>
      </div>
      {rebuild.data ? <InlineNotice title="图谱重建已开始" tone="info">正在根据当前材料更新关系；可在“处理记录”查看进度。</InlineNotice> : null}
      {rebuild.error ? <InlineNotice title="图谱重建失败" tone="warning">{publicErrorText(rebuild.error, '当前图谱保持不变。')}</InlineNotice> : null}
      {graphQuery.error ? <InlineNotice title="知识图谱暂不可用" tone="warning">{publicErrorText(graphQuery.error, '请检查图谱服务后重试。')}</InlineNotice> : null}
      {graph ? <GraphStats graph={graph} /> : null}
      {graphQuery.isPending ? <p className="knowledge-detail-loading">正在加载知识图谱…</p> : null}
      {graph && (graph.nodes.length || view === 'status') ? (
        <div className="knowledge-graph__workspace" data-has-selection={Boolean(selection) || undefined}>
          {view === 'graph' ? <InteractiveGraphCanvas edges={canvasEdges} key={showStructure ? 'structure' : 'semantic'} mode={showStructure ? 'structure' : 'semantic'} nodes={canvasNodes} onSelect={setSelection} selection={selection} /> : null}
          {view === 'nodes' ? <GraphList mode="nodes" edges={graph.edges} nodes={graph.nodes} onSelect={setSelection} selection={selection} /> : null}
          {view === 'edges' ? <GraphList mode="edges" edges={graph.edges} nodes={graph.nodes} onSelect={setSelection} selection={selection} /> : null}
          {view === 'status' ? <GraphBuildStatus base={base} extractorMode={extractorMode} graph={graph} rebuilding={rebuilding} onRebuild={() => rebuild.mutate()} /> : null}
          {view !== 'status' ? <GraphInspector edge={selectedEdge} edges={graph.edges} node={selectedNode} nodes={graph.nodes} onOpenSource={onOpenSource} onSelect={setSelection} /> : null}
        </div>
      ) : graph && !graphQuery.isPending ? <EmptyState action={<Button onClick={() => setView('status')} size="small">查看构建状态</Button>} description="调整材料、类型、深度或节点上限后再试。" icon={GitBranch} title="当前范围没有图谱节点" /> : null}
    </div>
  );
  // PAWOS itself is a z-indexed root. Portalling to <body> puts this fixed
  // surface in a lower sibling stacking context, underneath the entire OS.
  // Keep the focus canvas inside the desktop root when one exists; standalone
  // Knowledge pages still use <body> as their full-viewport host.
  const focusPortalHost = document.querySelector<HTMLElement>('.paw-desktop-root') ?? document.body;
  return focusMode ? createPortal(panel, focusPortalHost) : panel;
}

function GraphStats({ graph }: { graph: NonNullable<ReturnType<typeof useKnowledgeGraphQuery>['data']> }) {
  return <dl className="knowledge-graph__stats"><div><dt>节点</dt><dd>{graph.stats.nodeCount}</dd></div><div><dt>关系</dt><dd>{graph.stats.edgeCount}</dd></div><div><dt>文档</dt><dd>{graph.stats.documentCount}</dd></div><div><dt>片段</dt><dd>{graph.stats.chunkCount}</dd></div>{graph.truncated ? <span>已按节点上限截断</span> : null}</dl>;
}

function GraphList({ edges, mode, nodes, onSelect, selection }: { edges: readonly KnowledgeGraphEdge[]; mode: 'nodes' | 'edges'; nodes: readonly KnowledgeGraphNode[]; onSelect: (selection: Selection) => void; selection: Selection }) {
  const nodeNames = useMemo(() => new Map(nodes.map((node) => [node.id, publicKnowledgeText(node.label)])), [nodes]);
  const displayName = (id: string) => nodeNames.get(id) ?? id;
  return <div className="knowledge-graph__list" data-mode={mode}>{mode === 'nodes' ? <section><header><strong>节点</strong><span>{nodes.length}</span></header><Virtuoso data={[...nodes]} itemContent={(_index, node) => <button data-selected={selection?.type === 'node' && selection.id === node.id || undefined} onClick={() => onSelect({ type: 'node', id: node.id })} type="button"><span className="knowledge-graph-kind" data-kind={node.kind}>{kindLabel(node.kind)}</span><strong>{publicKnowledgeText(node.label)}</strong><small>{publicKnowledgeText(node.documentName || node.heading) || '跨文档概念'}</small></button>} /></section> : <section><header><strong>关系</strong><span>{edges.length}</span></header><Virtuoso data={[...edges]} itemContent={(_index, edge) => <button data-selected={selection?.type === 'edge' && selection.id === edge.id || undefined} onClick={() => onSelect({ type: 'edge', id: edge.id })} type="button"><span className="knowledge-graph-kind" data-kind="edge">{publicKnowledgeRelationLabel(edge.label, edge.kind)}</span><strong>{displayName(edge.source)} → {displayName(edge.target)}</strong><small>{publicKnowledgeRelationKind(edge.kind)}</small></button>} /></section>}</div>;
}

function GraphBuildStatus({ base, extractorMode, graph, onRebuild, rebuilding }: { base: DocumentKnowledgeBase; extractorMode: KnowledgeGraphExtractorMode; graph: NonNullable<ReturnType<typeof useKnowledgeGraphQuery>['data']>; onRebuild: () => void; rebuilding: boolean }) {
  const extractor = graph.extractor;
  return <section className="knowledge-graph__build-status"><header><div><span>图谱构建状态</span><h3>{graphStatusLabel(graph.status, false)}</h3></div><Button disabled={rebuilding} leadingIcon={<RefreshCw className={rebuilding ? 'ui-spin' : ''} size={14} />} onClick={onRebuild} variant="primary">重建图谱</Button></header><dl><div><dt>已索引材料</dt><dd>{graph.stats.indexedDocumentCount || graph.stats.documentCount}</dd></div><div><dt>待处理材料</dt><dd>{graph.stats.pendingDocumentCount}</dd></div><div><dt>已发现内容</dt><dd>{graph.stats.nodeCount} 个节点 · {graph.stats.edgeCount} 条关系</dd></div><div><dt>当前方式</dt><dd>{extractor?.mode === 'model' ? '模型整理' : extractor?.mode === 'deterministic' ? '规则整理' : '尚未报告'}</dd></div><div><dt>下次重建</dt><dd>{extractorMode === 'model' ? '模型整理（推荐）' : '规则整理'}</dd></div><div><dt>处理结果</dt><dd>{extractor?.degraded ? '部分材料使用了备用方式' : extractor ? '已完成当前方式处理' : '等待构建'}</dd></div><div><dt>更新时间</dt><dd>{graph.updatedAtMs ? formatTime(graph.updatedAtMs) : '未报告'}</dd></div></dl>{extractor?.lastError ? <InlineNotice title="部分材料未能按首选方式整理" tone="warning">已保留可用结果；重新构建后会再次尝试。</InlineNotice> : null}<Disclosure className="knowledge-graph__advanced" summary="高级：构建详情"><dl><div><dt>整理模型</dt><dd>{extractor?.model || (extractorMode === 'model' ? '由当前配置决定' : '不使用')}</dd></div><div><dt>抽取上限</dt><dd>5 实体 / 4 关系 / 2 主题</dd></div><div><dt>批处理</dt><dd>{extractor ? `${extractor.batchSize || 4} 片段/批 · 并发 ${extractor.extractionConcurrency || 1}` : '尚未报告'}</dd></div><div><dt>处理片段</dt><dd>{extractor ? `${extractor.modelChunkCount} 模型整理 · ${extractor.cachedChunkCount} 已复用` : '尚未报告'}</dd></div><div><dt>来源版本</dt><dd>{String(graph.sourceRevision || base.revision)}</dd></div></dl></Disclosure><InlineNotice title="独立文档图谱" tone="info">图谱从当前文档知识库构建，用于管理，并在回答时提供参考；它不与个人记忆图谱合并。</InlineNotice></section>;
}

function GraphInspector({ edge, edges, node, nodes, onOpenSource, onSelect }: { edge: KnowledgeGraphEdge | null; edges: readonly KnowledgeGraphEdge[]; node: KnowledgeGraphNode | null; nodes: readonly KnowledgeGraphNode[]; onOpenSource: (node: KnowledgeGraphNode) => void; onSelect: (selection: Selection) => void }) {
  if (!node && !edge) return null;
  const close = <IconButton className="knowledge-graph__inspector-close" icon={<X size={14} />} label="关闭图谱详情" onClick={() => onSelect(null)} size="small" tooltip />;
  if (edge) return <aside aria-label="关系详情" className="knowledge-graph__inspector">{close}<span className="knowledge-graph-kind" data-kind="edge">关系</span><h3>{publicKnowledgeRelationLabel(edge.label, edge.kind)}</h3><dl><div><dt>起点</dt><dd>{nodeName(nodes, edge.source)}</dd></div><div><dt>终点</dt><dd>{nodeName(nodes, edge.target)}</dd></div><div><dt>类型</dt><dd>{publicKnowledgeRelationKind(edge.kind)}</dd></div><div><dt>权重</dt><dd>{score(edge.weight)}</dd></div></dl></aside>;
  const related = edges.filter((candidate) => candidate.source === node!.id || candidate.target === node!.id);
  const visibleRelated = related.slice(0, 8);
  const renderRelation = (relation: KnowledgeGraphEdge) => (
    <button key={relation.id} onClick={() => onSelect({ type: 'edge', id: relation.id })} type="button">
      <span>{publicKnowledgeRelationLabel(relation.label, relation.kind)}</span>
      <small>{nodeName(nodes, relation.source === node!.id ? relation.target : relation.source)}</small>
    </button>
  );
  return (
    <aside aria-label="节点详情" className="knowledge-graph__inspector">
      {close}
      <span className="knowledge-graph-kind" data-kind={node?.kind}>{kindLabel(node!.kind)}</span>
      <h3>{publicKnowledgeText(node!.label)}</h3>
      <p>{publicKnowledgeText(node!.excerpt) || '该节点没有可显示的摘录。'}</p>
      <dl>
        <div><dt>材料</dt><dd>{publicKnowledgeText(node!.documentName) || '跨文档概念'}</dd></div>
        <div><dt>标题</dt><dd>{publicKnowledgeText(node!.heading) || '未记录'}</dd></div>
        <div><dt>页码</dt><dd>{node!.page ?? '未记录'}</dd></div>
        <div><dt>权重</dt><dd>{score(node!.weight)}</dd></div>
      </dl>
      {related.length ? (
        <section className="knowledge-graph__evidence">
          <header><strong>关联证据</strong><span>显示 {visibleRelated.length} / 共 {related.length} 条</span></header>
          {visibleRelated.map(renderRelation)}
          {related.length > visibleRelated.length ? (
            <Disclosure
              className="knowledge-graph__evidence-more"
              summary={`查看其余 ${related.length - visibleRelated.length} 条关系`}
            >
              <div className="knowledge-graph__evidence-more-list">
                {related.slice(visibleRelated.length).map(renderRelation)}
              </div>
            </Disclosure>
          ) : null}
        </section>
      ) : null}
      {node!.documentId ? <Button leadingIcon={<ExternalLink size={14} />} onClick={() => onOpenSource(node!)} size="small" variant="primary">打开材料来源</Button> : null}
    </aside>
  );
}

function nodeName(nodes: readonly KnowledgeGraphNode[], id: string) { return publicKnowledgeText(nodes.find((node) => node.id === id)?.label ?? id); }
function score(value: number | null) { return value === null ? '未记录' : value.toFixed(2); }
function kindLabel(kind: KnowledgeGraphNodeKind) { return ({ document: '文档', chunk: '片段', topic: '主题', entity: '实体', term: '术语', unknown: '节点' } as const)[kind]; }
function graphStatusLabel(status: string | undefined, fetching: boolean) { return fetching ? '同步中' : status === 'building' ? '构建中' : status === 'stale' ? '待重建' : status === 'failed' ? '失败' : '已就绪'; }
function formatTime(value: number) { return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(value); }
function isSemanticEdge(edge: KnowledgeGraphEdge, nodes: readonly KnowledgeGraphNode[]) {
  const source = nodes.find((node) => node.id === edge.source);
  const target = nodes.find((node) => node.id === edge.target);
  if (source?.kind === 'document' || source?.kind === 'chunk' || target?.kind === 'document' || target?.kind === 'chunk') return false;
  return !['contains', 'covers', 'next', 'next_chunk', 'evidence', 'mentions', 'provenance', 'source', 'derived_from'].includes(edge.kind.toLowerCase());
}

function useDebouncedValue<T>(value: T, delayMs: number) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [delayMs, value]);
  return debounced;
}
