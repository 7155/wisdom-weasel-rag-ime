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
const BIPARTITE_GRAPH_HEIGHT = 620;
const MAX_TAG_GRAPH_NODES = 24;
const MAX_BIPARTITE_GROUPS = 10;
const MAX_BIPARTITE_TAGS = 12;

export interface MemoryGraphPage<Item> {
  items: Item[];
  hasMore: boolean;
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
  label: string;
  description: string;
  aliases: string[];
  itemCount: number;
  edgeCount: number;
  color: string;
  connections: MemoryTagConnection[];
}

export interface MemoryGroupNode {
  id: string;
  label: string;
  note: string;
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
  presentOnTagPage: boolean;
  normalizedLabel: string;
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

export function parseMemoryTagPage(payload: unknown): MemoryGraphPage<MemoryTagNode> {
  return parsePage(payload, parseTag);
}

export function parseMemoryGroupPage(payload: unknown): MemoryGraphPage<MemoryGroupNode> {
  return parsePage(payload, parseGroup);
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
  const tagByLabel = preferredTagByLabel(tags);
  const membership = new Map<string, { count: number; label: string }>();

  for (const group of selectedGroups) {
    for (const label of group.tags) {
      const normalized = normalizeLabel(label);
      if (!normalized) continue;
      const current = membership.get(normalized);
      membership.set(normalized, { count: (current?.count ?? 0) + 1, label: current?.label ?? label });
    }
  }

  const tagCandidates = [...membership.entries()].map(([normalizedLabel, member]) => {
    const source = tagByLabel.get(normalizedLabel);
    return {
      ...(source ?? missingTag(normalizedLabel, member.label)),
      presentOnTagPage: Boolean(source),
      normalizedLabel,
      membershipCount: member.count,
    };
  }).sort((left, right) =>
    right.membershipCount - left.membershipCount
      || right.itemCount - left.itemCount
      || compareText(left.label, right.label)
      || compareText(left.id, right.id));
  const selectedTags = tagCandidates.slice(0, MAX_BIPARTITE_TAGS);
  const visibleLabels = new Map(selectedTags.map((tag) => [tag.normalizedLabel, tag]));
  const positionedGroups = selectedGroups.map((group, index) => {
    const dimensions = groupNodeDimensions(group.eventCount);
    return {
      ...group,
      x: 210,
      y: evenlySpacedY(index, selectedGroups.length, BIPARTITE_GRAPH_HEIGHT),
      ...dimensions,
    };
  });
  const positionedTags = selectedTags.map((tag, index) => ({
    ...tag,
    x: 790,
    y: evenlySpacedY(index, selectedTags.length, BIPARTITE_GRAPH_HEIGHT),
    radius: clamp(tagNodeRadius(tag.itemCount) - 2, 15, 28),
  }));
  const edges: BipartiteGraphEdge[] = [];

  for (const group of positionedGroups) {
    const seen = new Set<string>();
    for (const label of group.tags) {
      const tag = visibleLabels.get(normalizeLabel(label));
      if (!tag || !seen.add(tag.id)) continue;
      edges.push({ groupId: group.id, tagId: tag.id });
    }
  }
  edges.sort((left, right) => compareText(`${left.groupId}\u0000${left.tagId}`, `${right.groupId}\u0000${right.tagId}`));

  return {
    width: BIPARTITE_GRAPH_WIDTH,
    height: BIPARTITE_GRAPH_HEIGHT,
    groups: positionedGroups,
    tags: positionedTags,
    edges,
    clipped: groups.length > positionedGroups.length || tagCandidates.length > positionedTags.length,
  };
}

export function truncateGraphLabel(label: string, maxLength = 16): string {
  return label.length > maxLength ? `${label.slice(0, Math.max(1, maxLength - 1))}…` : label;
}

function parsePage<Item>(payload: unknown, parseItem: (value: unknown) => Item | null): MemoryGraphPage<Item> {
  if (!isRecord(payload)) return { items: [], hasMore: false };
  const rawItems = Array.isArray(payload.items) ? payload.items : [];
  return {
    items: rawItems.map(parseItem).filter((item): item is Item => item !== null),
    hasMore: typeof payload.nextCursor === 'string' && payload.nextCursor.length > 0,
  };
}

function parseTag(value: unknown): MemoryTagNode | null {
  if (!isRecord(value)) return null;
  const id = requiredString(value.id);
  const label = requiredString(value.tag);
  if (!id || !label) return null;
  const rawConnections = Array.isArray(value.connections) ? value.connections : [];
  return {
    id,
    label,
    description: optionalString(value.description),
    aliases: stringArray(value.aliases),
    itemCount: nonNegative(value.item_count, 1_000_000),
    edgeCount: nonNegative(value.edge_count, 10_000),
    color: safeGraphColor(value.color_token),
    connections: rawConnections.map(parseConnection).filter((connection): connection is MemoryTagConnection => connection !== null),
  };
}

function parseConnection(value: unknown): MemoryTagConnection | null {
  if (!isRecord(value)) return null;
  const targetId = requiredString(value.id);
  if (!targetId) return null;
  return {
    targetId,
    targetLabel: optionalString(value.tag),
    type: optionalString(value.type) || 'related_to',
    weight: clamp(finiteNumber(value.weight), 0, 4),
    evidenceCount: nonNegative(value.evidenceCount, 10_000),
  };
}

function parseGroup(value: unknown): MemoryGroupNode | null {
  if (!isRecord(value)) return null;
  const id = requiredString(value.id);
  if (!id) return null;
  return {
    id,
    label: optionalString(value.title) || id,
    note: optionalString(value.note),
    tags: stringArray(value.tags),
    eventCount: nonNegative(value.event_count, 1_000_000),
    color: safeGraphColor(value.color_token),
  };
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

function preferredTagByLabel(tags: readonly MemoryTagNode[]): Map<string, MemoryTagNode> {
  const result = new Map<string, MemoryTagNode>();
  for (const tag of [...tags].sort(compareTags)) {
    const normalized = normalizeLabel(tag.label);
    if (normalized && !result.has(normalized)) result.set(normalized, tag);
  }
  return result;
}

function missingTag(normalizedLabel: string, label: string): MemoryTagNode {
  return {
    id: `group-tag:${normalizedLabel}`,
    label,
    description: '当前 Group 页包含此标签，但当前标签页未返回对应详情。',
    aliases: [],
    itemCount: 0,
    edgeCount: 0,
    color: GRAPH_COLORS.blue,
    connections: [],
  };
}

function groupNodeDimensions(eventCount: number): { width: number; height: number } {
  const scale = Math.sqrt(nonNegative(eventCount, 1_000_000));
  return {
    width: clamp(160 + scale * 4.5, 160, 230),
    height: clamp(31 + scale * 0.75, 31, 44),
  };
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

function normalizeLabel(value: string): string {
  return value.trim().toLocaleLowerCase('zh-CN');
}

function stringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.map(requiredString).filter((item): item is string => Boolean(item)))];
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
