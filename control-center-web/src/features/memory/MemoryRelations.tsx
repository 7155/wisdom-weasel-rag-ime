import { BookOpen, Boxes, Eye, EyeOff, Network, Search, Tags } from 'lucide-react';
import {
  useDeferredValue,
  useMemo,
  useState,
} from 'react';
import { Button, EmptyState, Input, SegmentedControl, Select } from '@/components/primitives';
import {
  ManagementSection,
  QueryState,
  arrayRecords,
  asRecord,
  numberValue,
  stringValue,
} from '@/features/overview/management-ui';
import { useMemoryEntityQuery, useMemoryGraphQueries } from './api';
import { publicMemorySourceLabel } from './public-copy';
import { MemoryRelationCanvas } from './MemoryRelationCanvas';
import {
  buildGroupBookGraph,
  buildGroupTagGraph,
  buildTagGraph,
  parseMemoryGraph,
  type BookBipartiteGraphLayout,
  type BipartiteGraphLayout,
  type MemoryBookNode,
  type MemoryGroupNode,
  type MemoryTagNode,
  type PositionedBipartiteTagNode,
  type TagGraphLayout,
} from './memory-graph';

type RelationView = 'tags' | 'groups' | 'books';

const relationViews = [
  { value: 'tags', label: '标签关系' },
  { value: 'groups', label: '分组 / 标签' },
  { value: 'books', label: '分组 / 长期主题' },
] as const;

const EMPTY_GROUPS: readonly MemoryGroupNode[] = [];
const EMPTY_BOOKS: readonly MemoryBookNode[] = [];

export function MemoryRelations({ enabled }: { enabled: boolean }) {
  const [view, setView] = useState<RelationView>('tags');
  const [filter, setFilter] = useState('');
  const [source, setSource] = useState('');
  const [selectedTagId, setSelectedTagId] = useState('');
  const [selectedBipartiteKey, setSelectedBipartiteKey] = useState('');
  const [tagFocusId, setTagFocusId] = useState('');
  const [groupFocusId, setGroupFocusId] = useState('');
  const serverQuery = useDeferredValue(filter.trim());
  const queries = useMemoryGraphQueries(enabled, { query: serverQuery, tagFocusId, groupFocusId });
  const tagPayload = useMemo(() => parseMemoryGraph(queries.tags.data), [queries.tags.data]);
  const groupPayload = useMemo(() => parseMemoryGraph(queries.groups.data), [queries.groups.data]);
  const tags = view === 'tags' ? tagPayload.tags : groupPayload.tags;
  const groups = view === 'tags' ? EMPTY_GROUPS : groupPayload.groups;
  const books = view === 'books' ? groupPayload.books : EMPTY_BOOKS;
  const sources = useMemo(() => [...new Set([
    ...tags.map((tag) => tag.source),
    ...groups.map((group) => group.source),
    ...books.map((book) => book.source),
  ].map(publicSourceKey))].sort((left, right) => left.localeCompare(right, 'zh-CN')), [books, groups, tags]);
  // Once the server has applied the query, keep its related neighborhood
  // intact. Re-filtering only the returned seed labels would hide matches on
  // aliases and descriptions that are intentionally resolved by the backend.
  const localFilter = serverQuery ? '' : filter;
  const filtered = useMemo(
    () => filterRelationNodes(tags, groups, books, localFilter, source, view),
    [books, groups, localFilter, source, tags, view],
  );
  const tagGraph = useMemo(() => buildTagGraph(filtered.tags), [filtered.tags]);
  const groupTagGraph = useMemo(
    () => buildGroupTagGraph(filtered.groups, filtered.tags),
    [filtered.groups, filtered.tags],
  );
  const groupBookGraph = useMemo(
    () => buildGroupBookGraph(filtered.groups, filtered.books),
    [filtered.books, filtered.groups],
  );
  const activeQuery = view === 'tags' ? queries.tags : queries.groups;
  const error = activeQuery.error ? new Error('当前关系读取失败，请稍后重试。') : null;
  const pending = activeQuery.isPending;
  const refresh = () => void activeQuery.refetch();
  const payload = view === 'tags' ? tagPayload : groupPayload;
  const visibleEdgeCount = view === 'tags'
    ? tagGraph.edges.length
    : view === 'groups' ? groupTagGraph.edges.length : groupBookGraph.edges.length;

  const selectTag = (id: string) => {
    setFilter('');
    setSource('');
    setSelectedTagId(id);
    setTagFocusId(tags.find((tag) => tag.id === id)?.entityId ?? '');
  };
  const selectBipartite = (key: string) => {
    setFilter('');
    setSource('');
    setSelectedBipartiteKey(key);
    setGroupFocusId(groups.find((group) => groupKey(group.id) === key)?.entityId ?? '');
  };

  return (
    <ManagementSection
      description="查看标签之间，以及分组与标签或长期主题之间已经记录的关系。"
      title="记忆关系"
    >
      <div className="memory-relations">
        <div className="memory-relations__toolbar">
          <SegmentedControl
            aria-label="关系图类型"
            items={relationViews}
            onValueChange={(next) => {
              setView(next);
              setFilter('');
              setSource('');
              setSelectedTagId('');
              setSelectedBipartiteKey('');
              setTagFocusId('');
              setGroupFocusId('');
            }}
            value={view}
          />
          <div className="memory-relations__filters">
            <label className="memory-relations__search">
              <Search aria-hidden="true" size={14} />
              <Input
                aria-label="筛选分组或标签"
                onChange={(event) => {
                  setFilter(event.target.value);
                  setSelectedTagId('');
                  setSelectedBipartiteKey('');
                  setTagFocusId('');
                  setGroupFocusId('');
                }}
                placeholder="搜索全部分组或标签"
                value={filter}
              />
            </label>
            <Select
              aria-label="关系来源"
              className="memory-relations__source"
              onValueChange={setSource}
              options={[
                { value: '', label: '全部来源' },
                ...sources.map((item) => ({ value: item, label: item })),
              ]}
              value={source}
            />
          </div>
        </div>

        <QueryState error={error} isPending={pending} onRetry={refresh}>
          <div className="memory-relations__content">
          <GraphScope
            clipped={payload.truncated || (view === 'tags'
              ? tagGraph.clipped
              : view === 'groups' ? groupTagGraph.clipped : groupBookGraph.clipped)}
            serverEdges={payload.edgeCount}
            serverNodes={payload.nodeCount}
            visibleEdges={visibleEdgeCount}
            visibleNodes={view === 'tags'
              ? tagGraph.nodes.length
              : view === 'groups'
                ? groupTagGraph.groups.length + groupTagGraph.tags.length
                : groupBookGraph.groups.length + groupBookGraph.books.length}
          />

          {view === 'tags' ? (
            filtered.tags.length ? (
              <TagNetwork
                availableNodes={filtered.tags}
                enabled={enabled && view === 'tags'}
                graph={tagGraph}
                onSelect={selectTag}
                selectedId={selectedTagId}
              />
            ) : (
              <EmptyState description="当前筛选没有匹配标签。" icon={Search} title="没有匹配标签" />
            )
          ) : view === 'groups' && (filtered.groups.length || filtered.tags.length) ? (
            <GroupTagNetwork
              availableGroups={filtered.groups}
              availableTags={filtered.tags}
              enabled={enabled && view === 'groups'}
              graph={groupTagGraph}
              onSelect={selectBipartite}
              selectedKey={selectedBipartiteKey}
            />
          ) : view === 'books' && (filtered.groups.length || filtered.books.length) ? (
            <GroupBookNetwork
              availableBooks={filtered.books}
              availableGroups={filtered.groups}
              enabled={enabled && view === 'books'}
              graph={groupBookGraph}
              onSelect={selectBipartite}
              selectedKey={selectedBipartiteKey}
            />
          ) : (
            <EmptyState
              description={view === 'books' ? '当前筛选没有匹配分组或长期主题。' : '当前筛选没有匹配分组或标签。'}
              icon={Search}
              title="没有匹配关系"
            />
          )}
          </div>
        </QueryState>
      </div>
    </ManagementSection>
  );
}

