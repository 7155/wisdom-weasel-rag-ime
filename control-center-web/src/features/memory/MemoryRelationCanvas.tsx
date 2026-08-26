import type { EdgeData, ElementDatum, Graph, IElementEvent } from '@antv/g6';
import { CircleAlert, Focus, Maximize2, RotateCcw, ZoomIn, ZoomOut } from 'lucide-react';
import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { Button } from '@/components/primitives';

export interface MemoryRelationNode {
  id: string;
  label: string;
  kind: 'tag' | 'group' | 'book';
  count: number;
  connections: number;
  description?: string;
  metricLabel?: string;
  source?: string;
  status?: string;
}

export interface MemoryRelationEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  weight: number;
  evidenceCount: number;
}

export const MemoryRelationCanvas = memo(function MemoryRelationCanvas({
  edges,
  enabled,
  nodes,
  onSelect,
  selectedId,
}: {
  edges: readonly MemoryRelationEdge[];
  enabled: boolean;
  nodes: readonly MemoryRelationNode[];
  onSelect: (id: string) => void;
  selectedId: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<Graph | null>(null);
  const onSelectRef = useRef(onSelect);
  const [graphError, setGraphError] = useState(false);
  const [readyVersion, setReadyVersion] = useState(0);
  const [retryVersion, setRetryVersion] = useState(0);
  const graphData = useMemo(() => relationGraphData(nodes, edges), [edges, nodes]);
  const selectedNode = nodes.find((node) => node.id === selectedId) ?? null;
  onSelectRef.current = onSelect;

  useEffect(() => {
    const container = containerRef.current;
    if (!enabled || !container || graphData.nodes.length === 0) return;
    let cancelled = false;
    let failed = false;
    let initializing = false;
    let resizeFrame = 0;
    let settleFrame = 0;
    let fitted = false;

    const fitWhenVisible = async (graph: Graph) => {
      if (cancelled || container.clientWidth < 2 || container.clientHeight < 2) return;
      graph.resize(container.clientWidth, container.clientHeight);
      // The first fit should deliberately use the available canvas. Without
      // it, d3-force keeps a readable cluster at its simulation scale but the
      // product renders that cluster as a tiny island in a large viewport.
      // Later resizes only shrink overflow so user zoom is not continuously
      // overwritten.
      await graph.fitView(
        { when: fitted ? 'overflow' : 'always', direction: 'both' },
        { duration: motionDuration(fitted ? 120 : 240) },
      );
      // fitView may shrink a dense network, but it must not inflate a small
      // one into poster-sized circles. Keep one stable reading scale while
      // filters and relationship scopes change.
      if (graph.getZoom() > MAX_READABLE_ZOOM) {
        await graph.zoomTo(MAX_READABLE_ZOOM, { duration: motionDuration(160) });
        await graph.fitCenter({ duration: motionDuration(120) });
      }
      fitted = true;
    };

    setGraphError(false);
    setReadyVersion(0);

    const initialize = async () => {
      if (cancelled || failed || initializing || graphRef.current || container.clientWidth < 2 || container.clientHeight < 2) return;
      initializing = true;
      let graph: Graph | null = null;
      try {
        const { Graph: G6Graph } = await import('../knowledge/g6-runtime');
        if (cancelled) return;
        const style = getComputedStyle(container);
        const activeGraph = new G6Graph({
        container,
        width: container.clientWidth,
        height: container.clientHeight,
        autoResize: false,
        animation: motionDuration(180)
          ? { duration: 180, easing: 'cubic-bezier(0.23, 1, 0.32, 1)' }
          : false,
        data: graphData,
        layout: {
          type: 'd3-force',
          iterations: 320,
          preventOverlap: true,
          collide: {
            radius: (node) => relationCollisionRadius(node as unknown as RelationLayoutNode),
            strength: 1,
            iterations: 4,
          },
          manyBody: {
            strength: -640,
            distanceMin: 64,
            distanceMax: 520,
          },
          link: {
            distance: 168,
            strength: .68,
            iterations: 2,
          },
          centerStrength: .04,
          clustering: graphData.clusterCount > 1,
          clusterBy: (node) => relationCluster(node as unknown as RelationLayoutNode),
          clusterFociStrength: .16,
          clusterNodeStrength: -90,
          clusterEdgeStrength: .14,
          clusterEdgeDistance: 250,
          clusterNodeSize: 92,
          x: {
            x: (node) => relationClusterAnchor(node as unknown as RelationLayoutNode, 'x'),
            strength: .11,
          },
          y: {
            y: (node) => relationClusterAnchor(node as unknown as RelationLayoutNode, 'y'),
            strength: .08,
          },
          alphaDecay: .028,
          velocityDecay: .46,
        },
        node: {
          type: 'circle',
          style: {
            size: (datum) => nodeSize(Number(datum.data?.count ?? 0), Number(datum.data?.connections ?? 0)),
            fill: (datum) => kindColor(String(datum.data?.kind), style),
            fillOpacity: .88,
            stroke: cssColor(style, '--color-surface', '#fff'),
            lineWidth: 2.5,
            halo: true,
            haloLineWidth: 10,
            haloStrokeOpacity: .08,
            shadowBlur: 12,
            shadowColor: (datum) => kindColor(String(datum.data?.kind), style),
            shadowColorOpacity: .18,
            icon: true,
            iconText: (datum) => relationNodeText(
              String(datum.data?.label ?? datum.id),
              Number(datum.data?.count ?? 0),
            ),
            iconFill: cssColor(style, '--color-surface', '#fff'),
            iconFontSize: 12,
            iconFontWeight: 700,
            iconLineHeight: 18,
            iconTextAlign: 'center',
            iconTextBaseline: 'middle',
            label: false,
            badge: false,
          },
          state: {
            selected: {
              fillOpacity: 1,
              halo: true,
              haloLineWidth: 16,
              haloStrokeOpacity: .26,
              lineWidth: 3.5,
              stroke: cssColor(style, '--color-focus', '#2772c5'),
              shadowBlur: 22,
              shadowColor: cssColor(style, '--color-focus', '#2772c5'),
              shadowColorOpacity: .34,
            },
            active: {
              fillOpacity: 1,
              halo: true,
              haloLineWidth: 12,
              haloStrokeOpacity: .2,
              opacity: 1,
              lineWidth: 3,
              shadowBlur: 18,
            },
            // Selection and hover should reveal a neighbourhood, not turn the
            // rest of the graph into nearly invisible dust in dark mode.
            inactive: { opacity: .58, labelOpacity: .5 },
          },
          animation: {
            state: [
              { fields: ['fill', 'fillOpacity', 'stroke', 'lineWidth', 'opacity', 'shadowBlur'], duration: 160, easing: 'cubic-bezier(0.23, 1, 0.32, 1)' },
              { fields: ['opacity'], shape: 'label', duration: 140, easing: 'cubic-bezier(0.23, 1, 0.32, 1)' },
              { fields: ['strokeOpacity', 'lineWidth'], shape: 'halo', duration: 180, easing: 'cubic-bezier(0.23, 1, 0.32, 1)' },
            ],
          },
        },
        edge: {
          type: 'quadratic',
          style: {
            stroke: cssColor(style, '--color-border-strong', '#aebdb4'),
            opacity: .42,
            lineWidth: (datum) => edgeWidth(Number(datum.data?.weight ?? 0), Number(datum.data?.evidenceCount ?? 0)),
            curveOffset: (datum: EdgeData) => edgeCurveOffset(String(datum.id)),
            curvePosition: .5,
            endArrow: true,
            endArrowSize: 5,
            labelText: '',
          },
          state: {
            active: {
              stroke: cssColor(style, '--color-accent', '#0b756c'),
              opacity: 1,
              lineWidth: 2.8,
              halo: true,
              haloLineWidth: 9,
              haloStrokeOpacity: .12,
              labelText: (datum) => truncate(String(datum.data?.label ?? ''), 20),
              labelFill: cssColor(style, '--color-text-secondary', '#526159'),
              labelBackground: true,
              labelBackgroundFill: cssColor(style, '--color-surface', '#fff'),
              labelBackgroundFillOpacity: .92,
              labelBackgroundPadding: [3, 5, 3, 5],
            },
            inactive: { opacity: .06 },
          },
          animation: {
            state: [
              { fields: ['stroke', 'strokeOpacity', 'opacity', 'lineWidth'], duration: 160, easing: 'cubic-bezier(0.23, 1, 0.32, 1)' },
              { fields: ['strokeOpacity', 'lineWidth'], shape: 'halo', duration: 180, easing: 'cubic-bezier(0.23, 1, 0.32, 1)' },
              { fields: ['opacity'], shape: 'label', duration: 140, easing: 'cubic-bezier(0.23, 1, 0.32, 1)' },
            ],
          },
        },
        plugins: [{
          type: 'tooltip',
          key: 'memory-relation-node-tooltip',
          trigger: 'hover',
          position: 'top-right',
          offset: [14, 12],
          enterable: false,
          enable: (event: IElementEvent) => event.targetType === 'node',
          getContent: (_event: IElementEvent, items: ElementDatum[]) => relationTooltipContent(
            (items[0]?.data ?? {}) as Record<string, unknown>,
          ),
          onOpenChange: () => undefined,
        }],
        behaviors: [
          'drag-element-force',
          'drag-canvas',
          { type: 'zoom-canvas', sensitivity: 1.15, minZoom: .16, maxZoom: 4 },
          {
            type: 'hover-activate',
            degree: 1,
            inactiveState: 'inactive',
            animation: motionDuration(140) > 0,
          },
        ],
        });
        graph = activeGraph;
        activeGraph.on('node:click', (event) => {
          const id = eventTargetId((event as { target?: unknown }).target);
          if (!id) return;
          onSelectRef.current(id);
          void focusNode(activeGraph, id);
        });
        activeGraph.on('node:dblclick', (event) => {
          const id = eventTargetId((event as { target?: unknown }).target);
          if (id) void focusNode(activeGraph, id, true);
        });
        activeGraph.on('canvas:click', () => onSelectRef.current(''));
        await activeGraph.render();
        if (cancelled) { activeGraph.destroy(); return; }
        await fitWhenVisible(activeGraph);
        if (cancelled) { activeGraph.destroy(); return; }
        graphRef.current = activeGraph;
        setReadyVersion((value) => value + 1);
      } catch {
        graph?.destroy();
        container.replaceChildren();
        if (!cancelled) {
          failed = true;
          setGraphError(true);
        }
      } finally {
        initializing = false;
      }
    };

    const resizeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => {
      cancelAnimationFrame(resizeFrame);
      resizeFrame = requestAnimationFrame(() => {
        const graph = graphRef.current;
        if (graph) void fitWhenVisible(graph);
        else void initialize();
      });
    });
    resizeObserver?.observe(container);
    // The relation tab can become visible after its first layout pass. A
    // second frame prevents the graph from fitting against the old zero width.
    settleFrame = requestAnimationFrame(() => requestAnimationFrame(() => void initialize()));
    void initialize();
    return () => {
      cancelled = true;
      cancelAnimationFrame(resizeFrame);
      cancelAnimationFrame(settleFrame);
      resizeObserver?.disconnect();
      graphRef.current?.destroy();
      graphRef.current = null;
      container.replaceChildren();
    };
  }, [enabled, graphData, retryVersion]);

  useEffect(() => {
    const graph = graphRef.current;
    if (!graph) return;
    const states = selectionStates(nodes, edges, selectedId);
    void graph.setElementState(states, motionDuration(160) > 0);
  }, [edges, nodes, readyVersion, selectedId]);

  const invoke = (action: (graph: Graph) => Promise<void>) => {
    const graph = graphRef.current;
    if (graph) void action(graph);
  };
  const ready = readyVersion > 0;

  return (
    <div
      className="memory-relation-canvas"
      data-cluster-count={graphData.clusterCount}
      data-layout="clustered-force-network"
      data-node-count={nodes.length}
      data-ready={ready || undefined}
      data-renderer="g6"
      data-render-error={graphError || undefined}
    >
      <div className="memory-relation-canvas__surface" ref={containerRef} />
      {selectedNode ? (
        <div className="memory-relation-canvas__focus" role="status">
          <span>聚焦查看</span>
          <strong>{selectedNode.label}</strong>
          <small>{selectedNode.connections} 条直接关系</small>
          <Button
            aria-label="退出节点聚焦"
            leadingIcon={<RotateCcw size={13} />}
            onClick={() => {
              onSelect('');
              invoke((graph) => fitReadableView(graph));
            }}
            size="small"
            variant="quiet"
          >显示全部</Button>
        </div>
      ) : null}
      <div className="memory-relation-canvas__controls" aria-label="关系图视口控制">
        <Button aria-label="放大关系图" disabled={!ready} leadingIcon={<ZoomIn size={15} />} onClick={() => invoke((graph) => graph.zoomBy(1.25, { duration: motionDuration(140) }))} size="small" title="放大" variant="quiet" />
        <Button aria-label="缩小关系图" disabled={!ready} leadingIcon={<ZoomOut size={15} />} onClick={() => invoke((graph) => graph.zoomBy(.8, { duration: motionDuration(140) }))} size="small" title="缩小" variant="quiet" />
        <Button aria-label="显示完整关系图" disabled={!ready} leadingIcon={<Maximize2 size={15} />} onClick={() => invoke((graph) => fitReadableView(graph))} size="small" title="适应画布" variant="quiet" />
        <Button aria-label="定位所选节点" disabled={!ready || !selectedId} leadingIcon={<Focus size={15} />} onClick={() => selectedId && invoke((graph) => focusNode(graph, selectedId))} size="small" title="定位所选节点" variant="quiet" />
      </div>
      <span aria-hidden="true" className="memory-relation-canvas__hint">拖拽整理 · 滚轮缩放 · 悬浮预览 · 双击放大</span>
      {graphError ? (
        <div className="memory-relation-canvas__error" role="alert">
          <CircleAlert aria-hidden="true" size={18} />
          <span>
            <strong>关系图暂时无法布局。</strong>
            左侧节点列表仍可使用。
          </span>
          <Button
            aria-label="重新布局关系图"
            onClick={() => setRetryVersion((value) => value + 1)}
            size="small"
            variant="secondary"
          >重新布局</Button>
        </div>
      ) : !ready ? <span className="memory-relation-canvas__loading">正在布局关系…</span> : null}
    </div>
  );
});

