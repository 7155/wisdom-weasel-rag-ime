import { Boxes, Network, Tags } from 'lucide-react';
import { useMemo, useState, type KeyboardEvent } from 'react';
import { EmptyState, SegmentedControl } from '@/components/primitives';
import { ManagementSection, QueryState } from '@/features/overview/management-ui';
import { useMemoryGraphQueries } from './api';
import {
  buildGroupTagGraph,
  buildTagGraph,
  mergeMemoryGraphTags,
  parseMemoryGraph,
  truncateGraphLabel,
  type BipartiteGraphEdge,
  type BipartiteGraphLayout,
  type MemoryGroupNode,
  type MemoryTagNode,
  type PositionedBipartiteTagNode,
  type TagGraphEdge,
  type TagGraphLayout,
} from './memory-graph';

type RelationView = 'tags' | 'groups';

const relationViews = [
  { value: 'tags', label: '标签关系' },
  { value: 'groups', label: 'Group / Tag' },
] as const;

export function MemoryRelations({ enabled }: { enabled: boolean }) {
  const [view, setView] = useState<RelationView>('tags');
  const [selectedTagId, setSelectedTagId] = useState('');
  const [selectedBipartiteKey, setSelectedBipartiteKey] = useState('');
  const queries = useMemoryGraphQueries(enabled);
  const tagPayload = useMemo(() => parseMemoryGraph(queries.tags.data), [queries.tags.data]);
  const groupPayload = useMemo(() => parseMemoryGraph(queries.groups.data), [queries.groups.data]);
  const tags = useMemo(
    () => mergeMemoryGraphTags(tagPayload.tags, groupPayload.tags),
    [groupPayload.tags, tagPayload.tags],
  );
  const tagGraph = useMemo(() => buildTagGraph(tagPayload.tags), [tagPayload.tags]);
  const groupTagGraph = useMemo(() => buildGroupTagGraph(groupPayload.groups, tags), [groupPayload.groups, tags]);
  const error = (queries.tags.error ?? queries.groups.error) as Error | null;
  const pending = queries.tags.isPending || queries.groups.isPending;
  const refresh = () => void Promise.all([queries.tags.refetch(), queries.groups.refetch()]);

  return (
    <ManagementSection
      description="读取受控的 Tag 与 Group 关系图；节点和边均有明确上限，不读取原始记忆正文。"
      title="记忆关系"
    >
      <QueryState error={error} isPending={pending} onRetry={refresh}>
        <div className="memory-relations">
          <div className="memory-relations__toolbar">
            <SegmentedControl
              aria-label="关系图类型"
              items={relationViews}
              onValueChange={setView}
              value={view}
            />
            <GraphScope
              clipped={view === 'tags'
                ? tagPayload.truncated || tagGraph.clipped
                : tagPayload.truncated || groupPayload.truncated || groupTagGraph.clipped}
              groups={groupPayload.groups.length}
              tags={tags.length}
            />
          </div>

          {view === 'tags' ? (
            tagGraph.nodes.length ? (
              <TagNetwork
                graph={tagGraph}
                onSelect={setSelectedTagId}
                selectedId={selectedTagId}
              />
            ) : (
              <EmptyState description="当前标签页没有可展示的安全关系数据。" icon={Network} title="还没有标签关系" />
            )
          ) : groupTagGraph.groups.length && groupTagGraph.tags.length ? (
            <GroupTagNetwork
              graph={groupTagGraph}
              onSelect={setSelectedBipartiteKey}
              selectedKey={selectedBipartiteKey}
            />
          ) : (
            <EmptyState description="当前 Group 页还没有可与标签连接的数据。" icon={Boxes} title="还没有 Group / Tag 关系" />
          )}
        </div>
      </QueryState>
    </ManagementSection>
  );
}

function GraphScope({ clipped, groups, tags }: { clipped: boolean; groups: number; tags: number }) {
  return (
    <div className="memory-graph__scope" data-clipped={clipped || undefined} role="status">
      <strong>当前页局部图</strong>
      <span>Tag {tags} · Group {groups}</span>
      <span>{clipped ? '已截断' : '当前页完整'}</span>
    </div>
  );
}

