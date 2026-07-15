import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ExternalLink, GitBranch, Network, RefreshCw, Search } from 'lucide-react';
import { useDeferredValue, useEffect, useMemo, useState } from 'react';
import { Button, EmptyState, Input, SegmentedControl, Select, Switch } from '@/components/primitives';
import { InlineNotice, StatusBadge, publicErrorText } from '@/features/overview/management-ui';
import type { ControlTransport } from '@/platform/transport';
import {
  knowledgeLibraryKeys,
  rebuildKnowledgeGraph,
  useKnowledgeGraphQuery,
  type DocumentKnowledgeBase,
  type KnowledgeDocument,
  type KnowledgeGraphEdge,
  type KnowledgeGraphNode,
  type KnowledgeGraphNodeKind,
} from './api';

type Selection = { type: 'node'; id: string } | { type: 'edge'; id: string } | null;

const KIND_OPTIONS = [
  { value: 'all', label: '全部类型' },
  { value: 'document', label: '文档' },
  { value: 'topic', label: '主题' },
  { value: 'entity', label: '实体' },
  { value: 'term', label: '术语' },
  { value: 'chunk', label: '片段' },
] as const;

export function KnowledgeGraphPanel({
  base,
  documents,
  onOpenSource,
  transport,
}: {
  base: DocumentKnowledgeBase;
  documents: readonly KnowledgeDocument[];
  onOpenSource: (node: KnowledgeGraphNode) => void;
  transport: ControlTransport;
}) {
  const [view, setView] = useState<'graph' | 'nodes' | 'edges' | 'status'>('graph');
  const [query, setQuery] = useState('');
  const [documentId, setDocumentId] = useState('all');
  const [kind, setKind] = useState<'all' | KnowledgeGraphNodeKind>('all');
  const [limit, setLimit] = useState('100');
  const [depth, setDepth] = useState('2');
  const [excludeChunks, setExcludeChunks] = useState(true);
  const [selection, setSelection] = useState<Selection>(null);
  const deferredQuery = useDeferredValue(query.trim());
  const filters = useMemo(() => ({
    documentId: documentId === 'all' ? undefined : documentId,
    query: deferredQuery || undefined,
    kinds: kind === 'all' ? undefined : [kind],
    limit: Number(limit),
    depth: Number(depth),
    excludeChunks,
  }), [deferredQuery, depth, documentId, excludeChunks, kind, limit]);
  const graphQuery = useKnowledgeGraphQuery(base.id, filters);
  const queryClient = useQueryClient();
  const rebuild = useMutation({
    mutationFn: () => rebuildKnowledgeGraph(transport, base.id, graphQuery.data?.revision ?? 0),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: [...knowledgeLibraryKeys.root, 'graph', base.id] }),
  });
  const graph = graphQuery.data;
  const selectedNode = selection?.type === 'node' ? graph?.nodes.find((node) => node.id === selection.id) ?? null : null;
  const selectedEdge = selection?.type === 'edge' ? graph?.edges.find((edge) => edge.id === selection.id) ?? null : null;

  useEffect(() => setSelection(null), [base.id, depth, documentId, excludeChunks, kind, limit]);

  return (
    <div className="knowledge-panel knowledge-graph">
      <div className="knowledge-graph__toolbar">
        <div className="knowledge-graph__search"><Search aria-hidden="true" size={14} /><Input aria-label="搜索图谱" onChange={(event) => setQuery(event.target.value)} placeholder="搜索节点、主题或实体" value={query} /></div>
        <Select aria-label="材料范围" onValueChange={setDocumentId} options={[{ value: 'all', label: '全部材料' }, ...documents.map((document) => ({ value: document.id, label: document.name }))]} value={documentId} />
        <Select aria-label="节点类型" onValueChange={setKind} options={KIND_OPTIONS} value={kind} />
        <SegmentedControl aria-label="图谱显示方式" items={[{ value: 'graph', label: <><Network size={13} />图谱</> }, { value: 'nodes', label: '节点' }, { value: 'edges', label: '关系' }, { value: 'status', label: '构建状态' }]} onValueChange={setView} value={view} />
        <Button leadingIcon={<RefreshCw className={rebuild.isPending ? 'ui-spin' : ''} size={14} />} loading={rebuild.isPending} onClick={() => rebuild.mutate()} size="small">重建图谱</Button>
      </div>
      <div className="knowledge-graph__settings" aria-label="图谱加载设置">
        <label><span>节点上限</span><Select aria-label="节点上限" onValueChange={setLimit} options={['50', '100', '200', '500', '1000'].map((value) => ({ value, label: value }))} value={limit} /></label>
        <label><span>搜索深度</span><Select aria-label="搜索深度" onValueChange={setDepth} options={['1', '2', '3', '4', '5'].map((value) => ({ value, label: `${value} 层` }))} value={depth} /></label>
        <Switch checked={excludeChunks} label="隐藏片段节点" onCheckedChange={setExcludeChunks} />
        <span className="knowledge-graph__status"><StatusBadge label={graphStatusLabel(graph?.status, graphQuery.isFetching)} tone={graph?.status === 'failed' ? 'danger' : graph?.status === 'stale' ? 'warning' : 'success'} />{graph?.updatedAtMs ? `更新于 ${formatTime(graph.updatedAtMs)}` : '等待图谱数据'}</span>
      </div>
      {rebuild.data ? <InlineNotice title="图谱重建已提交" tone="info">任务 {rebuild.data.jobId || '已进入队列'} · {rebuild.data.status}</InlineNotice> : null}
      {rebuild.error ? <InlineNotice title="图谱重建失败" tone="warning">{publicErrorText(rebuild.error, '当前图谱保持不变。')}</InlineNotice> : null}
      {graphQuery.error ? <InlineNotice title="知识图谱暂不可用" tone="warning">{publicErrorText(graphQuery.error, '请检查图谱服务后重试。')}</InlineNotice> : null}
      {graph ? <GraphStats graph={graph} /> : null}
      {graphQuery.isPending ? <p className="knowledge-detail-loading">正在加载知识图谱…</p> : null}
      {graph && (graph.nodes.length || view === 'status') ? (
        <div className="knowledge-graph__workspace">
          {view === 'graph' ? <GraphCanvas edges={graph.edges} nodes={graph.nodes} onSelect={setSelection} selection={selection} /> : null}
          {view === 'nodes' ? <GraphList mode="nodes" edges={graph.edges} nodes={graph.nodes} onSelect={setSelection} selection={selection} /> : null}
          {view === 'edges' ? <GraphList mode="edges" edges={graph.edges} nodes={graph.nodes} onSelect={setSelection} selection={selection} /> : null}
          {view === 'status' ? <GraphBuildStatus base={base} graph={graph} rebuilding={rebuild.isPending} onRebuild={() => rebuild.mutate()} /> : null}
          {view !== 'status' ? <GraphInspector edge={selectedEdge} node={selectedNode} nodes={graph.nodes} onOpenSource={onOpenSource} /> : null}
        </div>
      ) : graph && !graphQuery.isPending ? <EmptyState action={<Button onClick={() => setView('status')} size="small">查看构建状态</Button>} description="调整材料、类型、深度或节点上限后再试。" icon={GitBranch} title="当前范围没有图谱节点" /> : null}
    </div>
  );
}