function GraphScope({
  clipped,
  serverEdges,
  serverNodes,
  visibleEdges,
  visibleNodes,
}: {
  clipped: boolean;
  serverEdges: number;
  serverNodes: number;
  visibleEdges: number;
  visibleNodes: number;
}) {
  return (
    <div className="memory-graph__scope" data-clipped={clipped || undefined} role="status">
      <span><Network aria-hidden="true" size={12} /> 共 {serverNodes} 项 · {serverEdges} 条关系</span>
      <span><Tags aria-hidden="true" size={12} /> 当前显示 {visibleNodes} 项 · {visibleEdges} 条关系</span>
      <span>{clipped ? '还有更多关系未显示' : '已显示全部'}</span>
    </div>
  );
}

function TagNetwork({
  availableNodes,
  enabled,
  graph,
  onSelect,
  selectedId,
}: {
  availableNodes: readonly MemoryTagNode[];
  enabled: boolean;
  graph: TagGraphLayout;
  onSelect: (id: string) => void;
  selectedId: string;
}) {
  const [showUnconnected, setShowUnconnected] = useState(false);
  const activeId = availableNodes.some((node) => node.id === selectedId)
    ? selectedId
    : availableNodes[0]?.id ?? '';
  const selected = availableNodes.find((node) => node.id === activeId) ?? null;
  const entity = useMemoryEntityQuery('tag', selected?.entityId ?? '', Boolean(selected));
  const connectedIds = useMemo(
    () => edgeNodeIds(graph.edges.map((edge) => ({ source: edge.source, target: edge.target }))),
    [graph.edges],
  );
  const unconnectedCount = graph.nodes.filter((node) => !connectedIds.has(node.id)).length;
  const visibleNodes = graph.edges.length === 0 || showUnconnected
    ? graph.nodes
    : graph.nodes.filter((node) => connectedIds.has(node.id) || node.id === selectedId);

  return (
    <>
      <div className="memory-explorer">
        <NodeScanList
          activeId={activeId}
          nodes={availableNodes}
          onSelect={onSelect}
          title="标签"
        />
        <div className="memory-explorer__visual">
          <GraphLegend view="tags" />
          <GraphTruthNotice
            edgeCount={graph.edges.length}
            nodeCount={visibleNodes.length}
            onToggleUnconnected={graph.edges.length > 0 && unconnectedCount > 0
              ? () => setShowUnconnected((value) => !value)
              : undefined}
            showUnconnected={showUnconnected}
            unconnectedCount={unconnectedCount}
          />
          <MemoryRelationCanvas
            edges={graph.edges.map((edge) => ({
              id: `tag-edge:${edge.source}:${edge.target}:${edge.type}`,
              source: edge.source,
              target: edge.target,
              label: formatRelation(edge.type),
              weight: edge.weight,
              evidenceCount: edge.evidenceCount,
            }))}
            enabled={enabled}
            nodes={visibleNodes.map((node) => ({
              id: node.id,
              label: node.label,
              kind: 'tag',
              count: node.itemCount,
              connections: node.edgeCount,
              description: node.description,
              metricLabel: `${node.itemCount} 条记忆`,
              source: formatSource(node.source),
              status: formatStatus(node.status),
            }))}
            onSelect={onSelect}
            selectedId={availableNodes.some((node) => node.id === selectedId) ? selectedId : ''}
          />
        </div>
      </div>
      {selected ? (
        <MemoryEntityInspector
          connectionLoadError={entity.connectionLoadError as Error | null}
          entityData={entity.data}
          error={entity.error as Error | null}
          isFetchingNextConnections={entity.isFetchingNextConnections}
          isFetchingNextMembers={entity.isFetchingNextMembers}
          isPending={entity.isPending}
          kind="tag"
          memberLoadError={entity.memberLoadError as Error | null}
          node={selected}
          onLoadMoreConnections={() => void entity.fetchNextConnections()}
          onLoadMoreMembers={() => void entity.fetchNextMembers()}
          onSelectTag={onSelect}
        />
      ) : null}
    </>
  );
}

