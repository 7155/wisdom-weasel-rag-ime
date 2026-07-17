import { BookOpen, Boxes, Network, RefreshCw, Search, Tags } from 'lucide-react';
import {
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
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
import {
  buildGroupBookGraph,
  buildGroupTagGraph,
  buildTagGraph,
  parseMemoryGraph,
  truncateGraphLabel,
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
  { value: 'books', label: '分组 / 主题书' },
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
      description="查看标签之间，以及分组与标签或主题书之间已经记录的关系。"
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
                ...sources.map((item) => ({ value: item, label: formatSource(item) })),
              ]}
              value={source}
            />
            <Button
              aria-label="刷新记忆关系"
              leadingIcon={<RefreshCw size={14} />}
              loading={activeQuery.isFetching}
              onClick={refresh}
              size="small"
            >刷新</Button>
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
              graph={groupTagGraph}
              onSelect={selectBipartite}
              selectedKey={selectedBipartiteKey}
            />
          ) : view === 'books' && (filtered.groups.length || filtered.books.length) ? (
            <GroupBookNetwork
              availableBooks={filtered.books}
              availableGroups={filtered.groups}
              graph={groupBookGraph}
              onSelect={selectBipartite}
              selectedKey={selectedBipartiteKey}
            />
          ) : (
            <EmptyState
              description={view === 'books' ? '当前筛选没有匹配分组或主题书。' : '当前筛选没有匹配分组或标签。'}
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
  graph,
  onSelect,
  selectedId,
}: {
  availableNodes: readonly MemoryTagNode[];
  graph: TagGraphLayout;
  onSelect: (id: string) => void;
  selectedId: string;
}) {
  const activeId = availableNodes.some((node) => node.id === selectedId)
    ? selectedId
    : availableNodes[0]?.id ?? '';
  const selected = availableNodes.find((node) => node.id === activeId) ?? null;
  const nodesById = new Map(graph.nodes.map((node) => [node.id, node]));
  const entity = useMemoryEntityQuery('tag', selected?.entityId ?? '', Boolean(selected));
  const viewportRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const viewport = viewportRef.current;
    const node = graph.nodes.find((item) => item.id === activeId);
    if (!viewport || !node) return;
    const renderedWidth = Math.max(viewport.clientWidth, 820);
    const targetX = (node.x / graph.width) * renderedWidth;
    viewport.scrollLeft = Math.max(0, targetX - viewport.clientWidth / 2);
  }, [activeId, graph]);

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
          <GraphTruthNotice edgeCount={graph.edges.length} nodeCount={graph.nodes.length} />
          <div
            aria-label="标签当前页局部关系图"
            className="memory-graph__viewport"
            ref={viewportRef}
            role="group"
          >
            <svg
              aria-labelledby="memory-tag-graph-title memory-tag-graph-description"
              className="memory-graph__canvas"
              height={graph.height}
              style={{ height: graph.height }}
              viewBox={`0 0 ${graph.width} ${graph.height}`}
              width={graph.width}
            >
              <title id="memory-tag-graph-title">标签当前页局部关系图</title>
              <desc id="memory-tag-graph-description">节点大小表示关联记忆数，连线表示已经记录的标签关系。</desc>
              {graph.edges.map((edge) => {
                const source = nodesById.get(edge.source);
                const target = nodesById.get(edge.target);
                if (!source || !target) return null;
                const emphasized = activeId === edge.source || activeId === edge.target;
                return (
                  <line
                    className="memory-graph__edge"
                    data-emphasized={emphasized || undefined}
                    data-muted={!emphasized || undefined}
                    key={`${edge.source}-${edge.target}-${edge.type}`}
                    strokeWidth={edge.strokeWidth}
                    x1={source.x}
                    x2={target.x}
                    y1={source.y}
                    y2={target.y}
                  />
                );
              })}
              {graph.nodes.map((node) => {
                const selectedNode = node.id === activeId;
                const accessibleLabel = `${node.label}，${node.itemCount} 条记忆，${node.edgeCount} 个连接，来源 ${formatSource(node.source)}`;
                return (
                  <g
                    aria-label={accessibleLabel}
                    aria-pressed={selectedNode}
                    className="memory-graph__node"
                    data-selected={selectedNode || undefined}
                    key={node.id}
                    onClick={() => onSelect(node.id)}
                    onKeyDown={(event) => activateNode(event, () => onSelect(node.id))}
                    role="button"
                    tabIndex={0}
                    transform={`translate(${node.x} ${node.y})`}
                  >
                    <title>{accessibleLabel}</title>
                    <circle className="memory-graph__node-shape" fill={node.color} r={node.radius} stroke={node.color} />
                    <text className="memory-graph__node-count memory-graph__node-count--inside" textAnchor="middle" y={4}>{node.itemCount}</text>
                    <text className="memory-graph__node-label memory-graph__node-label--outside" textAnchor="middle" y={node.radius + 19}>{truncateGraphLabel(node.label, 18)}</text>
                  </g>
                );
              })}
            </svg>
          </div>
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
  graph,
  onSelect,
  selectedKey,
}: {
  availableGroups: readonly MemoryGroupNode[];
  availableTags: readonly MemoryTagNode[];
  graph: BipartiteGraphLayout;
  onSelect: (key: string) => void;
  selectedKey: string;
}) {
  const defaultKey = availableGroups[0]
    ? groupKey(availableGroups[0].id)
    : tagKey(availableTags[0]?.id ?? '');
  const validKeys = new Set([
    ...availableGroups.map((group) => groupKey(group.id)),
    ...availableTags.map((tag) => tagKey(tag.id)),
  ]);
  const activeKey = validKeys.has(selectedKey) ? selectedKey : defaultKey;
  const groupsById = new Map(graph.groups.map((group) => [group.id, group]));
  const tagsById = new Map(graph.tags.map((tag) => [tag.id, tag]));
  const selectedGroup = activeKey.startsWith('group:')
    ? availableGroups.find((group) => group.id === activeKey.slice(6)) ?? null
    : null;
  const selectedTag = activeKey.startsWith('tag:')
    ? availableTags.find((tag) => tag.id === activeKey.slice(4)) ?? null
    : null;
  const entityKind = selectedGroup ? 'group' : 'tag';
  const entityId = selectedGroup?.entityId ?? selectedTag?.entityId ?? '';
  const entity = useMemoryEntityQuery(entityKind, entityId, Boolean(entityId));

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
          <GraphTruthNotice edgeCount={graph.edges.length} nodeCount={graph.groups.length + graph.tags.length} />
          <div className="memory-graph__viewport" role="group" aria-label="分组与标签关系图">
            <svg
              aria-labelledby="memory-group-graph-title memory-group-graph-description"
              className="memory-graph__canvas memory-graph__canvas--bipartite"
              height={graph.height}
              style={{ height: graph.height }}
              viewBox={`0 0 ${graph.width} ${graph.height}`}
              width={graph.width}
            >
              <title id="memory-group-graph-title">分组与标签关系图</title>
              <desc id="memory-group-graph-description">连线表示已经记录的分组与标签成员关系。</desc>
              <text className="memory-graph__column-title" x={80} y={25}>分组</text>
              <text className="memory-graph__column-title" x={760} y={25}>标签</text>
              {graph.edges.map((edge) => {
                const group = groupsById.get(edge.groupId);
                const tag = tagsById.get(edge.tagId);
                if (!group || !tag) return null;
                const emphasized = activeKey === groupKey(group.id) || activeKey === tagKey(tag.id);
                return (
                  <line
                    aria-label={`${group.label} 到 ${tag.label}，${formatRelation(edge.relation)}，来源 ${formatSource(edge.source)}`}
                    className="memory-graph__edge memory-graph__edge--membership"
                    data-emphasized={emphasized || undefined}
                    data-muted={!emphasized || undefined}
                    key={`${edge.groupId}-${edge.tagId}`}
                    strokeWidth={Math.max(1, .8 + edge.weight)}
                    x1={group.x + group.width / 2}
                    x2={tag.x - tag.radius}
                    y1={group.y}
                    y2={tag.y}
                  />
                );
              })}
              {graph.groups.map((group) => {
                const key = groupKey(group.id);
                const selectedNode = key === activeKey;
                const accessibleLabel = `分组 ${group.label}，${group.eventCount} 个成员，来源 ${formatSource(group.source)}`;
                return (
                  <g
                    aria-label={accessibleLabel}
                    aria-pressed={selectedNode}
                    className="memory-graph__node"
                    data-selected={selectedNode || undefined}
                    key={key}
                    onClick={() => onSelect(key)}
                    onKeyDown={(event) => activateNode(event, () => onSelect(key))}
                    role="button"
                    tabIndex={0}
                    transform={`translate(${group.x} ${group.y})`}
                  >
                    <title>{accessibleLabel}</title>
                    <rect className="memory-graph__node-shape" fill={group.color} height={group.height} rx={6} stroke={group.color} width={group.width} x={-group.width / 2} y={-group.height / 2} />
                    <text className="memory-graph__node-label" textAnchor="middle" y={-2}>{truncateGraphLabel(group.label, 19)}</text>
                    <text className="memory-graph__node-count" textAnchor="middle" y={12}>{group.eventCount} 个成员</text>
                  </g>
                );
              })}
              {graph.tags.map((tag) => {
                const key = tagKey(tag.id);
                const selectedNode = key === activeKey;
                const accessibleLabel = `标签 ${tag.label}，${tag.itemCount} 条记忆，来源 ${formatSource(tag.source)}`;
                return (
                  <g
                    aria-label={accessibleLabel}
                    aria-pressed={selectedNode}
                    className="memory-graph__node"
                    data-selected={selectedNode || undefined}
                    key={key}
                    onClick={() => onSelect(key)}
                    onKeyDown={(event) => activateNode(event, () => onSelect(key))}
                    role="button"
                    tabIndex={0}
                    transform={`translate(${tag.x} ${tag.y})`}
                  >
                    <title>{accessibleLabel}</title>
                    <circle className="memory-graph__node-shape" fill={tag.color} r={tag.radius} stroke={tag.color} />
                    <text className="memory-graph__bipartite-label" x={tag.radius + 8} y={-2}>{truncateGraphLabel(tag.label, 16)}</text>
                    <text className="memory-graph__bipartite-count" x={tag.radius + 8} y={12}>{tag.itemCount} 记忆</text>
                  </g>
                );
              })}
            </svg>
          </div>
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
  graph,
  onSelect,
  selectedKey,
}: {
  availableBooks: readonly MemoryBookNode[];
  availableGroups: readonly MemoryGroupNode[];
  graph: BookBipartiteGraphLayout;
  onSelect: (key: string) => void;
  selectedKey: string;
}) {
  const defaultKey = availableGroups[0]
    ? groupKey(availableGroups[0].id)
    : bookKey(availableBooks[0]?.id ?? '');
  const validKeys = new Set([
    ...availableGroups.map((group) => groupKey(group.id)),
    ...availableBooks.map((book) => bookKey(book.id)),
  ]);
  const activeKey = validKeys.has(selectedKey) ? selectedKey : defaultKey;
  const groupsById = new Map(graph.groups.map((group) => [group.id, group]));
  const booksById = new Map(graph.books.map((book) => [book.id, book]));
  const selectedGroup = activeKey.startsWith('group:')
    ? availableGroups.find((group) => group.id === activeKey.slice(6)) ?? null
    : null;
  const selectedBook = activeKey.startsWith('book:')
    ? availableBooks.find((book) => book.id === activeKey.slice(5)) ?? null
    : null;
  const entityKind = selectedGroup ? 'group' : 'book';
  const entityId = selectedGroup?.entityId ?? selectedBook?.entityId ?? '';
  const entity = useMemoryEntityQuery(entityKind, entityId, Boolean(entityId));

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
          <GraphTruthNotice edgeCount={graph.edges.length} nodeCount={graph.groups.length + graph.books.length} />
          <div className="memory-graph__viewport" role="group" aria-label="分组与主题书关系图">
            <svg
              aria-labelledby="memory-book-graph-title memory-book-graph-description"
              className="memory-graph__canvas memory-graph__canvas--bipartite"
              height={graph.height}
              style={{ height: graph.height }}
              viewBox={`0 0 ${graph.width} ${graph.height}`}
              width={graph.width}
            >
              <title id="memory-book-graph-title">分组与主题书关系图</title>
              <desc id="memory-book-graph-description">连线表示已经记录的分组与主题书成员关系。</desc>
              <text className="memory-graph__column-title" x={80} y={25}>分组</text>
              <text className="memory-graph__column-title" x={735} y={25}>主题书</text>
              {graph.edges.map((edge) => {
                const group = groupsById.get(edge.groupId);
                const book = booksById.get(edge.bookId);
                if (!group || !book) return null;
                const emphasized = activeKey === groupKey(group.id) || activeKey === bookKey(book.id);
                return (
                  <line
                    aria-label={`${group.label} 到 ${book.label}，${formatRelation(edge.relation)}，来源 ${formatSource(edge.source)}`}
                    className="memory-graph__edge memory-graph__edge--membership"
                    data-emphasized={emphasized || undefined}
                    data-muted={!emphasized || undefined}
                    key={`${edge.groupId}-${edge.bookId}`}
                    strokeWidth={Math.max(1, .8 + edge.weight)}
                    x1={group.x + group.width / 2}
                    x2={book.x - book.width / 2}
                    y1={group.y}
                    y2={book.y}
                  />
                );
              })}
              {graph.groups.map((group) => {
                const key = groupKey(group.id);
                const selectedNode = key === activeKey;
                const accessibleLabel = `分组 ${group.label}，${group.eventCount} 个成员，来源 ${formatSource(group.source)}`;
                return (
                  <g
                    aria-label={accessibleLabel}
                    aria-pressed={selectedNode}
                    className="memory-graph__node"
                    data-selected={selectedNode || undefined}
                    key={key}
                    onClick={() => onSelect(key)}
                    onKeyDown={(event) => activateNode(event, () => onSelect(key))}
                    role="button"
                    tabIndex={0}
                    transform={`translate(${group.x} ${group.y})`}
                  >
                    <title>{accessibleLabel}</title>
                    <rect className="memory-graph__node-shape" fill={group.color} height={group.height} rx={6} stroke={group.color} width={group.width} x={-group.width / 2} y={-group.height / 2} />
                    <text className="memory-graph__node-label" textAnchor="middle" y={-2}>{truncateGraphLabel(group.label, 19)}</text>
                    <text className="memory-graph__node-count" textAnchor="middle" y={12}>{group.eventCount} 个成员</text>
                  </g>
                );
              })}
              {graph.books.map((book) => {
                const key = bookKey(book.id);
                const selectedNode = key === activeKey;
                const accessibleLabel = `主题书 ${book.label}，${book.memberCount} 条记忆，${book.edgeCount} 个分组，来源 ${formatSource(book.source)}`;
                return (
                  <g
                    aria-label={accessibleLabel}
                    aria-pressed={selectedNode}
                    className="memory-graph__node"
                    data-selected={selectedNode || undefined}
                    key={key}
                    onClick={() => onSelect(key)}
                    onKeyDown={(event) => activateNode(event, () => onSelect(key))}
                    role="button"
                    tabIndex={0}
                    transform={`translate(${book.x} ${book.y})`}
                  >
                    <title>{accessibleLabel}</title>
                    <rect className="memory-graph__node-shape" fill={book.color} height={book.height} rx={4} stroke={book.color} width={book.width} x={-book.width / 2} y={-book.height / 2} />
                    <text className="memory-graph__node-label" textAnchor="middle" y={-2}>{truncateGraphLabel(book.label, 19)}</text>
                    <text className="memory-graph__node-count" textAnchor="middle" y={12}>{book.memberCount} 条记忆</text>
                  </g>
                );
              })}
            </svg>
          </div>
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
            aria-pressed={activeId === node.id}
            data-selected={activeId === node.id || undefined}
            key={node.id}
            onClick={() => onSelect(node.id)}
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
            <button aria-pressed={activeKey === key} data-selected={activeKey === key || undefined} key={key} onClick={() => onSelect(key)} type="button">
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
            <button aria-pressed={activeKey === key} data-selected={activeKey === key || undefined} key={key} onClick={() => onSelect(key)} type="button">
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
    <aside className="memory-node-list memory-node-list--bipartite" aria-label="分组与主题书列表">
      <header><strong>分组</strong><span>{groups.length}</span></header>
      <div>
        {groups.map((group) => {
          const key = groupKey(group.id);
          return (
            <button aria-pressed={activeKey === key} data-selected={activeKey === key || undefined} key={key} onClick={() => onSelect(key)} type="button">
              <span><strong>{group.label}</strong><small>{group.note || '无说明'}</small></span>
              <span><b>{group.eventCount}</b><small>{group.bookIds.length} 主题书 · {formatSource(group.source)}</small></span>
            </button>
          );
        })}
      </div>
      <header><strong>主题书</strong><span>{books.length}</span></header>
      <div className="memory-node-list__scroll">
        {books.map((book) => {
          const key = bookKey(book.id);
          return (
            <button aria-pressed={activeKey === key} data-selected={activeKey === key || undefined} key={key} onClick={() => onSelect(key)} type="button">
              <span><strong>{book.label}</strong><small>{book.description || '无说明'}</small></span>
              <span><b>{book.memberCount}</b><small>{book.edgeCount} 分组 · {formatSource(book.source)}</small></span>
            </button>
          );
        })}
      </div>
    </aside>
  );
}