function GraphStats({ graph }: { graph: NonNullable<ReturnType<typeof useKnowledgeGraphQuery>['data']> }) {
  return <dl className="knowledge-graph__stats"><div><dt>节点</dt><dd>{graph.stats.nodeCount}</dd></div><div><dt>关系</dt><dd>{graph.stats.edgeCount}</dd></div><div><dt>文档</dt><dd>{graph.stats.documentCount}</dd></div><div><dt>片段</dt><dd>{graph.stats.chunkCount}</dd></div>{graph.truncated ? <span>已按节点上限截断</span> : null}</dl>;
}

function GraphCanvas({ edges, nodes, onSelect, selection }: { edges: readonly KnowledgeGraphEdge[]; nodes: readonly KnowledgeGraphNode[]; onSelect: (selection: Selection) => void; selection: Selection }) {
  const positions = useMemo(() => layoutNodes(nodes), [nodes]);
  const columnSizes = [
    nodes.filter((node) => node.kind === 'document').length,
    nodes.filter((node) => ['topic', 'entity', 'term', 'unknown'].includes(node.kind)).length,
    nodes.filter((node) => node.kind === 'chunk').length,
  ];
  const height = Math.max(500, Math.max(...columnSizes) * 76 + 80);
  return (
    <div className="knowledge-graph__canvas" aria-label="知识图谱画布">
      <svg role="img" viewBox={`0 0 1060 ${height}`}>
        <title>当前知识库节点关系图</title>
        {edges.map((edge) => {
          const source = positions.get(edge.source); const target = positions.get(edge.target);
          if (!source || !target) return null;
          const selected = selection?.type === 'edge' && selection.id === edge.id;
          return <g className="knowledge-graph-edge" data-selected={selected || undefined} key={edge.id} onClick={() => onSelect({ type: 'edge', id: edge.id })} role="button" tabIndex={0} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') onSelect({ type: 'edge', id: edge.id }); }} aria-label={`关系 ${edge.label || edge.kind}`}><line className="knowledge-graph-edge__hit" x1={source.x} x2={target.x} y1={source.y} y2={target.y} /><line x1={source.x} x2={target.x} y1={source.y} y2={target.y} /></g>;
        })}
        {nodes.map((node) => {
          const point = positions.get(node.id)!;
          return <g aria-label={`${kindLabel(node.kind)} ${node.label}`} className="knowledge-graph-node" data-kind={node.kind} data-selected={selection?.type === 'node' && selection.id === node.id || undefined} key={node.id} onClick={() => onSelect({ type: 'node', id: node.id })} role="button" tabIndex={0} transform={`translate(${point.x} ${point.y})`} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') onSelect({ type: 'node', id: node.id }); }}><rect height="48" rx="5" width="184" x="-92" y="-24" /><text textAnchor="middle" y="-3">{truncate(node.label, 22)}</text><text className="knowledge-graph-node__kind" textAnchor="middle" y="14">{kindLabel(node.kind)}</text></g>;
        })}
      </svg>
    </div>
  );
}