function GroupTagNetwork({
  availableGroups,
  availableTags,
  enabled,
  graph,
  onSelect,
  selectedKey,
}: {
  availableGroups: readonly MemoryGroupNode[];
  availableTags: readonly MemoryTagNode[];
  enabled: boolean;
  graph: BipartiteGraphLayout;
  onSelect: (key: string) => void;
  selectedKey: string;
}) {
  const [showUnconnected, setShowUnconnected] = useState(false);
  const defaultKey = availableGroups[0]
    ? groupKey(availableGroups[0].id)
    : tagKey(availableTags[0]?.id ?? '');
  const validKeys = new Set([
    ...availableGroups.map((group) => groupKey(group.id)),
    ...availableTags.map((tag) => tagKey(tag.id)),
  ]);
  const activeKey = validKeys.has(selectedKey) ? selectedKey : defaultKey;
  const selectedGroup = activeKey.startsWith('group:')
    ? availableGroups.find((group) => group.id === activeKey.slice(6)) ?? null
    : null;
  const selectedTag = activeKey.startsWith('tag:')
    ? availableTags.find((tag) => tag.id === activeKey.slice(4)) ?? null
    : null;
  const entityKind = selectedGroup ? 'group' : 'tag';
  const entityId = selectedGroup?.entityId ?? selectedTag?.entityId ?? '';
  const entity = useMemoryEntityQuery(entityKind, entityId, Boolean(entityId));
  const graphEdges = useMemo(() => graph.edges.map((edge) => ({
    id: `group-tag:${edge.groupId}:${edge.tagId}`,
    source: groupKey(edge.groupId),
    target: tagKey(edge.tagId),
    label: formatRelation(edge.relation),
    weight: edge.weight,
    evidenceCount: edge.evidenceCount,
  })), [graph.edges]);
  const connectedIds = useMemo(() => edgeNodeIds(graphEdges), [graphEdges]);
  const graphNodes = useMemo(() => [
    ...graph.groups.map((node) => ({ id: groupKey(node.id), label: node.label, kind: 'group' as const, count: node.eventCount, connections: node.edgeCount, description: node.note, metricLabel: `${node.eventCount} 个成员`, source: formatSource(node.source), status: formatStatus(node.status) })),
    ...graph.tags.map((node) => ({ id: tagKey(node.id), label: node.label, kind: 'tag' as const, count: node.itemCount, connections: node.edgeCount, description: node.description, metricLabel: `${node.itemCount} 条记忆`, source: formatSource(node.source), status: formatStatus(node.status) })),
  ], [graph.groups, graph.tags]);
  const unconnectedCount = graphNodes.filter((node) => !connectedIds.has(node.id)).length;
  const visibleNodes = graphEdges.length === 0 || showUnconnected
    ? graphNodes
    : graphNodes.filter((node) => connectedIds.has(node.id) || node.id === selectedKey);

  return (
    <>
      <div className="memory-explorer">
        <BipartiteScanList
          activeKey={activeKey}
          groups={availableGroups}
          onSelect={onSelect}
          tags={availableTags}
        />
        <div className="memory-explorer__visual">
          <GraphLegend view="groups" />
          <GraphTruthNotice
            edgeCount={graphEdges.length}
            nodeCount={visibleNodes.length}
            onToggleUnconnected={graphEdges.length > 0 && unconnectedCount > 0
              ? () => setShowUnconnected((value) => !value)
              : undefined}
            showUnconnected={showUnconnected}
            unconnectedCount={unconnectedCount}
          />
          <MemoryRelationCanvas
            edges={graphEdges}
            enabled={enabled}
            nodes={visibleNodes}
            onSelect={onSelect}
            selectedId={validKeys.has(selectedKey) ? selectedKey : ''}
          />
        </div>
      </div>
      {selectedGroup || selectedTag ? (
        <MemoryEntityInspector
          connectionLoadError={entity.connectionLoadError as Error | null}
          entityData={entity.data}
          error={entity.error as Error | null}
          isFetchingNextConnections={entity.isFetchingNextConnections}
          isFetchingNextMembers={entity.isFetchingNextMembers}
          isPending={entity.isPending}
          kind={entityKind}
          memberLoadError={entity.memberLoadError as Error | null}
          node={selectedGroup ?? selectedTag!}
          onLoadMoreConnections={() => void entity.fetchNextConnections()}
          onLoadMoreMembers={() => void entity.fetchNextMembers()}
          onSelectTag={(id) => onSelect(tagKey(id))}
        />
      ) : null}
    </>
  );
}