function selectionStates(nodes: readonly MemoryRelationNode[], edges: readonly MemoryRelationEdge[], selectedId: string) {
  const states: Record<string, string[]> = {};
  for (const node of nodes) states[node.id] = selectedId ? ['inactive'] : [];
  for (const edge of edges) states[edge.id] = selectedId ? ['inactive'] : [];
  if (!selectedId) return states;
  states[selectedId] = ['selected'];
  for (const edge of edges) {
    if (edge.source !== selectedId && edge.target !== selectedId) continue;
    states[edge.id] = ['active'];
    states[edge.source === selectedId ? edge.target : edge.source] = ['active'];
  }
  return states;
}

function nodeSize(count: number, connections: number) {
  return Math.min(92, 68 + Math.log2(Math.max(1, count) + 1) * 3.8 + Math.min(8, connections));
}

function edgeWidth(weight: number, evidenceCount: number) {
  return Math.max(.8, Math.min(3.4, .8 + weight * 1.1 + Math.log2(Math.max(1, evidenceCount)) * .28));
}

function kindColor(kind: string, style: CSSStyleDeclaration) {
  const variable = ({ tag: '--color-accent', group: '--color-info', book: '--color-warning' } as Record<string, string>)[kind];
  return cssColor(style, variable ?? '--color-border-strong', '#789087');
}