function TagNetwork({
  graph,
  onSelect,
  selectedId,
}: {
  graph: TagGraphLayout;
  onSelect: (id: string) => void;
  selectedId: string;
}) {
  const activeId = graph.nodes.some((node) => node.id === selectedId) ? selectedId : graph.nodes[0]?.id ?? '';
  const selected = graph.nodes.find((node) => node.id === activeId) ?? null;
  const nodesById = new Map(graph.nodes.map((node) => [node.id, node]));
  const relations = selected
    ? graph.edges.filter((edge) => edge.source === selected.id || edge.target === selected.id)
    : [];

  return (
    <>
      <div className="memory-graph__viewport" role="group" aria-label="标签当前页局部关系图">
        <svg
          aria-labelledby="memory-tag-graph-title memory-tag-graph-description"
          className="memory-graph__canvas"
          height={graph.height}
          viewBox={`0 0 ${graph.width} ${graph.height}`}
          width={graph.width}
        >
          <title id="memory-tag-graph-title">标签当前页局部关系图</title>
          <desc id="memory-tag-graph-description">节点大小表示关联记忆数，连线宽度由关系权重与证据数共同决定。</desc>
          {graph.edges.map((edge) => {
            const source = nodesById.get(edge.source);
            const target = nodesById.get(edge.target);
            if (!source || !target) return null;
            const emphasized = activeId === edge.source || activeId === edge.target;
            return (
              <line
                className="memory-graph__edge"
                data-emphasized={emphasized || undefined}
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
            const accessibleLabel = `${node.label}，${node.itemCount} 条记忆，${node.edgeCount} 个连接`;
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
                <circle
                  className="memory-graph__node-shape"
                  fill={node.color}
                  r={node.radius}
                  stroke={node.color}
                />
                <text className="memory-graph__node-label" textAnchor="middle" y={-1}>
                  {truncateGraphLabel(node.label, 10)}
                </text>
                <text className="memory-graph__node-count" textAnchor="middle" y={13}>
                  {node.itemCount} 记忆
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      {selected ? (
        <TagInspector
          node={selected}
          nodesById={nodesById}
          onSelect={onSelect}
          relations={relations}
        />
      ) : null}
    </>
  );
}

function TagInspector({
  node,
  nodesById,
  onSelect,
  relations,
}: {
  node: MemoryTagNode;
  nodesById: Map<string, MemoryTagNode>;
  onSelect: (id: string) => void;
  relations: TagGraphEdge[];
}) {
  return (
    <section className="memory-graph__inspector" aria-label={`${node.label} 详情`} aria-live="polite">
      <div className="memory-graph__summary">
        <span className="memory-graph__eyebrow"><Tags aria-hidden="true" size={13} /> 已选标签</span>
        <h3>{node.label}</h3>
        <p>{node.description || '没有补充说明。'}</p>
        <dl>
          <div><dt>关联记忆</dt><dd>{node.itemCount}</dd></div>
          <div><dt>全部连接</dt><dd>{node.edgeCount}</dd></div>
          <div><dt>当前页可见</dt><dd>{relations.length}</dd></div>
        </dl>
        {node.aliases.length ? <p>别名：{node.aliases.join('、')}</p> : null}
      </div>
      <div className="memory-graph__relations">
        <h3>当前页关系</h3>
        <div className="memory-graph__table-wrap" tabIndex={0}>
          <table className="memory-graph__table">
            <caption>{node.label} 在当前页可见的标签关系</caption>
            <thead><tr><th scope="col">相关标签</th><th scope="col">关系</th><th scope="col">权重</th><th scope="col">证据</th></tr></thead>
            <tbody>
              {relations.length ? relations.map((edge) => {
                const targetId = edge.source === node.id ? edge.target : edge.source;
                const target = nodesById.get(targetId);
                return (
                  <tr key={`${edge.source}-${edge.target}-${edge.type}`}>
                    <td><button className="memory-graph__relation-link" onClick={() => onSelect(targetId)} type="button">{target?.label ?? targetId}</button></td>
                    <td>{edge.type}</td>
                    <td>{edge.weight.toFixed(2)}</td>
                    <td>{edge.evidenceCount}</td>
                  </tr>
                );
              }) : <tr><td colSpan={4}>当前页没有可见连接。</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function GroupTagNetwork({
  graph,
  onSelect,
  selectedKey,
}: {
  graph: BipartiteGraphLayout;
  onSelect: (key: string) => void;
  selectedKey: string;
}) {
  const defaultKey = graph.groups[0] ? groupKey(graph.groups[0].id) : tagKey(graph.tags[0]?.id ?? '');
  const validKeys = new Set([
    ...graph.groups.map((group) => groupKey(group.id)),
    ...graph.tags.map((tag) => tagKey(tag.id)),
  ]);
  const activeKey = validKeys.has(selectedKey) ? selectedKey : defaultKey;
  const groupsById = new Map(graph.groups.map((group) => [group.id, group]));
  const tagsById = new Map(graph.tags.map((tag) => [tag.id, tag]));
  const selectedGroup = activeKey.startsWith('group:') ? groupsById.get(activeKey.slice(6)) ?? null : null;
  const selectedTag = activeKey.startsWith('tag:') ? tagsById.get(activeKey.slice(4)) ?? null : null;
  const relations = graph.edges.filter((edge) =>
    edge.groupId === selectedGroup?.id || edge.tagId === selectedTag?.id);

  return (
    <>
      <div className="memory-graph__viewport" role="group" aria-label="Group 与 Tag 当前页双部图">
        <svg
          aria-labelledby="memory-group-graph-title memory-group-graph-description"
          className="memory-graph__canvas memory-graph__canvas--bipartite"
          height={graph.height}
          viewBox={`0 0 ${graph.width} ${graph.height}`}
          width={graph.width}
        >
          <title id="memory-group-graph-title">Group 与 Tag 当前页双部图</title>
          <desc id="memory-group-graph-description">左侧 Group 大小表示知识事件数，右侧 Tag 大小表示关联记忆数。</desc>
          <text className="memory-graph__column-title" x={80} y={25}>GROUP</text>
          <text className="memory-graph__column-title" x={760} y={25}>TAG</text>
          {graph.edges.map((edge) => {
            const group = groupsById.get(edge.groupId);
            const tag = tagsById.get(edge.tagId);
            if (!group || !tag) return null;
            const emphasized = activeKey === groupKey(group.id) || activeKey === tagKey(tag.id);
            return (
              <line
                className="memory-graph__edge memory-graph__edge--membership"
                data-emphasized={emphasized || undefined}
                key={`${edge.groupId}-${edge.tagId}`}
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
            const accessibleLabel = `Group ${group.label}，${group.eventCount} 条知识`;
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
                <rect
                  className="memory-graph__node-shape"
                  fill={group.color}
                  height={group.height}
                  rx={6}
                  stroke={group.color}
                  width={group.width}
                  x={-group.width / 2}
                  y={-group.height / 2}
                />
                <text className="memory-graph__node-label" textAnchor="middle" y={-2}>{truncateGraphLabel(group.label, 19)}</text>
                <text className="memory-graph__node-count" textAnchor="middle" y={12}>{group.eventCount} 条知识</text>
              </g>
            );
          })}
          {graph.tags.map((tag) => {
            const key = tagKey(tag.id);
            const selectedNode = key === activeKey;
            const accessibleLabel = `Tag ${tag.label}，${tag.itemCount} 条记忆`;
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
                <text className="memory-graph__bipartite-count" x={tag.radius + 8} y={12}>
                  {tag.presentOnTagGraph ? `${tag.itemCount} 记忆` : '仅见于 Group 图'}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      <BipartiteInspector
        groupsById={groupsById}
        node={selectedGroup ?? selectedTag}
        onSelect={onSelect}
        relations={relations}
        tagsById={tagsById}
      />
    </>
  );
}

function BipartiteInspector({
  groupsById,
  node,
  onSelect,
  relations,
  tagsById,
}: {
  groupsById: Map<string, MemoryGroupNode>;
  node: MemoryGroupNode | PositionedBipartiteTagNode | null;
  onSelect: (key: string) => void;
  relations: BipartiteGraphEdge[];
  tagsById: Map<string, PositionedBipartiteTagNode>;
}) {
  if (!node) return null;
  const group = 'eventCount' in node ? node : null;
  const tag = 'itemCount' in node ? node : null;
  return (
    <section className="memory-graph__inspector" aria-label={`${node.label} 详情`} aria-live="polite">
      <div className="memory-graph__summary">
        <span className="memory-graph__eyebrow">{group ? <Boxes aria-hidden="true" size={13} /> : <Tags aria-hidden="true" size={13} />} 已选{group ? ' Group' : ' Tag'}</span>
        <h3>{node.label}</h3>
        <p>{group?.note || tag?.description || '没有补充说明。'}</p>
        <dl>
          <div><dt>{group ? '知识事件' : '关联记忆'}</dt><dd>{group?.eventCount ?? tag?.itemCount ?? 0}</dd></div>
          <div><dt>当前页连接</dt><dd>{relations.length}</dd></div>
          {tag ? <div><dt>标签详情</dt><dd>{tag.presentOnTagGraph ? 'Tag 图已加载' : '仅 Group 图'}</dd></div> : null}
        </dl>
        {group?.tags.length ? <p>标签：{group.tags.join('、')}</p> : null}
      </div>
      <div className="memory-graph__relations">
        <h3>当前页成员关系</h3>
        <div className="memory-graph__table-wrap" tabIndex={0}>
          <table className="memory-graph__table">
            <caption>{node.label} 在当前页可见的 Group 与 Tag 关系</caption>
            <thead><tr><th scope="col">Group</th><th scope="col">Tag</th><th scope="col">来源</th></tr></thead>
            <tbody>
              {relations.length ? relations.map((edge) => {
                const relatedGroup = groupsById.get(edge.groupId);
                const relatedTag = tagsById.get(edge.tagId);
                return (
                  <tr key={`${edge.groupId}-${edge.tagId}`}>
                    <td><button className="memory-graph__relation-link" onClick={() => onSelect(groupKey(edge.groupId))} type="button">{relatedGroup?.label ?? edge.groupId}</button></td>
                    <td><button className="memory-graph__relation-link" onClick={() => onSelect(tagKey(edge.tagId))} type="button">{relatedTag?.label ?? edge.tagId}</button></td>
                    <td>{relatedTag?.presentOnTagGraph ? 'Group + Tag 图' : '仅 Group 图'}</td>
                  </tr>
                );
              }) : <tr><td colSpan={3}>当前页没有可见成员关系。</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
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