function GroupBookNetwork({
  availableBooks,
  availableGroups,
  enabled,
  graph,
  onSelect,
  selectedKey,
}: {
  availableBooks: readonly MemoryBookNode[];
  availableGroups: readonly MemoryGroupNode[];
  enabled: boolean;
  graph: BookBipartiteGraphLayout;
  onSelect: (key: string) => void;
  selectedKey: string;
}) {
  const [showUnconnected, setShowUnconnected] = useState(false);
  const defaultKey = availableGroups[0]
    ? groupKey(availableGroups[0].id)
    : bookKey(availableBooks[0]?.id ?? '');
  const validKeys = new Set([
    ...availableGroups.map((group) => groupKey(group.id)),
    ...availableBooks.map((book) => bookKey(book.id)),
  ]);
  const activeKey = validKeys.has(selectedKey) ? selectedKey : defaultKey;
  const selectedGroup = activeKey.startsWith('group:')
    ? availableGroups.find((group) => group.id === activeKey.slice(6)) ?? null
    : null;
  const selectedBook = activeKey.startsWith('book:')
    ? availableBooks.find((book) => book.id === activeKey.slice(5)) ?? null
    : null;
  const entityKind = selectedGroup ? 'group' : 'book';
  const entityId = selectedGroup?.entityId ?? selectedBook?.entityId ?? '';
  const entity = useMemoryEntityQuery(entityKind, entityId, Boolean(entityId));
  const graphEdges = useMemo(() => graph.edges.map((edge) => ({
    id: `group-book:${edge.groupId}:${edge.bookId}`,
    source: groupKey(edge.groupId),
    target: bookKey(edge.bookId),
    label: formatRelation(edge.relation),
    weight: edge.weight,
    evidenceCount: edge.evidenceCount,
  })), [graph.edges]);
  const connectedIds = useMemo(() => edgeNodeIds(graphEdges), [graphEdges]);
  const graphNodes = useMemo(() => [
    ...graph.groups.map((node) => ({ id: groupKey(node.id), label: node.label, kind: 'group' as const, count: node.eventCount, connections: node.edgeCount, description: node.note, metricLabel: `${node.eventCount} 个成员`, source: formatSource(node.source), status: formatStatus(node.status) })),
    ...graph.books.map((node) => ({ id: bookKey(node.id), label: node.label, kind: 'book' as const, count: node.memberCount, connections: node.edgeCount, description: node.description, metricLabel: `${node.memberCount} 条记忆`, source: formatSource(node.source), status: formatStatus(node.status) })),
  ], [graph.books, graph.groups]);
  const unconnectedCount = graphNodes.filter((node) => !connectedIds.has(node.id)).length;
  const visibleNodes = graphEdges.length === 0 || showUnconnected
    ? graphNodes
    : graphNodes.filter((node) => connectedIds.has(node.id) || node.id === selectedKey);

  return (
    <>
      <div className="memory-explorer">
        <GroupBookScanList
          activeKey={activeKey}
          books={availableBooks}
          groups={availableGroups}
          onSelect={onSelect}
        />
        <div className="memory-explorer__visual">
          <GraphLegend view="books" />
          <GraphTruthNotice
            edgeCount={graphEdges.length}
            nodeCount={visibleNodes.length}
            onToggleUnconnected={graphEdges.length > 0 && unconnectedCount > 0
              ? () => setShowUnconnected((value) => !value)
              : undefined}
            showUnconnected={showUnconnected}
            unconnectedCount={unconnectedCount}
          />
          <MemoryRelationCanvas
            edges={graphEdges}
            enabled={enabled}
            nodes={visibleNodes}
            onSelect={onSelect}
            selectedId={validKeys.has(selectedKey) ? selectedKey : ''}
          />
        </div>
      </div>
      {selectedGroup || selectedBook ? (
        <MemoryEntityInspector
          connectionLoadError={entity.connectionLoadError as Error | null}
          entityData={entity.data}
          error={entity.error as Error | null}
          isFetchingNextConnections={entity.isFetchingNextConnections}
          isFetchingNextMembers={entity.isFetchingNextMembers}
          isPending={entity.isPending}
          kind={entityKind}
          memberLoadError={entity.memberLoadError as Error | null}
          node={selectedGroup ?? selectedBook!}
          onLoadMoreConnections={() => void entity.fetchNextConnections()}
          onLoadMoreMembers={() => void entity.fetchNextMembers()}
          onSelectTag={(id) => onSelect(tagKey(id))}
        />
      ) : null}
    </>
  );
}