function cssColor(style: CSSStyleDeclaration, variable: string, fallback: string) {
  return style.getPropertyValue(variable).trim() || fallback;
}

function eventTargetId(target: unknown) {
  return typeof target === 'object' && target !== null && 'id' in target ? String(target.id) : '';
}

function truncate(value: string, length: number) {
  return value.length > length ? `${value.slice(0, length - 1)}…` : value;
}

async function focusNode(graph: Graph, id: string, magnify = false) {
  await graph.focusElement(id, { duration: motionDuration(180) });
  if (magnify) {
    await graph.zoomTo(Math.max(1.18, Math.min(1.5, graph.getZoom() * 1.22)), {
      duration: motionDuration(220),
    });
  }
}

interface RelationLayoutNode {
  _original?: {
    cluster?: unknown;
    clusterAnchorX?: unknown;
    clusterAnchorY?: unknown;
    data?: Record<string, unknown>;
  };
}

function relationGraphData(
  nodes: readonly MemoryRelationNode[],
  edges: readonly MemoryRelationEdge[],
) {
  const clusters = relationClusters(nodes, edges);
  const clusterIds = [...new Set(nodes.map((node) => clusters.get(node.id) ?? 'unconnected'))];
  const clusterCount = clusterIds.length;
  const columns = Math.max(1, Math.ceil(Math.sqrt(clusterCount * 1.8)));
  const clusterIndexes = new Map(clusterIds.map((id, index) => [id, index]));
  const nodesByCluster = new Map<string, MemoryRelationNode[]>();
  for (const node of nodes) {
    const cluster = clusters.get(node.id) ?? 'unconnected';
    const group = nodesByCluster.get(cluster) ?? [];
    group.push(node);
    nodesByCluster.set(cluster, group);
  }

  return {
    clusterCount,
    nodes: nodes.map((node) => {
      const cluster = clusters.get(node.id) ?? 'unconnected';
      const clusterIndex = clusterIndexes.get(cluster) ?? 0;
      const siblings = nodesByCluster.get(cluster) ?? [node];
      const siblingIndex = siblings.findIndex((sibling) => sibling.id === node.id);
      const anchorX = 180 + (clusterIndex % columns) * 360;
      const anchorY = 160 + Math.floor(clusterIndex / columns) * 300;
      const angle = (Math.PI * 2 * siblingIndex) / Math.max(1, siblings.length) - Math.PI / 2;
      const radius = siblings.length > 1 ? Math.min(116, 42 + siblings.length * 12) : 0;
      return {
        id: node.id,
        cluster,
        clusterAnchorX: anchorX,
        clusterAnchorY: anchorY,
        data: { ...node, degree: node.connections },
        style: {
          x: anchorX + Math.cos(angle) * radius,
          y: anchorY + Math.sin(angle) * radius,
        },
      };
    }),
    edges: edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      data: { ...edge },
    })),
  };
}

