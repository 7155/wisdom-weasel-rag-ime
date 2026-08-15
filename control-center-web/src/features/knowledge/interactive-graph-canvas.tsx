import type { Graph } from '@antv/g6';
import { Focus, Maximize2, ZoomIn, ZoomOut } from 'lucide-react';
import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { Button } from '@/components/primitives';
import type { KnowledgeGraphEdge, KnowledgeGraphNode, KnowledgeGraphNodeKind } from './api';
import { publicKnowledgeRelationLabel, publicKnowledgeText } from './public-copy';

export type GraphSelection = { type: 'node'; id: string } | { type: 'edge'; id: string } | null;

export const InteractiveGraphCanvas = memo(function InteractiveGraphCanvas({
  edges,
  mode,
  nodes,
  onSelect,
  selection,
}: {
  edges: readonly KnowledgeGraphEdge[];
  mode: 'semantic' | 'structure';
  nodes: readonly KnowledgeGraphNode[];
  onSelect: (selection: GraphSelection) => void;
  selection: GraphSelection;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<Graph | null>(null);
  const onSelectRef = useRef(onSelect);
  const [readyVersion, setReadyVersion] = useState(0);
  const graphData = useMemo(() => formatGraphData(nodes, edges), [edges, nodes]);
  onSelectRef.current = onSelect;

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !graphData.nodes.length) return;
    let cancelled = false;
    let initializing = false;
    let resizeFrame = 0;
    let settleFrame = 0;
    let lastWidth = 0;
    let lastHeight = 0;

    const initialize = async () => {
      if (cancelled || initializing || graphRef.current || container.clientWidth < 2 || container.clientHeight < 2) return;
      initializing = true;
      const { Graph: G6Graph } = await import('./g6-runtime');
      if (cancelled) return;
      const style = getComputedStyle(container);
      const graph = new G6Graph({
        container,
        width: container.clientWidth,
        height: container.clientHeight,
        autoResize: false,
        animation: false,
        data: graphData,
        layout: {
          type: 'd3-force',
          iterations: nodes.length > 60 ? 180 : 240,
          preventOverlap: true,
          collideStrength: .9,
          collideIterations: 2,
          nodeStrength: nodes.length > 60 ? -150 : -220,
          edgeStrength: .68,
          linkDistance: nodes.length > 60 ? 72 : 92,
          centerStrength: .14,
          alphaDecay: .038,
          velocityDecay: .4,
        },
        node: {
          type: 'circle',
          style: {
            size: (datum) => Math.min(20 + Number(datum.data?.degree ?? 0) * 2.4, 44),
            fill: (datum) => kindColor(String(datum.data?.kind), style),
            stroke: cssColor(style, '--color-surface', '#fff'),
            lineWidth: 1.5,
            opacity: .94,
            shadowBlur: 8,
            shadowColor: (datum) => kindColor(String(datum.data?.kind), style),
            shadowColorOpacity: .1,
            labelText: (datum) => truncate(String(datum.data?.label ?? datum.id), 24),
            labelFill: cssColor(style, '--color-text-secondary', '#526159'),
            labelFontSize: 11,
            labelPlacement: 'bottom',
            labelMaxWidth: 126,
            labelWordWrap: true,
          },
          state: {
            selected: {
              lineWidth: 3,
              stroke: cssColor(style, '--color-focus', '#2772c5'),
              shadowBlur: 9,
              shadowColor: cssColor(style, '--color-selection', '#bfe3de'),
              shadowColorOpacity: .32,
            },
            active: { opacity: 1, lineWidth: 2 },
            inactive: { opacity: .16, labelOpacity: .12 },
          },
        },
        edge: {
          type: 'line',
          style: {
            stroke: cssColor(style, '--color-border-strong', '#aebdb4'),
            opacity: .42,
            lineWidth: (datum) => Math.max(.8, Math.min(2, Number(datum.data?.weight ?? .5) * 1.8)),
            endArrow: mode === 'structure',
            endArrowSize: 4,
            labelText: '',
          },
          state: {
            selected: {
              stroke: cssColor(style, '--color-accent', '#0b756c'),
              opacity: 1,
              lineWidth: 2.4,
              labelText: (datum) => truncate(String(datum.data?.label ?? datum.data?.kind ?? ''), 24),
              labelFill: cssColor(style, '--color-text', '#18211d'),
              labelBackground: true,
              labelBackgroundFill: cssColor(style, '--color-surface', '#fff'),
              labelBackgroundLineWidth: 1,
              labelBackgroundStroke: cssColor(style, '--color-border', '#cbd5ce'),
            },
            active: {
              opacity: .92,
              lineWidth: 2,
              labelText: (datum) => truncate(String(datum.data?.label ?? datum.data?.kind ?? ''), 24),
              labelFill: cssColor(style, '--color-text', '#18211d'),
              labelBackground: true,
              labelBackgroundFill: cssColor(style, '--color-surface', '#fff'),
            },
            inactive: { opacity: .05 },
          },
        },
        behaviors: [
          'drag-element-force',
          'drag-canvas',
          { type: 'zoom-canvas', sensitivity: 1.15, minZoom: .12, maxZoom: 4 },
          { type: 'hover-activate', degree: 1 },
          { type: 'auto-adapt-label', throttle: 80, padding: 6, sortNode: { type: 'degree' } },
        ],
      });
      graph.on('node:click', (event) => {
        const id = eventTargetId((event as { target?: unknown }).target);
        if (id) onSelectRef.current({ type: 'node', id });
      });
      graph.on('edge:click', (event) => {
        const id = eventTargetId((event as { target?: unknown }).target);
        if (id) onSelectRef.current({ type: 'edge', id });
      });
      graph.on('canvas:click', () => onSelectRef.current(null));
      await graph.render();
      if (cancelled) { graph.destroy(); return; }
      graphRef.current = graph;
      await graph.fitView({}, { duration: 180 });
      lastWidth = container.clientWidth;
      lastHeight = container.clientHeight;
      setReadyVersion((value) => value + 1);
    };

    const resizeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => {
      cancelAnimationFrame(resizeFrame);
      resizeFrame = requestAnimationFrame(() => {
        const width = container.clientWidth;
        const height = container.clientHeight;
        if (graphRef.current) {
          graphRef.current.resize(width, height);
          const becameVisible = (lastWidth < 2 || lastHeight < 2) && width >= 2 && height >= 2;
          const materiallyChanged = lastWidth > 0 && Math.abs(width - lastWidth) / lastWidth > .2;
          lastWidth = width;
          lastHeight = height;
          if (becameVisible || materiallyChanged) void graphRef.current.fitView({}, { duration: 180 });
        } else void initialize();
      });
    });
    resizeObserver?.observe(container);
    settleFrame = requestAnimationFrame(() => requestAnimationFrame(() => {
      const graph = graphRef.current;
      if (graph && container.clientWidth >= 2 && container.clientHeight >= 2) {
        graph.resize(container.clientWidth, container.clientHeight);
        void graph.fitView({}, { duration: 180 });
      } else void initialize();
    }));
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
  }, [graphData]);

  useEffect(() => {
    const graph = graphRef.current;
    if (!graph) return;
    const state = selectionStates(nodes, edges, selection);
    void graph.setElementState(state, false).then(() => graph.draw());
  }, [edges, nodes, readyVersion, selection]);

  const invoke = (action: (graph: Graph) => Promise<void>) => {
    const graph = graphRef.current;
    if (graph) void action(graph);
  };
  const ready = readyVersion > 0;

  return (
    <div className="knowledge-graph__canvas" aria-label="交互式知识图谱画布" data-edge-mode={mode} data-layout="force-network" data-ready={readyVersion > 0 || undefined} data-renderer="g6">
      <div className="knowledge-graph__g6" ref={containerRef} />
      <div className="knowledge-graph__canvas-controls" aria-label="图谱视口控制">
        <Button aria-label="放大知识图谱" disabled={!ready} leadingIcon={<ZoomIn size={15} />} onClick={() => invoke((graph) => graph.zoomBy(1.25, { duration: 140 }))} size="small" title={ready ? '放大图谱' : '图谱正在加载'} variant="quiet" />
        <Button aria-label="缩小知识图谱" disabled={!ready} leadingIcon={<ZoomOut size={15} />} onClick={() => invoke((graph) => graph.zoomBy(.8, { duration: 140 }))} size="small" title={ready ? '缩小图谱' : '图谱正在加载'} variant="quiet" />
        <Button aria-label="适应画布" disabled={!ready} leadingIcon={<Maximize2 size={15} />} onClick={() => invoke((graph) => graph.fitView({}, { duration: 220 }))} size="small" title={ready ? '让全部节点适应当前画布' : '图谱正在加载'} variant="quiet" />
        <Button aria-label="定位节点" disabled={!ready || selection?.type !== 'node'} leadingIcon={<Focus size={15} />} onClick={() => selection?.type === 'node' && invoke((graph) => graph.focusElement(selection.id, { duration: 180 }))} size="small" title={selection?.type === 'node' ? '把所选节点移到画布中心' : '请先选择一个节点'} variant="quiet" />
      </div>
      <GraphLegend nodes={nodes} />
    </div>
  );
});

