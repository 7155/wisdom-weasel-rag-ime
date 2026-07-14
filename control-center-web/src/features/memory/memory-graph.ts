const GRAPH_COLORS = {
  blue: 'var(--color-info)',
  cyan: 'var(--color-accent)',
  teal: 'var(--color-accent)',
  green: 'var(--color-success)',
  mint: 'var(--color-success)',
  yellow: 'var(--color-warning)',
  orange: 'var(--color-warning)',
  red: 'var(--color-danger)',
  pink: 'var(--color-danger)',
  purple: 'var(--color-info)',
  gray: 'var(--color-text-tertiary)',
  grey: 'var(--color-text-tertiary)',
} as const;

const TAG_GRAPH_WIDTH = 1_000;
const TAG_GRAPH_HEIGHT = 540;
const BIPARTITE_GRAPH_WIDTH = 1_000;
const MIN_BIPARTITE_GRAPH_HEIGHT = 620;
const BIPARTITE_CONTENT_TOP = 72;
const BIPARTITE_CONTENT_BOTTOM = 48;
const BIPARTITE_NODE_GAP = 12;
const MAX_TAG_GRAPH_NODES = 24;
const MAX_BIPARTITE_GROUPS = 10;
const MAX_BIPARTITE_TAGS = 12;

export interface ParsedMemoryGraph {
  groups: MemoryGroupNode[];
  tags: MemoryTagNode[];
  truncated: boolean;
}

export interface MemoryTagConnection {
  targetId: string;
  targetLabel: string;
  type: string;
  weight: number;
  evidenceCount: number;
}

export interface MemoryTagNode {
  id: string;
  entityId: string;
  label: string;
  description: string;
  aliases: string[];
  itemCount: number;
  edgeCount: number;
  color: string;
  connections: MemoryTagConnection[];
  presentOnTagGraph: boolean;
}

export interface MemoryGroupNode {
  id: string;
  entityId: string;
  label: string;
  note: string;
  tagIds: string[];
  tags: string[];
  eventCount: number;
  color: string;
}

export interface PositionedTagNode extends MemoryTagNode {
  x: number;
  y: number;
  radius: number;
}

export interface TagGraphEdge {
  source: string;
  target: string;
  type: string;
  weight: number;
  evidenceCount: number;
  strokeWidth: number;
}

export interface TagGraphLayout {
  width: number;
  height: number;
  nodes: PositionedTagNode[];
  edges: TagGraphEdge[];
  clipped: boolean;
}