function NodeScanList({
  activeId,
  nodes,
  onSelect,
  title,
}: {
  activeId: string;
  nodes: readonly MemoryTagNode[];
  onSelect: (id: string) => void;
  title: string;
}) {
  return (
    <aside className="memory-node-list" aria-label={`${title}节点列表`}>
      <header><strong>{title}</strong><span>{nodes.length}</span></header>
      <div className="memory-node-list__scroll">
        {nodes.map((node) => (
          <button
            aria-label={`${node.label}，${node.itemCount} 条记忆，${node.edgeCount} 个连接，来源 ${formatSource(node.source)}`}
            aria-pressed={activeId === node.id}
            data-selected={activeId === node.id || undefined}
            key={node.id}
            onClick={() => onSelect(node.id)}
            onKeyDown={(event) => {
              if (event.key !== 'Enter' && event.key !== ' ') return;
              event.preventDefault();
              onSelect(node.id);
            }}
            type="button"
          >
            <span><strong>{node.label}</strong><small>{node.description || '无说明'}</small></span>
            <span><b>{node.itemCount}</b><small>{node.edgeCount} 关系 · {formatSource(node.source)}</small></span>
          </button>
        ))}
      </div>
    </aside>
  );
}

function BipartiteScanList({
  activeKey,
  groups,
  onSelect,
  tags,
}: {
  activeKey: string;
  groups: readonly MemoryGroupNode[];
  onSelect: (key: string) => void;
  tags: readonly MemoryTagNode[];
}) {
  return (
    <aside className="memory-node-list memory-node-list--bipartite" aria-label="分组与标签列表">
      <header><strong>分组</strong><span>{groups.length}</span></header>
      <div>
        {groups.map((group) => {
          const key = groupKey(group.id);
          return (
            <button aria-label={`分组 ${group.label}，${group.eventCount} 个成员，来源 ${formatSource(group.source)}`} aria-pressed={activeKey === key} data-selected={activeKey === key || undefined} key={key} onClick={() => onSelect(key)} type="button">
              <span><strong>{group.label}</strong><small>{group.note || '无说明'}</small></span>
              <span><b>{group.eventCount}</b><small>{group.tagIds.length} 标签 · {formatSource(group.source)}</small></span>
            </button>
          );
        })}
      </div>
      <header><strong>标签</strong><span>{tags.length}</span></header>
      <div className="memory-node-list__scroll">
        {tags.map((tag) => {
          const key = tagKey(tag.id);
          return (
            <button aria-label={`标签 ${tag.label}，${tag.itemCount} 条记忆，来源 ${formatSource(tag.source)}`} aria-pressed={activeKey === key} data-selected={activeKey === key || undefined} key={key} onClick={() => onSelect(key)} type="button">
              <span><strong>{tag.label}</strong><small>{tag.description || '无说明'}</small></span>
              <span><b>{tag.itemCount}</b><small>{tag.edgeCount} 关系 · {formatSource(tag.source)}</small></span>
            </button>
          );
        })}
      </div>
    </aside>
  );
}