function relationClusters(
  nodes: readonly MemoryRelationNode[],
  edges: readonly MemoryRelationEdge[],
) {
  const neighbours = new Map(nodes.map((node) => [node.id, new Set<string>()]));
  for (const edge of edges) {
    neighbours.get(edge.source)?.add(edge.target);
    neighbours.get(edge.target)?.add(edge.source);
  }
  const clusters = new Map<string, string>();
  let connectedIndex = 0;
  for (const node of nodes) {
    if (clusters.has(node.id)) continue;
    if ((neighbours.get(node.id)?.size ?? 0) === 0) {
      clusters.set(node.id, 'unconnected');
      continue;
    }
    const cluster = `network-${connectedIndex++}`;
    const pending = [node.id];
    while (pending.length) {
      const id = pending.pop()!;
      if (clusters.has(id)) continue;
      clusters.set(id, cluster);
      for (const neighbour of neighbours.get(id) ?? []) {
        if (!clusters.has(neighbour)) pending.push(neighbour);
      }
    }
  }
  return clusters;
}

function relationCluster(node: RelationLayoutNode) {
  return String(node._original?.cluster ?? 'network');
}

function relationClusterAnchor(node: RelationLayoutNode, axis: 'x' | 'y') {
  return Number(axis === 'x'
    ? node._original?.clusterAnchorX ?? 0
    : node._original?.clusterAnchorY ?? 0);
}