function GraphTruthNotice({ edgeCount, nodeCount }: { edgeCount: number; nodeCount: number }) {
  return (
    <p className="memory-graph__truth" data-empty={edgeCount === 0 || undefined}>
      {edgeCount > 0
        ? `当前显示 ${nodeCount} 项记忆与 ${edgeCount} 条已记录关系。`
        : `${nodeCount} 项记忆目前没有已记录关系。`}
    </p>
  );
}

function GraphLegend({ view }: { view: RelationView }) {
  return (
    <div className="memory-graph__legend" role="group" aria-label="关系图图例">
      {view === 'tags' ? <span><i data-shape="tag" />标签 · 大小表示记忆量</span> : <span><i data-shape="group" />分组</span>}
      {view === 'groups' ? <span><i data-shape="tag" />标签</span> : null}
      {view === 'books' ? <span><i data-shape="book" />主题书</span> : null}
      <span><i data-shape="edge" />当前节点的已记录关系</span>
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
          {' '}已选{kind === 'group' ? '分组' : kind === 'book' ? '主题书' : '标签'}
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
          : kind === 'book' ? '这个主题书尚未加入分组。' : '这个标签暂无已记录关系。'}
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

function formatSource(source: string): string {
  return {
    local: '本地记忆',
    smart: '智能整理',
    user: '用户编辑',
    import: '导入',
    other: '其他来源',
  }[publicSourceKey(source)] ?? '其他来源';
}

function publicSourceKey(source: string): 'local' | 'smart' | 'user' | 'import' | 'other' {
  const normalized = source.toLocaleLowerCase('en-US');
  if (!normalized || normalized === 'local') return 'local';
  if (normalized === 'smart' || normalized.includes('dsv4') || normalized.includes('deepseek')) return 'smart';
  if (normalized === 'user' || normalized.includes('user')) return 'user';
  if (normalized === 'import' || normalized.includes('import')) return 'import';
  if (normalized.includes('sqlite') || normalized.includes('memory_')) return 'local';
  return 'other';
}

function formatStatus(status: string): string {
  return {
    active: '使用中',
    approved: '已确认',
    archived: '已归档',
    disabled: '已暂停',
    suppressed: '已抑制',
  }[status] ?? '状态未知';
}

function formatEntityKind(kind: string): string {
  return {
    tag: '标签',
    group: '分组',
    atom: '记忆原子',
    book: '主题书',
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

function activateNode(event: KeyboardEvent<SVGGElement>, select: () => void) {
  if (event.key !== 'Enter' && event.key !== ' ') return;
  event.preventDefault();
  select();
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