function GroupBookScanList({
  activeKey,
  books,
  groups,
  onSelect,
}: {
  activeKey: string;
  books: readonly MemoryBookNode[];
  groups: readonly MemoryGroupNode[];
  onSelect: (key: string) => void;
}) {
  return (
    <aside className="memory-node-list memory-node-list--bipartite" aria-label="分组与长期主题列表">
      <header><strong>分组</strong><span>{groups.length}</span></header>
      <div>
        {groups.map((group) => {
          const key = groupKey(group.id);
          return (
            <button aria-label={`分组 ${group.label}，${group.eventCount} 个成员，来源 ${formatSource(group.source)}`} aria-pressed={activeKey === key} data-selected={activeKey === key || undefined} key={key} onClick={() => onSelect(key)} type="button">
              <span><strong>{group.label}</strong><small>{group.note || '无说明'}</small></span>
              <span><b>{group.eventCount}</b><small>{group.bookIds.length} 个长期主题 · {formatSource(group.source)}</small></span>
            </button>
          );
        })}
      </div>
      <header><strong>长期主题</strong><span>{books.length}</span></header>
      <div className="memory-node-list__scroll">
        {books.map((book) => {
          const key = bookKey(book.id);
          return (
            <button aria-label={`长期主题 ${book.label}，${book.memberCount} 条记忆，${book.edgeCount} 个分组，来源 ${formatSource(book.source)}`} aria-pressed={activeKey === key} data-selected={activeKey === key || undefined} key={key} onClick={() => onSelect(key)} type="button">
              <span><strong>{book.label}</strong><small>{book.description || '无说明'}</small></span>
              <span><b>{book.memberCount}</b><small>{book.edgeCount} 分组 · {formatSource(book.source)}</small></span>
            </button>
          );
        })}
      </div>
    </aside>
  );
}

function GraphTruthNotice({
  edgeCount,
  nodeCount,
  onToggleUnconnected,
  showUnconnected = false,
  unconnectedCount = 0,
}: {
  edgeCount: number;
  nodeCount: number;
  onToggleUnconnected?: () => void;
  showUnconnected?: boolean;
  unconnectedCount?: number;
}) {
  return (
    <div className="memory-graph__truth" data-empty={edgeCount === 0 || undefined}>
      <p>
        {edgeCount > 0
          ? `当前显示 ${nodeCount} 项记忆与 ${edgeCount} 条有证据关系。`
          : `${nodeCount} 项记忆目前没有已记录关系。`}
      </p>
      {onToggleUnconnected ? (
        <Button
          aria-label={`${showUnconnected ? '隐藏' : '显示'} ${unconnectedCount} 个未连接节点`}
          leadingIcon={showUnconnected ? <EyeOff size={13} /> : <Eye size={13} />}
          onClick={onToggleUnconnected}
          size="small"
          variant="quiet"
        >{showUnconnected ? '隐藏未连接项' : `查看未连接项 · ${unconnectedCount}`}</Button>
      ) : null}
    </div>
  );
}

function edgeNodeIds(edges: readonly { source: string; target: string }[]) {
  const ids = new Set<string>();
  for (const edge of edges) {
    ids.add(edge.source);
    ids.add(edge.target);
  }
  return ids;
}

function GraphLegend({ view }: { view: RelationView }) {
  return (
    <div className="memory-graph__legend" role="group" aria-label="关系图图例">
      {view === 'tags' ? <span><i data-shape="tag" />标签 · 大小表示记忆量</span> : <span><i data-shape="group" />分组</span>}
      {view === 'groups' ? <span><i data-shape="tag" />标签</span> : null}
      {view === 'books' ? <span><i data-shape="book" />长期主题</span> : null}
      <span><i data-shape="edge" />明确关系 · 同一事实共现</span>
    </div>
  );
}