function formatGraphData(nodes: readonly KnowledgeGraphNode[], edges: readonly KnowledgeGraphEdge[]) {
  const degree = new Map(nodes.map((node) => [node.id, 0]));
  for (const edge of edges) {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
  }
  return {
    nodes: nodes.map((node) => ({
      id: node.id,
      data: { label: publicKnowledgeText(node.label), kind: node.kind, degree: degree.get(node.id) ?? 0, weight: node.weight ?? 0 },
    })),
    edges: edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      data: { label: publicKnowledgeRelationLabel(edge.label, edge.kind), kind: edge.kind, weight: edge.weight ?? .5 },
    })),
  };
}

function selectionStates(nodes: readonly KnowledgeGraphNode[], edges: readonly KnowledgeGraphEdge[], selection: GraphSelection) {
  const states: Record<string, string[]> = {};
  for (const node of nodes) states[node.id] = selection ? ['inactive'] : [];
  for (const edge of edges) states[edge.id] = selection ? ['inactive'] : [];
  if (!selection) return states;
  if (selection.type === 'node') {
    states[selection.id] = ['selected'];
    for (const edge of edges) {
      if (edge.source !== selection.id && edge.target !== selection.id) continue;
      states[edge.id] = ['active'];
      states[edge.source === selection.id ? edge.target : edge.source] = ['active'];
    }
  } else {
    const edge = edges.find((candidate) => candidate.id === selection.id);
    if (edge) {
      states[selection.id] = ['selected'];
      states[edge.source] = ['active'];
      states[edge.target] = ['active'];
    }
  }
  return states;
}

