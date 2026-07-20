import type { Graph } from '@antv/g6';
import { Focus, Maximize2, ZoomIn, ZoomOut } from 'lucide-react';
import { memo, useEffect, useMemo, useRef, useState } from 'react';
import { Button } from '@/components/primitives';

export interface MemoryRelationNode {
  id: string;
  label: string;
  kind: 'tag' | 'group' | 'book';
  count: number;
  connections: number;
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
  const [readyVersion, setReadyVersion] = useState(0);
  const graphData = useMemo(() => ({
    nodes: nodes.map((node) => ({
      id: node.id,
      data: { ...node, degree: node.connections },
    })),
    edges: edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      data: { ...edge },
    })),
  }), [edges, nodes]);
  onSelectRef.current = onSelect;

  useEffect(() => {
    const container = containerRef.current;
    if (!enabled || !container || graphData.nodes.length === 0) return;
    let cancelled = false;
    let initializing = false;
    let resizeFrame = 0;
    let settleFrame = 0;
    let fitted = false;

    const fitWhenVisible = async (graph: Graph) => {
      if (cancelled || container.clientWidth < 2 || container.clientHeight < 2) return;
      graph.resize(container.clientWidth, container.clientHeight);
      await graph.fitView({}, { duration: fitted ? 120 : 260 });
      fitted = true;
    };

    const initialize = async () => {
      if (cancelled || initializing || graphRef.current || container.clientWidth < 2 || container.clientHeight < 2) return;
      initializing = true;
      const { Graph: G6Graph } = await import('../knowledge/g6-runtime');
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
          iterations: 220,
          preventOverlap: true,
          collideStrength: .92,
          collideIterations: 2,
          nodeStrength: -260,
          edgeStrength: .72,
          linkDistance: 92,
          centerStrength: .16,
          alphaDecay: .035,
          velocityDecay: .38,
        },
        node: {
          type: 'circle',
          style: {
            size: (datum) => nodeSize(Number(datum.data?.count ?? 0), Number(datum.data?.connections ?? 0)),
            fill: (datum) => kindColor(String(datum.data?.kind), style),
            fillOpacity: .22,
            stroke: (datum) => kindColor(String(datum.data?.kind), style),
            lineWidth: 1.6,
            shadowBlur: 8,
            shadowColor: (datum) => kindColor(String(datum.data?.kind), style),
            shadowColorOpacity: .12,
            labelText: (datum) => truncate(String(datum.data?.label ?? datum.id), 22),
            labelFill: cssColor(style, '--color-text', '#18211d'),
            labelFontSize: 12,
            labelFontWeight: 650,
            labelPlacement: 'bottom',
            labelMaxWidth: 142,
            labelWordWrap: true,
            badge: true,
            badgeText: (datum) => String(datum.data?.count ?? 0),
            badgePlacement: 'right-top',
            badgeBackgroundFill: cssColor(style, '--color-surface', '#fff'),
            badgeBackgroundStroke: cssColor(style, '--color-border', '#cbd5ce'),
            badgeFill: cssColor(style, '--color-text-secondary', '#526159'),
            badgeFontSize: 10,
          },
          state: {
            selected: {
              fillOpacity: .35,
              lineWidth: 3,
              stroke: cssColor(style, '--color-focus', '#2772c5'),
              shadowBlur: 18,
              shadowColor: cssColor(style, '--color-focus', '#2772c5'),
              shadowColorOpacity: .3,
            },
            active: { fillOpacity: .3, opacity: 1, lineWidth: 2.4 },
            inactive: { opacity: .16, labelOpacity: .12, badgeOpacity: .08 },
          },
        },
        edge: {
          type: 'line',
          style: {
            stroke: cssColor(style, '--color-border-strong', '#aebdb4'),
            opacity: .34,
            lineWidth: (datum) => edgeWidth(Number(datum.data?.weight ?? 0), Number(datum.data?.evidenceCount ?? 0)),
            endArrow: true,
            endArrowSize: 4,
            labelText: '',
          },
          state: {
            active: {
              stroke: cssColor(style, '--color-accent', '#0b756c'),
              opacity: .95,
              lineWidth: 2.4,
              labelText: (datum) => truncate(String(datum.data?.label ?? ''), 20),
              labelFill: cssColor(style, '--color-text-secondary', '#526159'),
              labelBackground: true,
              labelBackgroundFill: cssColor(style, '--color-surface', '#fff'),
            },
            inactive: { opacity: .04 },
          },
        },
        behaviors: [
          'drag-element-force',
          'drag-canvas',
          { type: 'zoom-canvas', sensitivity: 1.15, minZoom: .16, maxZoom: 4 },
          { type: 'hover-activate', degree: 1 },
          { type: 'auto-adapt-label', throttle: 80, padding: 8, sortNode: { type: 'degree' } },
        ],
      });
      graph.on('node:click', (event) => {
        const id = eventTargetId((event as { target?: unknown }).target);
        if (id) onSelectRef.current(id);
      });
      await graph.render();
      if (cancelled) { graph.destroy(); return; }
      graphRef.current = graph;
      await fitWhenVisible(graph);
      setReadyVersion((value) => value + 1);
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
  }, [enabled, graphData]);

  useEffect(() => {
    const graph = graphRef.current;
    if (!graph) return;
    const states = selectionStates(nodes, edges, selectedId);
    void graph.setElementState(states, false).then(() => graph.draw());
  }, [edges, nodes, readyVersion, selectedId]);

  const invoke = (action: (graph: Graph) => Promise<void>) => {
    const graph = graphRef.current;
    if (graph) void action(graph);
  };
  const ready = readyVersion > 0;

  return (
    <div className="memory-relation-canvas" data-layout="force-network" data-ready={ready || undefined} data-renderer="g6">
      <div className="memory-relation-canvas__surface" ref={containerRef} />
      <div className="memory-relation-canvas__controls" aria-label="关系图视口控制">
        <Button aria-label="放大关系图" disabled={!ready} leadingIcon={<ZoomIn size={15} />} onClick={() => invoke((graph) => graph.zoomBy(1.25, { duration: 140 }))} size="small" title="放大" variant="quiet" />
        <Button aria-label="缩小关系图" disabled={!ready} leadingIcon={<ZoomOut size={15} />} onClick={() => invoke((graph) => graph.zoomBy(.8, { duration: 140 }))} size="small" title="缩小" variant="quiet" />
        <Button aria-label="显示完整关系图" disabled={!ready} leadingIcon={<Maximize2 size={15} />} onClick={() => invoke((graph) => graph.fitView({}, { duration: 220 }))} size="small" title="适应画布" variant="quiet" />
        <Button aria-label="定位所选节点" disabled={!ready || !selectedId} leadingIcon={<Focus size={15} />} onClick={() => selectedId && invoke((graph) => graph.focusElement(selectedId, { duration: 180 }))} size="small" title="定位所选节点" variant="quiet" />
      </div>
      {!ready ? <span className="memory-relation-canvas__loading">正在布局关系…</span> : null}
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
  return Math.min(54, 24 + Math.log2(Math.max(1, count) + 1) * 4 + Math.min(8, connections));
}

function edgeWidth(weight: number, evidenceCount: number) {
  return Math.max(.8, Math.min(3.4, .8 + weight * 1.1 + Math.log2(Math.max(1, evidenceCount)) * .28));
}

function kindColor(kind: string, style: CSSStyleDeclaration) {
  const variable = ({ tag: '--color-info', group: '--color-accent', book: '--color-warning' } as Record<string, string>)[kind];
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