function MemoryEntityInspector({
  connectionLoadError,
  entityData,
  error,
  isFetchingNextConnections,
  isFetchingNextMembers,
  isPending,
  kind,
  memberLoadError,
  node,
  onLoadMoreConnections,
  onLoadMoreMembers,
  onSelectTag,
}: {
  connectionLoadError: Error | null;
  entityData: unknown;
  error: Error | null;
  isFetchingNextConnections: boolean;
  isFetchingNextMembers: boolean;
  isPending: boolean;
  kind: 'tag' | 'group' | 'book';
  memberLoadError: Error | null;
  node: MemoryTagNode | MemoryGroupNode | MemoryBookNode | PositionedBipartiteTagNode;
  onLoadMoreConnections: () => void;
  onLoadMoreMembers: () => void;
  onSelectTag: (id: string) => void;
}) {
  const payload = asRecord(entityData);
  const entity = asRecord(payload.entity);
  const attributes = asRecord(payload.attributes);
  const connectionPage = asRecord(payload.connections);
  const memberPage = asRecord(payload.members);
  const connections = arrayRecords(connectionPage.items);
  const members = arrayRecords(memberPage.items);
  const aliases = safePublicStringList(attributes.aliases);
  const attributeTags = safePublicStringList(attributes.tags);
  const memberCount = numberValue(
    entity.memberCount,
    'itemCount' in node ? node.itemCount : 'eventCount' in node ? node.eventCount : node.memberCount,
  );
  const edgeCount = numberValue(entity.edgeCount, node.edgeCount);
  const source = formatSource(stringValue(entity.source, node.source));

  return (
    <section className="memory-entity" aria-label={`${node.label} 详情`} aria-live="polite">
      <div className="memory-entity__summary">
        <span className="memory-graph__eyebrow">
          {kind === 'group'
            ? <Boxes aria-hidden="true" size={13} />
            : kind === 'book' ? <BookOpen aria-hidden="true" size={13} /> : <Tags aria-hidden="true" size={13} />}
          {' '}已选{kind === 'group' ? '分组' : kind === 'book' ? '长期主题' : '标签'}
        </span>
        <h3>{node.label}</h3>
        <p>{stringValue(entity.description, 'note' in node ? node.note : node.description) || '暂无说明。'}</p>
        <dl>
          <div><dt>成员</dt><dd>{memberCount}</dd></div>
          <div><dt>关系</dt><dd>{edgeCount}</dd></div>
          <div><dt>来源</dt><dd>{source}</dd></div>
          <div><dt>状态</dt><dd>{formatStatus(stringValue(entity.status, node.status))}</dd></div>
          <div><dt>质量</dt><dd>{formatQuality(entity.qualityScore ?? node.qualityScore)}</dd></div>
          <div><dt>更新</dt><dd>{formatTimestamp(numberValue(entity.updatedAtMs, node.updatedAtMs))}</dd></div>
        </dl>
        {aliases.length || attributeTags.length ? (
          <div className="memory-entity__attributes">
            {aliases.map((alias) => <span key={`alias:${alias}`}>别名 · {alias}</span>)}
            {attributeTags.map((tag) => <span key={`tag:${tag}`}>标签 · {tag}</span>)}
          </div>
        ) : null}
        {isPending ? <p role="status">正在读取实体详情…</p> : null}
        {error ? <p className="memory-entity__error" role="alert">实体详情读取失败，请稍后重试。</p> : null}
      </div>

      <EntityRows
        emptyText={kind === 'group'
          ? '这个分组没有独立关系；成员关系会在下方显示。'
          : kind === 'book' ? '这个长期主题尚未加入分组。' : '这个标签暂无已记录关系。'}
        hasMore={connectionPage.hasMore === true && Boolean(stringValue(connectionPage.nextCursor))}
        isLoadingMore={isFetchingNextConnections}
        items={connections}
        loadError={connectionLoadError}
        onLoadMore={onLoadMoreConnections}
        onSelectTag={onSelectTag}
        title="已存关系"
      />
      <EntityRows
        emptyText={kind === 'book' ? '为保护原始记忆内容，此处只显示成员计数。' : '暂无成员。'}
        hasMore={memberPage.hasMore === true && Boolean(stringValue(memberPage.nextCursor))}
        isLoadingMore={isFetchingNextMembers}
        items={members}
        loadError={memberLoadError}
        onLoadMore={onLoadMoreMembers}
        onSelectTag={onSelectTag}
        title={`成员 · 当前 ${members.length} / ${memberCount}`}
      />
    </section>
  );
}

function EntityRows({
  emptyText,
  hasMore = false,
  isLoadingMore = false,
  items,
  loadError,
  onLoadMore,
  onSelectTag,
  title,
}: {
  emptyText: string;
  hasMore?: boolean;
  isLoadingMore?: boolean;
  items: readonly Record<string, unknown>[];
  loadError?: Error | null;
  onLoadMore?: () => void;
  onSelectTag: (id: string) => void;
  title: string;
}) {
  return (
    <section className="memory-entity__rows">
      <header><h3>{title}</h3>{hasMore ? <span>还有更多</span> : null}</header>
      {items.length ? items.map((item, index) => {
        const related = asRecord(item.node);
        const edge = asRecord(item.edge);
        const relatedKind = stringValue(related.kind, 'memory');
        const relatedId = stringValue(related.id);
        const tagSelectable = relatedKind === 'tag' && relatedId;
        return (
          <div className="memory-entity__row" key={stringValue(edge.id, `${relatedId}:${index}`)}>
            <span>
              {tagSelectable ? (
                <button onClick={() => onSelectTag(relatedId)} type="button">{stringValue(related.label, '未命名标签')}</button>
              ) : <strong>{stringValue(related.label, '未命名成员')}</strong>}
              <small>{formatEntityKind(relatedKind)} · {formatStatus(stringValue(related.status))}</small>
            </span>
            <span><b>{formatRelation(stringValue(edge.relation))}</b><small>{numberValue(edge.evidenceCount) > 1 ? `${numberValue(edge.evidenceCount)} 条记录` : '已记录'}</small></span>
            <span><b>{formatSource(stringValue(related.source))}</b><small>{formatSource(stringValue(edge.source))}</small></span>
          </div>
        );
      }) : <p className="memory-entity__empty">{emptyText}</p>}
      {hasMore && onLoadMore ? (
        <button
          className="memory-entity__load-more"
          disabled={isLoadingMore}
          onClick={onLoadMore}
          type="button"
        >
          {isLoadingMore ? '正在加载…' : '加载更多'}
        </button>
      ) : null}
      {loadError ? <p className="memory-entity__error" role="alert">更多内容读取失败，请稍后重试。</p> : null}
    </section>
  );
}