function relationCollisionRadius(node: RelationLayoutNode) {
  const count = Number(node._original?.data?.count ?? 0);
  const connections = Number(node._original?.data?.connections ?? 0);
  return nodeSize(count, connections) / 2 + 22;
}

function relationNodeText(label: string, count: number) {
  return `${truncate(label, 8)}\n${count} 条`;
}

function edgeCurveOffset(id: string) {
  const score = [...id].reduce((total, character) => total + character.charCodeAt(0), 0);
  return (score % 2 ? 1 : -1) * (12 + (score % 4) * 3);
}

function relationTooltipContent(data: Record<string, unknown>): HTMLElement {
  const root = document.createElement('div');
  root.className = 'memory-relation-tooltip';

  const eyebrow = document.createElement('span');
  eyebrow.className = 'memory-relation-tooltip__eyebrow';
  eyebrow.textContent = kindLabel(String(data.kind ?? ''));

  const title = document.createElement('strong');
  title.textContent = String(data.label ?? '未命名节点');

  const description = document.createElement('p');
  description.textContent = String(data.description || '暂无说明。');

  const metrics = document.createElement('div');
  metrics.className = 'memory-relation-tooltip__metrics';
  for (const value of [
    String(data.metricLabel || `${Number(data.count ?? 0)} 个成员`),
    `${Number(data.connections ?? 0)} 条关系`,
    String(data.source || '本地记忆'),
    String(data.status || '使用中'),
  ]) {
    const item = document.createElement('span');
    item.textContent = value;
    metrics.append(item);
  }

  const hint = document.createElement('small');
  hint.textContent = '点击聚焦并查看完整详情';
  root.append(eyebrow, title, description, metrics, hint);
  return root;
}

function kindLabel(kind: string) {
  return ({ tag: '标签', group: '分组', book: '长期主题' } as Record<string, string>)[kind] ?? '记忆节点';
}

function motionDuration(duration: number) {
  if (typeof window === 'undefined') return 0;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
    || document.documentElement.dataset.reduceMotion === 'true'
    ? 0
    : duration;
}

const MAX_READABLE_ZOOM = 1.08;

async function fitReadableView(graph: Graph) {
  await graph.fitView(
    { when: 'always', direction: 'both' },
    { duration: motionDuration(220) },
  );
  if (graph.getZoom() > MAX_READABLE_ZOOM) {
    await graph.zoomTo(MAX_READABLE_ZOOM, { duration: motionDuration(160) });
    await graph.fitCenter({ duration: motionDuration(120) });
  }
}