function GraphLegend({ nodes }: { nodes: readonly KnowledgeGraphNode[] }) {
  const kinds = [...new Set(nodes.map((node) => node.kind))].slice(0, 6);
  return <div className="knowledge-graph__legend" aria-label="节点类型图例">{kinds.map((kind) => <span data-kind={kind} key={kind}><i />{kindLabel(kind)}</span>)}</div>;
}

function cssColor(style: CSSStyleDeclaration, variable: string, fallback: string) { return style.getPropertyValue(variable).trim() || fallback; }
function kindColor(kind: string, style: CSSStyleDeclaration) {
  const variable = ({ document: '--color-accent', chunk: '--color-text-tertiary', topic: '--color-warning', entity: '--color-success', term: '--color-info' } as Record<string, string>)[kind];
  return cssColor(style, variable ?? '--color-border-strong', '#789087');
}
function eventTargetId(target: unknown) { return typeof target === 'object' && target !== null && 'id' in target ? String(target.id) : ''; }
function truncate(value: string, length: number) { return value.length > length ? `${value.slice(0, length - 1)}…` : value; }
function kindLabel(kind: KnowledgeGraphNodeKind) { return ({ document: '文档', chunk: '片段', topic: '主题', entity: '实体', term: '术语', unknown: '节点' } as const)[kind]; }