function GraphList({ edges, mode, nodes, onSelect, selection }: { edges: readonly KnowledgeGraphEdge[]; mode: 'nodes' | 'edges'; nodes: readonly KnowledgeGraphNode[]; onSelect: (selection: Selection) => void; selection: Selection }) {
  return <div className="knowledge-graph__list" data-mode={mode}>{mode === 'nodes' ? <section><header><strong>节点</strong><span>{nodes.length}</span></header>{nodes.map((node) => <button data-selected={selection?.type === 'node' && selection.id === node.id || undefined} key={node.id} onClick={() => onSelect({ type: 'node', id: node.id })} type="button"><span className="knowledge-graph-kind" data-kind={node.kind}>{kindLabel(node.kind)}</span><strong>{node.label}</strong><small>{node.documentName || node.heading || '跨文档概念'}</small></button>)}</section> : <section><header><strong>关系</strong><span>{edges.length}</span></header>{edges.map((edge) => <button data-selected={selection?.type === 'edge' && selection.id === edge.id || undefined} key={edge.id} onClick={() => onSelect({ type: 'edge', id: edge.id })} type="button"><span className="knowledge-graph-kind" data-kind="edge">{edge.label || edge.kind}</span><strong>{nodeName(nodes, edge.source)} → {nodeName(nodes, edge.target)}</strong><small>{edge.kind}</small></button>)}</section>}</div>;
}