function filterRelationNodes(
  tags: readonly MemoryTagNode[],
  groups: readonly MemoryGroupNode[],
  books: readonly MemoryBookNode[],
  filter: string,
  source: string,
  view: RelationView,
): { tags: MemoryTagNode[]; groups: MemoryGroupNode[]; books: MemoryBookNode[] } {
  const query = filter.trim().toLocaleLowerCase('zh-CN');
  const sourceMatch = (node: MemoryTagNode | MemoryGroupNode | MemoryBookNode) => !source || publicSourceKey(node.source) === source;
  const textMatch = (node: MemoryTagNode | MemoryGroupNode | MemoryBookNode) => {
    if (!query) return true;
    const description = 'note' in node ? node.note : node.description;
    return `${node.label}\n${description}\n${node.source}\n${node.project}`.toLocaleLowerCase('zh-CN').includes(query);
  };
  const matchedTags = tags.filter((tag) => sourceMatch(tag) && textMatch(tag));
  if (view === 'tags') return { tags: matchedTags, groups: [], books: [] };
  const matchedGroups = groups.filter((group) => sourceMatch(group) && textMatch(group));
  if (view === 'books') {
    const matchedBooks = books.filter((book) => sourceMatch(book) && textMatch(book));
    if (!query) return { tags: [], groups: groups.filter(sourceMatch), books: books.filter(sourceMatch) };
    const bookIds = new Set(matchedBooks.map((book) => book.id));
    const groupIds = new Set(matchedGroups.map((group) => group.id));
    for (const group of groups) {
      if (group.bookIds.some((bookId) => bookIds.has(bookId))) groupIds.add(group.id);
    }
    for (const group of matchedGroups) {
      for (const bookId of group.bookIds) bookIds.add(bookId);
    }
    return {
      tags: [],
      groups: groups.filter((group) => sourceMatch(group) && groupIds.has(group.id)),
      books: books.filter((book) => sourceMatch(book) && bookIds.has(book.id)),
    };
  }
  if (!query) return { tags: tags.filter(sourceMatch), groups: groups.filter(sourceMatch), books: [] };
  const tagIds = new Set(matchedTags.map((tag) => tag.id));
  const groupIds = new Set(matchedGroups.map((group) => group.id));
  for (const group of groups) {
    if (group.tagIds.some((tagId) => tagIds.has(tagId))) groupIds.add(group.id);
  }
  for (const group of matchedGroups) {
    for (const tagId of group.tagIds) tagIds.add(tagId);
  }
  return {
    tags: tags.filter((tag) => sourceMatch(tag) && tagIds.has(tag.id)),
    groups: groups.filter((group) => sourceMatch(group) && groupIds.has(group.id)),
    books: [],
  };
}

function formatQuality(value: unknown): string {
  const score = typeof value === 'number' && Number.isFinite(value) ? value : 0;
  return `${Math.round(Math.max(0, Math.min(1, score)) * 100)}%`;
}

function formatTimestamp(value: number): string {
  if (!value) return '暂无';
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(value);
}

// The relation views use the same public provenance vocabulary as the
// catalog; the shared label doubles as the source-filter key so the same
// record can never carry two different origins across Memory pages.
function formatSource(source: string): string {
  return publicMemorySourceLabel(source);
}

function publicSourceKey(source: string): string {
  return publicMemorySourceLabel(source);
}

function formatStatus(status: string): string {
  return {
    active: '使用中',
    approved: '已确认',
    archived: '已归档',
    hidden: '历史保留',
    superseded: '已合并',
    conflict: '有冲突',
    conflicted: '有冲突',
    not_for_memory: '已遗忘',
    forgotten: '已遗忘',
    disabled: '已暂停',
    suppressed: '已抑制',
  }[status] ?? '状态未知';
}

function formatEntityKind(kind: string): string {
  return {
    tag: '标签',
    group: '分组',
    atom: '记忆原子',
    book: '长期主题',
    phrase: '短语',
    memory: '记忆',
  }[kind] ?? '记忆';
}

function formatRelation(relation: string): string {
  const normalized = relation.trim().toLocaleLowerCase('en-US').replaceAll('-', '_');
  return {
    related: '相关',
    related_to: '相关',
    part_of: '属于',
    contains: '包含',
    tagged: '使用此标签',
    member: '属于',
    member_of: '属于',
    belongs_to: '属于',
    supports: '支持',
    depends_on: '依赖',
    derived_from: '来源于',
    similar: '相似',
    similar_to: '相似',
    co_occurs: '经常同时出现',
    co_occurs_with: '经常同时出现',
    alias_of: '别名',
    parent_of: '上级',
    child_of: '下级',
  }[normalized] ?? '已关联';
}

function safePublicStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item !== 'string') return [];
    const text = item.trim().slice(0, 64);
    return text ? [text] : [];
  }).slice(0, 64);
}

function groupKey(id: string): string {
  return `group:${id}`;
}

function tagKey(id: string): string {
  return `tag:${id}`;
}

function bookKey(id: string): string {
  return `book:${id}`;
}