export interface PositionedGroupNode extends MemoryGroupNode {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface PositionedBipartiteTagNode extends MemoryTagNode {
  x: number;
  y: number;
  radius: number;
}

export interface BipartiteGraphEdge {
  groupId: string;
  tagId: string;
}

export interface BipartiteGraphLayout {
  width: number;
  height: number;
  groups: PositionedGroupNode[];
  tags: PositionedBipartiteTagNode[];
  edges: BipartiteGraphEdge[];
  clipped: boolean;
}

interface GraphNode {
  id: string;
  entityId: string;
  kind: 'tag' | 'group' | 'atom' | 'book' | 'phrase';
  label: string;
  description: string;
  color: string;
  memberCount: number;
  edgeCount: number;
}

interface GraphEdge {
  id: string;
  kind: 'tagRelation' | 'groupMember';
  sourceId: string;
  targetId: string;
  relation: string;
  weight: number;
  evidenceCount: number;
}

export function parseMemoryGraph(payload: unknown): ParsedMemoryGraph {
  if (!isRecord(payload)) return { groups: [], tags: [], truncated: false };
  const plane = payload.plane === 'tags' || payload.plane === 'groups' ? payload.plane : null;
  if (payload.schemaVersion !== 'rag-ime.memory-graph.v1' || !plane) {
    return { groups: [], tags: [], truncated: false };
  }

  const rawNodes = Array.isArray(payload.nodes) ? payload.nodes : [];
  const rawEdges = Array.isArray(payload.edges) ? payload.edges : [];
  const graphNodes = rawNodes.map(parseGraphNode).filter((node): node is GraphNode => node !== null);
  const graphNodeById = new Map(graphNodes.map((node) => [node.id, node]));
  const graphEdges = rawEdges
    .map(parseGraphEdge)
    .filter((edge): edge is GraphEdge => edge !== null)
    .filter((edge) => graphNodeById.has(edge.sourceId) && graphNodeById.has(edge.targetId));
  const tagConnections = tagConnectionsByNode(graphEdges, graphNodeById);
  const tags = graphNodes
    .filter((node) => node.kind === 'tag')
    .map((node) => toTagNode(node, tagConnections.get(node.id) ?? [], plane === 'tags'));
  const groups = graphNodes
    .filter((node) => node.kind === 'group')
    .map((node) => toGroupNode(node, graphEdges, graphNodeById));
  const truncated = isRecord(payload.truncated)
    && (payload.truncated.nodes === true || payload.truncated.edges === true);

  return { groups, tags, truncated };
}

export function mergeMemoryGraphTags(
  primary: readonly MemoryTagNode[],
  secondary: readonly MemoryTagNode[],
): MemoryTagNode[] {
  const merged = new Map<string, MemoryTagNode>();
  for (const tag of [...secondary, ...primary]) {
    const current = merged.get(tag.id);
    merged.set(tag.id, current ? {
      ...tag,
      aliases: [...new Set([...current.aliases, ...tag.aliases])],
      connections: mergeConnections(current.connections, tag.connections),
      presentOnTagGraph: current.presentOnTagGraph || tag.presentOnTagGraph,
    } : tag);
  }
  return [...merged.values()].sort(compareTags);
}

export function safeGraphColor(token: unknown): string {
  if (typeof token !== 'string') return GRAPH_COLORS.blue;
  return GRAPH_COLORS[token.trim().toLowerCase() as keyof typeof GRAPH_COLORS] ?? GRAPH_COLORS.blue;
}

export function tagNodeRadius(itemCount: number): number {
  return clamp(17 + Math.sqrt(nonNegative(itemCount, 1_000_000)) * 2.15, 17, 34);
}

export function tagEdgeStrokeWidth(weight: number, evidenceCount: number): number {
  const safeWeight = clamp(finiteNumber(weight), 0, 4);
  const safeEvidence = nonNegative(evidenceCount, 10_000);
  return clamp(0.8 + safeWeight * 1.45 + Math.log2(safeEvidence + 1) * 0.42, 0.8, 5);
}

export function buildTagGraph(tags: readonly MemoryTagNode[]): TagGraphLayout {
  const sorted = [...tags].sort(compareTags);
  const visible = sorted.slice(0, MAX_TAG_GRAPH_NODES);
  const nodes = visible.map((tag, index) => ({
    ...tag,
    ...tagPosition(index, visible.length),
    radius: tagNodeRadius(tag.itemCount),
  }));
  const visibleIds = new Set(nodes.map((node) => node.id));
  const edgesByKey = new Map<string, TagGraphEdge>();

  for (const node of nodes) {
    for (const connection of node.connections) {
      if (!visibleIds.has(connection.targetId) || connection.targetId === node.id) continue;
      const [source, target] = [node.id, connection.targetId].sort(compareText);
      const key = `${source}\u0000${target}\u0000${connection.type}`;
      const next: TagGraphEdge = {
        source,
        target,
        type: connection.type,
        weight: connection.weight,
        evidenceCount: connection.evidenceCount,
        strokeWidth: tagEdgeStrokeWidth(connection.weight, connection.evidenceCount),
      };
      const current = edgesByKey.get(key);
      if (!current || next.strokeWidth > current.strokeWidth) edgesByKey.set(key, next);
    }
  }

  return {
    width: TAG_GRAPH_WIDTH,
    height: TAG_GRAPH_HEIGHT,
    nodes,
    edges: [...edgesByKey.entries()].sort(([left], [right]) => compareText(left, right)).map(([, edge]) => edge),
    clipped: sorted.length > visible.length,
  };
}

export function buildGroupTagGraph(
  groups: readonly MemoryGroupNode[],
  tags: readonly MemoryTagNode[],
): BipartiteGraphLayout {
  const selectedGroups = [...groups]
    .sort((left, right) => right.eventCount - left.eventCount || compareText(left.label, right.label) || compareText(left.id, right.id))
    .slice(0, MAX_BIPARTITE_GROUPS);
  const tagById = preferredTagById(tags);
  const membership = new Map<string, number>();

  for (const group of selectedGroups) {
    for (const tagId of group.tagIds) {
      if (!tagById.has(tagId)) continue;
      membership.set(tagId, (membership.get(tagId) ?? 0) + 1);
    }
  }

  const tagCandidates = [...membership.entries()].map(([tagId, membershipCount]) => {
    const source = tagById.get(tagId)!;
    return { ...source, membershipCount };
  }).sort((left, right) =>
    right.membershipCount - left.membershipCount
      || right.itemCount - left.itemCount
      || compareText(left.label, right.label)
      || compareText(left.id, right.id));
  const selectedTags = tagCandidates.slice(0, MAX_BIPARTITE_TAGS);
  const visibleTagIds = new Set(selectedTags.map((tag) => tag.id));
  const groupDimensions = selectedGroups.map((group) => groupNodeDimensions(group.eventCount));
  const tagRadii = selectedTags.map((tag) => clamp(tagNodeRadius(tag.itemCount) - 2, 15, 28));
  const graphHeight = bipartiteGraphHeight(groupDimensions, tagRadii);
  const positionedGroups = selectedGroups.map((group, index) => {
    return {
      ...group,
      x: 210,
      y: evenlySpacedY(index, selectedGroups.length, graphHeight),
      ...groupDimensions[index]!,
    };
  });
  const positionedTags = selectedTags.map((tag, index) => ({
    ...tag,
    x: 790,
    y: evenlySpacedY(index, selectedTags.length, graphHeight),
    radius: tagRadii[index]!,
  }));
  const edges: BipartiteGraphEdge[] = [];

  for (const group of positionedGroups) {
    for (const tagId of new Set(group.tagIds)) {
      if (!visibleTagIds.has(tagId)) continue;
      edges.push({ groupId: group.id, tagId });
    }
  }
  edges.sort((left, right) => compareText(`${left.groupId}\u0000${left.tagId}`, `${right.groupId}\u0000${right.tagId}`));

  return {
    width: BIPARTITE_GRAPH_WIDTH,
    height: graphHeight,
    groups: positionedGroups,
    tags: positionedTags,
    edges,
    clipped: groups.length > positionedGroups.length || tagCandidates.length > positionedTags.length,
  };
}

export function truncateGraphLabel(label: string, maxLength = 16): string {
  return label.length > maxLength ? `${label.slice(0, Math.max(1, maxLength - 1))}…` : label;
}

function parseGraphNode(value: unknown): GraphNode | null {
  if (!isRecord(value)) return null;
  const id = requiredString(value.id);
  const entityId = requiredString(value.entityId);
  const label = requiredString(value.label);
  const kind = value.kind;
  if (!id || !entityId || !label || !['tag', 'group', 'atom', 'book', 'phrase'].includes(String(kind))) {
    return null;
  }
  return {
    id,
    entityId,
    kind: kind as GraphNode['kind'],
    label,
    description: optionalString(value.description),
    color: optionalString(value.color) || 'blue',
    memberCount: nonNegative(value.memberCount, 1_000_000),
    edgeCount: nonNegative(value.edgeCount, 10_000),
  };
}

function parseGraphEdge(value: unknown): GraphEdge | null {
  if (!isRecord(value)) return null;
  const id = requiredString(value.id);
  const sourceId = requiredString(value.sourceId);
  const targetId = requiredString(value.targetId);
  const kind = value.kind;
  if (!id || !sourceId || !targetId || (kind !== 'tagRelation' && kind !== 'groupMember')) return null;
  return {
    id,
    kind,
    sourceId,
    targetId,
    relation: optionalString(value.relation) || (kind === 'groupMember' ? 'member' : 'related_to'),
    weight: clamp(finiteNumber(value.weight), 0, 4),
    evidenceCount: nonNegative(value.evidenceCount, 10_000),
  };
}

function tagConnectionsByNode(
  edges: readonly GraphEdge[],
  nodesById: ReadonlyMap<string, GraphNode>,
): Map<string, MemoryTagConnection[]> {
  const result = new Map<string, MemoryTagConnection[]>();
  for (const edge of edges) {
    if (edge.kind !== 'tagRelation') continue;
    const source = nodesById.get(edge.sourceId);
    const target = nodesById.get(edge.targetId);
    if (source?.kind !== 'tag' || target?.kind !== 'tag') continue;
    pushConnection(result, source.id, target, edge);
    pushConnection(result, target.id, source, edge);
  }
  return result;
}

function pushConnection(
  target: Map<string, MemoryTagConnection[]>,
  sourceId: string,
  related: GraphNode,
  edge: GraphEdge,
): void {
  const connections = target.get(sourceId) ?? [];
  connections.push({
    targetId: related.id,
    targetLabel: related.label,
    type: edge.relation,
    weight: edge.weight,
    evidenceCount: edge.evidenceCount,
  });
  target.set(sourceId, connections);
}

function toTagNode(
  node: GraphNode,
  connections: readonly MemoryTagConnection[],
  presentOnTagGraph: boolean,
): MemoryTagNode {
  return {
    id: node.id,
    entityId: node.entityId,
    label: node.label,
    description: node.description,
    aliases: [],
    itemCount: node.memberCount,
    edgeCount: node.edgeCount,
    color: safeGraphColor(node.color),
    connections: [...connections].sort((left, right) => compareText(left.targetId, right.targetId)),
    presentOnTagGraph,
  };
}

function toGroupNode(
  node: GraphNode,
  edges: readonly GraphEdge[],
  nodesById: ReadonlyMap<string, GraphNode>,
): MemoryGroupNode {
  const tagNodes = edges.flatMap((edge) => {
    if (edge.kind !== 'groupMember') return [];
    const relatedId = edge.sourceId === node.id
      ? edge.targetId
      : edge.targetId === node.id ? edge.sourceId : '';
    const related = nodesById.get(relatedId);
    return related?.kind === 'tag' ? [related] : [];
  });
  return {
    id: node.id,
    entityId: node.entityId,
    label: node.label,
    note: node.description,
    tagIds: [...new Set(tagNodes.map((tag) => tag.id))],
    tags: [...new Set(tagNodes.map((tag) => tag.label))],
    eventCount: node.memberCount,
    color: safeGraphColor(node.color),
  };
}

function mergeConnections(
  left: readonly MemoryTagConnection[],
  right: readonly MemoryTagConnection[],
): MemoryTagConnection[] {
  const merged = new Map<string, MemoryTagConnection>();
  for (const connection of [...left, ...right]) {
    const key = `${connection.targetId}\u0000${connection.type}`;
    const current = merged.get(key);
    if (!current || connection.weight > current.weight) merged.set(key, connection);
  }
  return [...merged.values()].sort((a, b) => compareText(a.targetId, b.targetId));
}

function tagPosition(index: number, count: number): { x: number; y: number } {
  if (index === 0) return { x: TAG_GRAPH_WIDTH / 2, y: TAG_GRAPH_HEIGHT / 2 };
  const innerCount = Math.min(7, Math.max(0, count - 1));
  if (index <= innerCount) {
    const angle = -Math.PI / 2 + (2 * Math.PI * (index - 1)) / Math.max(1, innerCount);
    return { x: 500 + Math.cos(angle) * 220, y: 270 + Math.sin(angle) * 132 };
  }
  const outerCount = Math.max(1, count - innerCount - 1);
  const outerIndex = index - innerCount - 1;
  const angle = -Math.PI / 2 + (2 * Math.PI * outerIndex) / outerCount;
  return { x: 500 + Math.cos(angle) * 420, y: 270 + Math.sin(angle) * 218 };
}

function preferredTagById(tags: readonly MemoryTagNode[]): Map<string, MemoryTagNode> {
  const result = new Map<string, MemoryTagNode>();
  for (const tag of [...tags].sort(compareTags)) {
    if (!result.has(tag.id)) result.set(tag.id, tag);
  }
  return result;
}

function groupNodeDimensions(eventCount: number): { width: number; height: number } {
  const scale = Math.sqrt(nonNegative(eventCount, 1_000_000));
  return {
    width: clamp(160 + scale * 4.5, 160, 230),
    height: clamp(31 + scale * 0.75, 31, 44),
  };
}

function bipartiteGraphHeight(
  groups: readonly { height: number }[],
  tagRadii: readonly number[],
): number {
  const tallestGroup = Math.max(0, ...groups.map((group) => group.height));
  const largestTagDiameter = Math.max(0, ...tagRadii.map((radius) => radius * 2));
  const groupHeight = BIPARTITE_CONTENT_TOP + BIPARTITE_CONTENT_BOTTOM
    + Math.max(0, groups.length - 1) * (tallestGroup + BIPARTITE_NODE_GAP);
  const tagHeight = BIPARTITE_CONTENT_TOP + BIPARTITE_CONTENT_BOTTOM
    + Math.max(0, tagRadii.length - 1) * (largestTagDiameter + BIPARTITE_NODE_GAP);
  return Math.ceil(Math.max(MIN_BIPARTITE_GRAPH_HEIGHT, groupHeight, tagHeight));
}

function evenlySpacedY(index: number, count: number, height: number): number {
  if (count <= 1) return height / 2;
  const margin = 52;
  return margin + (index * (height - margin * 2)) / (count - 1);
}

function compareTags(left: MemoryTagNode, right: MemoryTagNode): number {
  return right.edgeCount - left.edgeCount
    || right.itemCount - left.itemCount
    || compareText(left.label, right.label)
    || compareText(left.id, right.id);
}

function compareText(left: string, right: string): number {
  return left.localeCompare(right, 'zh-CN');
}

function requiredString(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const text = value.trim();
  return text || null;
}

function optionalString(value: unknown): string {
  return requiredString(value) ?? '';
}

function finiteNumber(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function nonNegative(value: unknown, maximum: number): number {
  return clamp(finiteNumber(value), 0, maximum);
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