function GraphBuildStatus({ base, graph, onRebuild, rebuilding }: { base: DocumentKnowledgeBase; graph: NonNullable<ReturnType<typeof useKnowledgeGraphQuery>['data']>; onRebuild: () => void; rebuilding: boolean }) {
  return <section className="knowledge-graph__build-status"><header><div><span>图谱构建状态</span><h3>{graphStatusLabel(graph.status, rebuilding)}</h3></div><Button leadingIcon={<RefreshCw size={14} />} loading={rebuilding} onClick={onRebuild} variant="primary">重建图谱</Button></header><dl><div><dt>已索引材料</dt><dd>{graph.stats.indexedDocumentCount || graph.stats.documentCount}</dd></div><div><dt>待处理材料</dt><dd>{graph.stats.pendingDocumentCount}</dd></div><div><dt>节点 / 关系</dt><dd>{graph.stats.nodeCount} / {graph.stats.edgeCount}</dd></div><div><dt>来源 revision</dt><dd>{String(graph.sourceRevision || base.revision)}</dd></div><div><dt>更新时间</dt><dd>{graph.updatedAtMs ? formatTime(graph.updatedAtMs) : '未报告'}</dd></div></dl><InlineNotice title="独立文档图谱" tone="info">图谱从当前文档知识库构建，用于管理和辅助召回；它不与个人记忆图谱合并。</InlineNotice></section>;
}

function GraphInspector({ edge, node, nodes, onOpenSource }: { edge: KnowledgeGraphEdge | null; node: KnowledgeGraphNode | null; nodes: readonly KnowledgeGraphNode[]; onOpenSource: (node: KnowledgeGraphNode) => void }) {
  if (!node && !edge) return <aside className="knowledge-graph__inspector"><EmptyState description="可查看摘录、关系和材料来源。" icon={Network} title="选择一个节点或关系" /></aside>;
  if (edge) return <aside className="knowledge-graph__inspector"><span className="knowledge-graph-kind" data-kind="edge">关系</span><h3>{edge.label || edge.kind}</h3><dl><div><dt>起点</dt><dd>{nodeName(nodes, edge.source)}</dd></div><div><dt>终点</dt><dd>{nodeName(nodes, edge.target)}</dd></div><div><dt>类型</dt><dd>{edge.kind}</dd></div><div><dt>权重</dt><dd>{score(edge.weight)}</dd></div></dl></aside>;
  return <aside className="knowledge-graph__inspector"><span className="knowledge-graph-kind" data-kind={node?.kind}>{kindLabel(node!.kind)}</span><h3>{node!.label}</h3><p>{node!.excerpt || '该节点没有可显示的摘录。'}</p><dl><div><dt>材料</dt><dd>{node!.documentName || '跨文档概念'}</dd></div><div><dt>标题</dt><dd>{node!.heading || '未记录'}</dd></div><div><dt>页码</dt><dd>{node!.page ?? '未记录'}</dd></div><div><dt>权重</dt><dd>{score(node!.weight)}</dd></div></dl>{node!.documentId ? <Button leadingIcon={<ExternalLink size={14} />} onClick={() => onOpenSource(node!)} size="small" variant="primary">打开材料来源</Button> : null}</aside>;
}

function layoutNodes(nodes: readonly KnowledgeGraphNode[]) {
  const columns: KnowledgeGraphNodeKind[][] = [['document'], ['topic', 'entity', 'term', 'unknown'], ['chunk']];
  const positions = new Map<string, { x: number; y: number }>();
  columns.forEach((kinds, column) => {
    const group = nodes.filter((node) => kinds.includes(node.kind));
    group.forEach((node, index) => positions.set(node.id, { x: 160 + column * 370, y: 64 + index * 76 }));
  });
  return positions;
}

function nodeName(nodes: readonly KnowledgeGraphNode[], id: string) { return nodes.find((node) => node.id === id)?.label ?? id; }
function truncate(value: string, length: number) { return value.length > length ? `${value.slice(0, length - 1)}…` : value; }
function score(value: number | null) { return value === null ? '未记录' : value.toFixed(2); }
function kindLabel(kind: KnowledgeGraphNodeKind) { return ({ document: '文档', chunk: '片段', topic: '主题', entity: '实体', term: '术语', unknown: '节点' } as const)[kind]; }
function graphStatusLabel(status: string | undefined, fetching: boolean) { return fetching ? '同步中' : status === 'building' ? '构建中' : status === 'stale' ? '待重建' : status === 'failed' ? '失败' : '已就绪'; }
function formatTime(value: number) { return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(value); }
